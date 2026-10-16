"""Streaming, fold-local probability reservoirs over partitioned feature tables."""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

from wildfire_kz.config import Config
from wildfire_kz.data import AccessGuard


@dataclass
class FeatureStore:
    """A predicate-only view; rows are sampled only after a fold view is defined."""

    path: Path
    cfg: Config
    years: list[int]
    cells: set[str] | None = None
    final: bool = False
    _cache: ClassVar[OrderedDict[str, pd.DataFrame]] = OrderedDict()
    _cache_budget_bytes: ClassVar[int] = 512 * 1024 * 1024

    def view(self, years: list[int], cells: set[str] | None = None) -> FeatureStore:
        return FeatureStore(
            self.path, self.cfg, years, self.cells if cells is None else cells, self.final
        )

    def batches(self, columns: list[str] | None = None) -> Iterator[pd.DataFrame]:
        AccessGuard(self.cfg, final=self.final).check(self.years)
        predicate = ds.field("year").isin(self.years)
        if self.cells is not None:
            predicate &= ds.field("cell_id").isin(sorted(self.cells))
        scanner = ds.dataset(self.path, partitioning="hive", format="parquet").scanner(
            filter=predicate, columns=columns, batch_size=self.cfg.data.chunk_rows
        )
        for batch in scanner.to_batches():
            if batch.num_rows:
                yield batch.to_pandas()

    def sample(self, *, training: bool) -> pd.DataFrame:
        """Two-pass uniform reservoirs by month x broad cover; all positives retained.

        Inclusion probabilities are calculated from this view only. Evaluation is
        unbalanced when it fits; otherwise probability sampling retains design weights.
        """
        AccessGuard(self.cfg, final=self.final).check(self.years)
        signature = [
            (str(p.relative_to(self.path)), p.stat().st_size, p.stat().st_mtime_ns)
            for p in sorted(self.path.rglob("*.parquet"))
        ]
        cache_key = hashlib.sha256(
            repr(
                (
                    str(self.path.resolve()),
                    signature,
                    self.years,
                    sorted(self.cells) if self.cells is not None else None,
                    training,
                    self.cfg.model_dump(mode="json"),
                )
            ).encode()
        ).hexdigest()
        if cache_key in self._cache:
            self._cache.move_to_end(cache_key)
            return self._cache[cache_key]
        counts: dict[tuple[int, str], list[int]] = {}
        for frame in self.batches(["day", "landcover", "label"]):
            for (month, cover), group in frame.groupby(
                [frame.day.dt.month, "landcover"], observed=True
            ):
                key = (int(str(month)), str(cover))
                item = counts.setdefault(key, [0, 0])
                item[0] += int(group.label.sum())
                item[1] += int((group.label == 0).sum())
        total = sum(sum(v) for v in counts.values())
        total_positive = sum(v[0] for v in counts.values())
        total_negative = total - total_positive
        allocations = {}
        for key, (positives, negatives) in counts.items():
            if training and self.cfg.sampling.mode == "probability":
                desired = max(
                    self.cfg.sampling.minimum_negatives,
                    int(np.ceil(positives * self.cfg.sampling.negative_ratio)),
                )
            elif not training and total > self.cfg.data.maximum_evaluation_rows:
                budget = max(1, self.cfg.data.maximum_evaluation_rows - total_positive)
                desired = max(1, int(np.ceil(budget * negatives / max(1, total_negative))))
            else:
                desired = negatives
            allocations[key] = min(negatives, desired)
        reservoirs: dict[tuple[int, str], pd.DataFrame] = {}
        positives_list = []
        rng = np.random.default_rng(self.cfg.seed)
        for frame in self.batches():
            positive = frame[frame.label == 1].copy()
            positive["q"], positive["weight"] = 1.0, 1.0
            positives_list.append(positive)
            for (month, cover), negative in frame[frame.label == 0].groupby(
                [frame.loc[frame.label == 0, "day"].dt.month, "landcover"], observed=True
            ):
                key = (int(str(month)), str(cover))
                keep = allocations[key]
                if not keep:
                    continue
                candidate = negative.assign(_priority=rng.random(len(negative)))
                if key in reservoirs:
                    candidate = pd.concat([reservoirs[key], candidate], ignore_index=True)
                reservoirs[key] = candidate.nsmallest(keep, "_priority")
        pieces = positives_list
        for key, negative in reservoirs.items():
            negative = negative.drop(columns="_priority").copy()
            negative["q"] = allocations[key] / counts[key][1]
            negative["weight"] = 1 / negative.q
            pieces.append(negative)
        if not pieces:
            raise ValueError("Empty feature view")
        result = (
            pd.concat(pieces, ignore_index=True)
            .sort_values(["day", "cell_id"])
            .reset_index(drop=True)
        )
        size = int(result.memory_usage(deep=True).sum())
        if size < self._cache_budget_bytes:
            while (
                self._cache
                and sum(int(v.memory_usage(deep=True).sum()) for v in self._cache.values()) + size
                > self._cache_budget_bytes
            ):
                self._cache.popitem(last=False)
            self._cache[cache_key] = result
        return result
