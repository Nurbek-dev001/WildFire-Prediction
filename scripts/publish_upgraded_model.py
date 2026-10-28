"""Verify all upgraded rasters, prepare a report, and install the model map assets."""

from __future__ import annotations

import gzip
import html
import json
import shutil
import struct

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import rowcol

from wildfire_kz import model_upgrade as mu
from wildfire_kz.data import checksum, dump_json

RUN = mu.ROOT / "runs/model_stack_v5"
DIST = mu.ROOT / "platform/dist"


def main() -> None:
    mu.verify_release(RUN / "release.json")
    result = json.loads((RUN / "evaluation.json").read_text())
    for name, digest in result["outputs"].items():
        if checksum(RUN / name) != digest:
            raise ValueError(f"Evaluation changed: {name}")
    manifest = json.loads((RUN / "site_assets/forecast-manifest.json").read_text())
    rows = list(struct.iter_unpack("<hhfffH8H", (DIST / "assets/cells.bin").read_bytes()))
    # Native grid centres, in the exact browser cell order.
    xs = np.array([(r[1] + 0.5) * 5000 for r in rows])
    ys = np.array([(r[0] + 0.5) * 5000 for r in rows])
    counts = []
    for day, proof in manifest["prediction_assets"].items():
        path = RUN / f"site_assets/predictions/{day}.f16.gz"
        raster = RUN / f"maps/probability_{day}.tif"
        if checksum(path) != proof["payload_sha256"] or checksum(raster) != proof["raster_sha256"]:
            raise ValueError(f"Map bytes changed: {day}")
        b = np.frombuffer(gzip.decompress(path.read_bytes()), dtype="uint8")
        p = np.frombuffer(b.reshape(2, -1).T.tobytes(), dtype="<f2").astype("float32")
        with rasterio.open(raster) as r:
            rr, cc = rowcol(r.transform, xs, ys)
            image = r.read(1)
            actual = image[rr, cc]
            actual[actual == r.nodata] = np.nan
            if not np.array_equal(actual, p, equal_nan=True):
                raise ValueError(f"Raster/browser differ: {day}")
            if r.tags()["release_sha256"] != manifest["release_sha256"]:
                raise ValueError("Raster release differs")
        if int(np.isfinite(p).sum()) != proof["finite_cells"]:
            raise ValueError("Coverage differs")
        if np.any((p[np.isfinite(p)] < 0) | (p[np.isfinite(p)] > 1)):
            raise ValueError("Invalid probabilities")
        counts.append(
            {
                "day": day,
                "eligible_cells": proof["finite_cells"],
                "alerts": int(np.sum(p >= manifest["threshold"])),
            }
        )
    if len(counts) != 731:
        raise ValueError("All 731 dates are required")
    destination = DIST / "upgrade"
    destination.mkdir(exist_ok=True)
    for name in [
        "release.json",
        "frozen.json",
        "selection.json",
        "training.json",
        "plan.json",
        "comparison.csv",
        "joint_comparison.csv",
        "metrics.csv",
        "cluster_intervals.csv",
        "evaluation.json",
    ]:
        shutil.copyfile(RUN / name, destination / name)
    pd.DataFrame(counts).to_csv(destination / "daily_alert_counts.csv", index=False)
    selection = json.loads((RUN / "selection.json").read_text())
    frozen = json.loads((RUN / "frozen.json").read_text())
    combined = {m["model"]: m for m in result["metrics"] if m["period"] == "2023–2024"}
    old, new = combined["xgboost_original"], combined["xgboost_spatiotemporal"]
    dump_json(
        destination / "comparison_spec.json",
        {
            "claim": "Recall increased and precision decreased on the previously evaluated test",
            "visual_form": "two dot-and-interval panels",
            "metrics": ["precision", "recall"],
            "unit": "percent of eligible cell-days",
            "direction": "higher is better",
            "order": ["Original XGBoost", "XGBoost + learned stack"],
            "uncertainty": "95% percentile intervals; 1000 paired 100 km by 30 day cluster resamples; seed 42",
            "evidence": ["metrics.csv", "cluster_intervals.csv"],
            "width_px": 1000,
            "height_px": 400,
            "output_formats": ["png", "svg"],
            "ap_uncertainty": "not estimated; AP retained in exact-value table",
        },
    )
    intervals = pd.read_csv(RUN / "cluster_intervals.csv")
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 11,
            "text.color": "#171717",
            "axes.labelcolor": "#171717",
            "axes.edgecolor": "#b6b6b0",
            "svg.fonttype": "none",
        }
    )
    fig, axes = plt.subplots(1, 2, figsize=(10, 4), layout="constrained")
    for ax, key, title in zip(
        axes, ["precision", "recall"], ["Precision (%)", "Recall (%)"], strict=True
    ):
        for y, tag, score, color, marker in [
            (1, "original", old, "#777777", "s"),
            (0, "new", new, "#1F6F5F", "o"),
        ]:
            ci = intervals[(intervals.model == tag) & (intervals.metric == key)].iloc[0]
            v = score[key] * 100
            ax.errorbar(
                v,
                y,
                xerr=[[v - ci.lower * 100], [ci.upper * 100 - v]],
                fmt=marker,
                color=color,
                markersize=7,
                elinewidth=1,
                capsize=4,
            )
            ax.annotate(
                f"{v:.2f}%",
                (v, y),
                xytext=(0, 15),
                textcoords="offset points",
                ha="center",
                fontsize=11,
            )
        ax.set_yticks([1, 0], ["Original XGBoost", "XGBoost + stack"])
        ax.set_ylim(-0.6, 1.65)
        ax.set_xlim(0, 15)
        ax.set_xticks([0, 5, 10, 15])
        ax.set_xlabel(title)
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.tick_params(axis="y", length=0)
        ax.grid(axis="x", color="#E4E7E5", linewidth=0.6)
        ax.set_axisbelow(True)
    fig.suptitle(
        "Recall increased; precision decreased · 2023–2024", fontsize=14, x=0.02, ha="left"
    )
    fig.savefig(destination / "comparison.png", dpi=200)
    fig.savefig(destination / "comparison.svg")
    plt.close(fig)
    from PIL import Image, ImageOps

    ImageOps.grayscale(Image.open(destination / "comparison.png")).save(
        RUN / "comparison_grayscale.png"
    )

    def pct(v):
        return f"{v * 100:.2f}%".replace(".", ",")

    metric_rows = "".join(
        f"<tr><td>{label}</td><td>{pct(v['precision'])}</td><td>{pct(v['recall'])}</td><td>{v['f1']:.4f}</td><td>{v['average_precision']:.5f}</td><td>{v['roc_auc']:.4f}</td></tr>"
        for label, v in [("Исходный XGBoost", old), ("XGBoost + обученный второй уровень", new)]
    )
    comparison = pd.read_csv(RUN / "comparison.csv")
    candidate_table = comparison[["name", "precision", "recall", "average_precision"]].to_html(
        index=False, border=0
    )
    page = f"""<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Steppe · новая модель</title><style>body{{margin:0;background:#f8f9f4;color:#193d35;font:15px/1.7 'Segoe UI',sans-serif}}main{{max-width:1050px;margin:auto;padding:36px 24px}}h1{{font-size:clamp(30px,5vw,44px);line-height:1.2}}h2{{margin-top:34px}}a{{color:#315f4a}}table{{border-collapse:collapse;width:100%;font-size:13px;text-align:right}}td,th{{padding:12px;border-bottom:1px solid #dfe5d7}}td:first-child,th:first-child{{text-align:left}}.table{{overflow:auto}}.note{{padding:18px;background:#eaf0df;border-left:3px solid #ce7138}}img{{width:100%}}code{{overflow-wrap:anywhere;font-size:11px}}.links{{display:flex;gap:18px;flex-wrap:wrap}}</style><main><a href="../">← Карта</a><p>STEPPE / ПЕРЕОБУЧЕННАЯ МОДЕЛЬ</p><h1>Новые признаки.<br>Повторное обучение.</h1><p>Выбран вариант <strong>{html.escape(selection["selected"]["name"])}</strong>. Исходный XGBoost обучен на 2015–2021. Новый логистический уровень обучен на прогнозах 2019–2021, каждый из которых построен только по более ранним годам. Регуляризация выбрана на 2021; вес смеси 50/50 проверен на 2021 и 2022. Калибровка и порог — 2022.</p><div class="note">Данные 2023–2024 не использовались для обучения, выбора признаков, кандидата или порога. Они открыты для этой оценки после фиксации нового релиза. Тест уже публиковался ранее, поэтому это повторная оценка, а не новый независимый holdout.</div><h2>Результат: 2023–2024</h2><div class="table"><table><thead><tr><th>Модель</th><th>Precision</th><th>Recall</th><th>F1</th><th>AP</th><th>ROC-AUC</th></tr></thead><tbody>{metric_rows}</tbody></table></div><img src="comparison.png" alt="Сравнение precision, recall и AP исходной и переобученной моделей"><p>На 2021 модели сравнивались при precision ≥10%. Рабочий порог выбран на 2022 при precision не ниже исходного уровня 2022 (5,95%). На тесте precision всё же снизился до 7,36%; полного сохранения точности не достигнуто. Все метрики учитывают вероятности отбора отрицательных примеров. Цель — первое спутниковое обнаружение нового события в ячейке 5 × 5 км.</p><h2>Проверка кандидатов: 2021</h2><div class="table">{candidate_table}</div><p>Это таблица данных для выбора, а не результаты 2023–2024. Значения precision, recall и AP здесь представлены долями.</p><h2>Совместная проверка 2021 и 2022</h2><div class="table">{pd.read_csv(RUN / "joint_comparison.csv").to_html(index=False, border=0)}</div><p>Для выбора веса максимизировался минимальный относительный прирост полноты между двумя годами; AP должна была улучшиться на обоих. Вес 0,5 удовлетворил условию, вариант 0,75 — нет. В selection.json поля precision/recall/AP внутри selected относятся к начальному выбору регуляризации на 2021, а окончательные значения выбранной смеси находятся в joint_criterion и joint_comparison.csv.</p><h2>Что изменилось</h2><p>К исходным 26 признакам добавлены шесть признаков активности пожаров в прошлые периоды. Обученный второй уровень использует их и logit оценки XGBoost. Итоговая оценка до калибровки — 50% оценки XGBoost и 50% оценки второго уровня; это новая модель вероятностей, а не только новый порог. История строится по уникальным активным ячейкам-дням в квадратных окрестностях 15 и 55 км, в окнах 7, 30, 90 и 365 дней. Все окна заканчиваются минимум за двое суток до цели. Будущие метки и связи событий не используются.</p><p>Калибровка 2022: precision {pct(frozen["calibration_metrics"]["precision"])}, recall {pct(frozen["calibration_metrics"]["recall"])}; фиксированный порог {pct(frozen["threshold"])}. Сложность выбрана на 2021; вес смеси выбран по улучшению recall и AP на обоих годах до 2023. Эти результаты использовались для настройки, а не как независимая оценка.</p><p>Карта использует float16-округление вероятностей, объявленное до финальной оценки. Порог и метрики рассчитаны на тех же округлённых значениях. Все 731 браузерных массива независимо сверены с GeoTIFF. Отсутствующие данные сохранены; оперативная пригодность на текущую дату не подтверждена.</p><p>Релиз: <code>{manifest["release_sha256"]}</code></p><div class="links"><a href="metrics.csv">Метрики по годам CSV</a><a href="cluster_intervals.csv">Парные интервалы CSV</a><a href="comparison.csv">Выбор кандидатов CSV</a><a href="joint_comparison.csv">Проверки 2021/2022 CSV</a><a href="release.json">Фиксация релиза JSON</a><a href="plan.json">План обучения JSON</a><a href="daily_alert_counts.csv">Сигналы по датам CSV</a><a href="../results/">Исходный отчёт</a><a href="../alerts/">Предыдущее изменение порогов</a></div></main></html>"""
    page = page.replace(
        "</style>",
        ".figure{overflow-x:auto}.figure img{min-width:900px}figure+figcaption{font-size:13px}</style>",
    )
    page = page.replace(
        '<img src="comparison.png" alt="Сравнение precision, recall и AP исходной и переобученной моделей">',
        '<div class="figure"><img src="comparison.png" alt="Precision снизился, recall вырос; точки и 95-процентные интервалы"></div><p>Показаны 95% процентильные интервалы: 1000 парных блочных повторов по 100 км × 30 дней, seed 42. Метрики относятся к взвешенной выборке ячеек-дней. Для AP интервал в этом сравнении не рассчитан.</p>',
    )
    (destination / "index.html").write_text(page, encoding="utf-8")
    dump_json(
        destination / "complete.json",
        {
            "synthetic": False,
            "release_sha256": manifest["release_sha256"],
            "verified_dates": 731,
            "outputs": {
                p.name: checksum(p)
                for p in destination.iterdir()
                if p.is_file() and p.name != "complete.json"
            },
        },
    )
    previous = RUN / "previous_site_assets"
    previous.mkdir(exist_ok=True)
    original = DIST / "assets/forecast-manifest.json"
    if not (previous / "forecast-manifest.json").exists():
        shutil.copyfile(original, previous / "forecast-manifest.json")
    old_predictions = previous / "predictions"
    old_predictions.mkdir(exist_ok=True)
    # Explicit, nonrecursive moves; both absolute targets are confined to this workspace.
    for path in (DIST / "assets/predictions").glob("*.f32.gz"):
        target = (old_predictions / path.name).resolve()
        if not path.resolve().is_relative_to(mu.ROOT.resolve()) or not target.is_relative_to(
            mu.ROOT.resolve()
        ):
            raise ValueError("Unsafe archive destination")
        if not target.exists():
            path.replace(target)
    for path in (RUN / "site_assets/predictions").glob("*.f16.gz"):
        shutil.copyfile(path, DIST / "assets/predictions" / path.name)
    shutil.copyfile(RUN / "site_assets/forecast-manifest.json", original)
    print(
        json.dumps(
            {
                "verified_dates": 731,
                "precision": new["precision"],
                "recall": new["recall"],
                "release_sha256": manifest["release_sha256"],
            }
        )
    )


if __name__ == "__main__":
    main()
