"""Partitioned Parquet helpers (pyarrow) used for all tabular artifacts."""

from __future__ import annotations

import shutil
from collections.abc import Iterable, Sequence
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq


def write_partitioned(df: pd.DataFrame, root: Path, partition_cols: Sequence[str],
                      overwrite: bool = True) -> None:
    """Write a hive-partitioned Parquet dataset (``root/year=2019/part-0.parquet``)."""
    if overwrite and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_to_dataset(table, root_path=str(root), partition_cols=list(partition_cols))


def write_partition(df: pd.DataFrame, root: Path, key: str, value: object,
                    name: str = "part-0.parquet") -> Path:
    """Write (replace) a single hive partition, e.g. ``year=2019``."""
    part_dir = root / f"{key}={value}"
    if part_dir.exists():
        shutil.rmtree(part_dir)
    part_dir.mkdir(parents=True, exist_ok=True)
    path = part_dir / name
    df.to_parquet(path, index=False)
    return path


def partition_values(root: Path, key: str) -> list[str]:
    if not root.exists():
        return []
    return sorted(p.name.split("=", 1)[1] for p in root.glob(f"{key}=*") if p.is_dir())


def read_partitions(root: Path, key: str, values: Iterable[object] | None = None,
                    columns: list[str] | None = None) -> pd.DataFrame:
    """Read selected hive partitions; the partition key is restored as an int column if numeric."""
    wanted = None if values is None else {str(v) for v in values}
    frames = []
    for val in partition_values(root, key):
        if wanted is not None and val not in wanted:
            continue
        files = sorted((root / f"{key}={val}").glob("*.parquet"))
        for f in files:
            frame = pd.read_parquet(f, columns=columns)
            frame[key] = int(val) if val.lstrip("-").isdigit() else val
            frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=[*(columns or []), key])
    return pd.concat(frames, ignore_index=True)


def dataset_rows(root: Path) -> int:
    return int(ds.dataset(str(root), format="parquet", partitioning="hive").count_rows())
