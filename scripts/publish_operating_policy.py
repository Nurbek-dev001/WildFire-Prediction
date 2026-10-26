"""Package the frozen alert policy without changing any model or probability map."""

from __future__ import annotations

import html
import json
import shutil
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import PercentFormatter

from wildfire_kz.data import checksum, dump_json
from wildfire_kz.public_payloads import decode

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs/public_hindcast"
SOURCE = RUN / "operating_v2"
DIST = ROOT / "platform/dist"


def main() -> None:
    policy_path, result_path = SOURCE / "policy.json", SOURCE / "evaluation.json"
    policy, result = json.loads(policy_path.read_text()), json.loads(result_path.read_text())
    if result["policy_sha256"] != checksum(policy_path):
        raise ValueError("Policy differs from the fixed evaluation")
    for name, digest in policy["original_artifacts"].items():
        if checksum(RUN / name) != digest:
            raise ValueError(f"Original artifact changed: {name}")
    for name, digest in result["outputs"].items():
        if checksum(SOURCE / name) != digest:
            raise ValueError(f"Evaluation changed: {name}")
    saved = pd.read_parquet(RUN / "evaluate/predictions_xgboost.parquet", columns=["probability"])
    p = saved.probability.to_numpy()
    for profile in policy["profiles"].values():
        if not np.array_equal(p >= profile["threshold"], p.astype("float32") >= profile["threshold"]):
            raise ValueError("Browser float32 decisions differ from evaluated decisions")
    manifest_path = DIST / "assets/forecast-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    burdens = []
    for day, proof in manifest["prediction_assets"].items():
        path = DIST / f"assets/predictions/{day}.f32.gz"
        if checksum(path) != proof["payload_sha256"]:
            raise ValueError(f"Probability map changed: {day}")
        values = decode(path.read_bytes(), manifest["format"])
        finite = np.isfinite(values)
        if int(finite.sum()) != proof["finite_cells"]:
            raise ValueError(f"Coverage differs: {day}")
        for key, profile in policy["profiles"].items():
            alerts = int(np.sum(finite & (values >= profile["threshold"])))
            burdens.append({"day": day, "profile": key, "eligible_cells": int(finite.sum()),
                            "alert_cells": alerts, "threshold": profile["threshold"]})
    burden = pd.DataFrame(burdens)
    burden.to_csv(SOURCE / "full_grid_alert_counts.csv", index=False)
    destination = DIST / "alerts"
    destination.mkdir(exist_ok=True)
    for name in ["policy.json", "evaluation.json", "metrics.csv", "cluster_intervals.csv",
                 "calibration_curve_plot.csv", "full_grid_alert_counts.csv"]:
        shutil.copyfile(SOURCE / name, destination / name)
    curve = pd.read_csv(SOURCE / "calibration_curve.csv.gz")
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4), layout="constrained")
    axes[0].plot(curve.recall, curve.precision, color="#244f41", linewidth=1.1)
    axes[0].set(xlim=(0, .6), ylim=(0, .15), xlabel="Recall", ylabel="Precision",
                title="2022: threshold selection only")
    colors = {"precision": "#84966e", "balanced": "#244f41", "coverage": "#ce7138"}
    labels = {"precision": "Original F1", "balanced": "Balance F2", "coverage": "Recall >=30%"}
    for key, profile in policy["profiles"].items():
        m = profile["calibration_metrics"]
        axes[0].scatter(m["recall"], m["precision"], color=colors[key], label=labels[key], zorder=3)
    axes[0].legend(frameon=False, fontsize=8)
    keys = list(policy["profiles"])
    x = np.arange(3)
    axes[1].bar(x-.18, [result["metrics"][k]["precision"] for k in keys], .36, color="#84966e", label="Precision")
    axes[1].bar(x+.18, [result["metrics"][k]["recall"] for k in keys], .36, color="#244f41", label="Recall")
    axes[1].set(xticks=x, xticklabels=[labels[k] for k in keys], ylabel="Rate", ylim=(0, .42),
                title="2023–2024: fixed-policy reassessment")
    axes[1].legend(frameon=False, fontsize=8)
    for ax in axes:
        ax.yaxis.set_major_formatter(PercentFormatter(1))
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", alpha=.2)
    axes[0].xaxis.set_major_formatter(PercentFormatter(1))
    fig.savefig(destination / "tradeoff.png", dpi=170)
    plt.close(fig)
    pct = lambda value: f"{value*100:.2f}%".replace(".", ",")
    rows, calibration_rows = [], []
    full_counts = burden.groupby("profile").alert_cells.sum()
    for key, profile in policy["profiles"].items():
        m = result["metrics"][key]
        rows.append(f'<tr{" class=selected" if key==policy["default_profile"] else ""}><td>{html.escape(profile["label"])}</td><td>{pct(profile["threshold"])}</td><td>{pct(m["precision"])}</td><td>{pct(m["recall"])}</td><td>{m["f1"]:.4f}</td><td>{m["f2"]:.4f}</td><td>{pct(m["alert_fraction"])}</td><td>{int(full_counts[key]):,}</td></tr>')
        m = profile["calibration_metrics"]
        calibration_rows.append(f'<tr><td>{html.escape(profile["label"])}</td><td>{pct(m["precision"])}</td><td>{pct(m["recall"])}</td><td>{m["f2"]:.4f}</td></tr>')
    intervals = pd.read_csv(SOURCE / "cluster_intervals.csv")
    ci = intervals.loc[(intervals.profile=="balanced") & (intervals.metric=="recall")].iloc[0]
    difference = intervals.loc[(intervals.profile=="balanced minus precision") & (intervals.metric=="f2")].iloc[0]
    page = f'''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Steppe · баланс precision и recall</title>
<style>body{{margin:0;background:#f8f9f4;color:#193d35;font:15px/1.7 'Segoe UI',sans-serif}}main{{max-width:1120px;margin:auto;padding:40px 24px}}a{{color:#315f4a}}h1{{font-size:clamp(29px,5vw,43px);line-height:1.15;margin:35px 0 18px}}h2{{font-size:23px;margin-top:38px}}.eyebrow{{font-size:12px;letter-spacing:2px;color:#7d8981}}.note{{padding:18px 22px;background:#edf1e5;border-left:3px solid #ce7138}}.table-wrap{{overflow:auto}}table{{border-collapse:collapse;width:100%;font-size:13px;text-align:right;white-space:nowrap}}td,th{{padding:13px 12px;border-bottom:1px solid #dfe5d7}}th:first-child,td:first-child{{text-align:left}}.selected{{background:#e5eddb;font-weight:600}}img{{display:block;width:100%;margin:25px 0}}code{{overflow-wrap:anywhere;font-size:12px}}.links{{display:flex;flex-wrap:wrap;gap:12px 24px}}small{{color:#6e7e6a}}</style>
<main><a href="../">← Вернуться к карте</a><p class="eyebrow">STEPPE / РЕЖИМЫ ПРЕДУПРЕЖДЕНИЙ V2</p><h1>Больше обнаруженных событий.<br>Измеримый компромисс.</h1>
<p>По умолчанию на карте — <strong>«Баланс · F2»</strong>. Порог {pct(policy["profiles"]["balanced"]["threshold"])} выбран по максимуму взвешенного F2 на 2022 году. В формуле F2 полнота получает больший вес. XGBoost, калибровка и сами вероятности не менялись.</p>
<div class="note">Все новые пороги выбраны только по 2022 году. Данные 2023–2024 использованы после фиксации порогов для повторной оценки. Их результаты уже были опубликованы ранее: это повторная проверка на прежнем тесте, а не новая независимая контрольная выборка.</div>
<h2>Результат на 2023–2024</h2><div class="table-wrap"><table><thead><tr><th>Режим</th><th>Порог</th><th>Precision</th><th>Recall</th><th>F1</th><th>F2</th><th>Доля сигналов*</th><th>Сигналы на полной сетке**</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<p><small>* Доля ячеек-дней по выборке с весами отбора. ** Точное число ячеек-дней с предупреждением по всем 731 картам; несколько суток одной ячейки считаются отдельно. Это разные оценки нагрузки, их не следует отождествлять.</small></p>
<p>Полнота режима F2: 95% интервал {pct(ci.lower)}–{pct(ci.upper)}. Парный 95% интервал прироста F2 относительно прежнего режима: {difference.lower:.4f}–{difference.upper:.4f}. Использованы 1000 одинаковых блочных повторов: 100 км × 30 дней.</p>
<p>Больший охват сопровождается большим числом ложных сигналов. «Охват ≥30%» означает ограничение на полноту <strong>в 2022 году</strong>; на иной дате или территории этот уровень не гарантируется. Цель — первые спутниковые обнаружения новых растительных пожаров в ячейках 5 × 5 км, без оценки ущерба.</p>
<img src="tradeoff.png" alt="Слева кривая precision-recall на 2022 году и три порога; справа повторная оценка фиксированных режимов на 2023–2024">
<h2>Данные, по которым выбирались пороги: 2022</h2><div class="table-wrap"><table><thead><tr><th>Режим</th><th>Precision</th><th>Recall</th><th>F2</th></tr></thead><tbody>{''.join(calibration_rows)}</tbody></table></div>
<p>197 096 строк, 10 115 положительных. Отрицательные примеры имеют веса отбора. Общая исходная частота событий с учётом весов: {pct(policy["calibration_prevalence"])}. Прежний режим максимизирует F1; «Баланс» — F2; «Охват» — F2 при recall ≥30%. При равенстве целевой функции выбирается наибольший порог.</p>
<h2>Порядок работы и воспроизводимость</h2><ol><li>Проверены контрольные суммы исходной модели, калибровки и релиза.</li><li>Открыта только таблица 2022 года; построена взвешенная precision-recall кривая.</li><li>Зафиксированы три порога и режим по умолчанию. Время фиксации: {policy["frozen_utc"]}.</li><li>Только после фиксации применены пороги к сохранённым вероятностям 2023–2024; повторного обучения и выбора порога по тесту не было.</li><li>Проверено совпадение решений на float32-картах с оценкой. Контрольные суммы всех 731 файлов вероятностей проверены; пропуски не заполнены.</li></ol>
<p>AP = 0,02045, ROC-AUC = 0,9237 и Brier прежние: изменение порога не улучшает ранжирование или вероятности. Карта остаётся ретроспективной; пригодность для текущих оперативных предупреждений не подтверждена.</p>
<p>SHA-256 политики: <code>{checksum(policy_path)}</code><br>SHA-256 исходного релиза: <code>{policy["model_release_sha256"]}</code></p>
<div class="links"><a href="policy.json">Зафиксированная политика JSON</a><a href="evaluation.json">Оценка JSON</a><a href="metrics.csv">Метрики CSV, включая каждый год</a><a href="cluster_intervals.csv">Доверительные интервалы CSV</a><a href="full_grid_alert_counts.csv">Сигналы по датам CSV</a><a href="calibration_curve_plot.csv">Кривая 2022 CSV</a><a href="../results/">Исходный отчёт по шести моделям</a></div></main></html>'''
    (destination / "index.html").write_text(page, encoding="utf-8")
    manifest["operating_policy"] = {
        "policy_path": "./alerts/policy.json", "policy_sha256": checksum(policy_path),
        "evaluation_path": "./alerts/evaluation.json", "evaluation_sha256": checksum(result_path),
        "report_path": "./alerts/", "default_profile": policy["default_profile"],
    }
    dump_json(manifest_path, manifest)
    outputs = {p.name: checksum(p) for p in destination.iterdir() if p.is_file() and p.name != "complete.json"}
    dump_json(destination / "complete.json", {"synthetic": False, "policy_sha256": checksum(policy_path),
              "model_release_sha256": policy["model_release_sha256"], "verified_probability_dates": len(manifest["available_days"]),
              "probabilities_changed": False, "outputs": outputs})
    print(json.dumps({"policy_sha256": checksum(policy_path), "full_grid_alert_counts": full_counts.to_dict(), "report": str(destination)}, ensure_ascii=True))


if __name__ == "__main__":
    main()
