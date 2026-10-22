"""Readable final metrics and publication-quality figures from actual evaluated files."""

from __future__ import annotations

import html
import json
import shutil
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from wildfire_kz.data import checksum, dump_json
from wildfire_kz.data.public_predictors import ROOT, permitted
from wildfire_kz.data.public_study import RUN

LABELS = {
    "logistic": "Logistic regression",
    "random_forest": "Random forest",
    "xgboost": "XGBoost",
    "catboost": "CatBoost",
    "weather_logistic": "Weather logistic",
    "seasonal": "Seasonal baseline",
}


def report() -> Path:
    permitted([2023, 2024], RUN / "release.json")
    result = json.loads((RUN / "evaluate/complete.json").read_text())
    if result["release_sha256"] != checksum(RUN / "release.json"):
        raise ValueError("Evaluation belongs to another frozen experiment")
    for name, digest in result["outputs"].items():
        if checksum(RUN / "evaluate" / name) != digest:
            raise ValueError(f"Evaluation output changed: {name}")
    selected = result["selected_model"]
    tuning = json.loads((RUN / "tuning.json").read_text())
    training = json.loads((RUN / "training_complete.json").read_text())
    trial_rows = []
    for name in ["random_forest", "xgboost", "catboost"]:
        trials = tuning[name]["trials"]
        trial_rows.append(
            {
                "model": LABELS[name],
                "attempts": len(trials),
                "completed": sum(t["state"] == "COMPLETE" for t in trials),
                "pruned": sum(t["state"] == "PRUNED" for t in trials),
                "failed": sum(t["state"] == "FAIL" for t in trials),
            }
        )
    search_table = pd.DataFrame(trial_rows).to_html(index=False, border=0)
    runtime = training["runtime"]
    peak = runtime.get("process_peak_resident_bytes")
    peak_text = f"{peak / 1024**3:.2f} ГиБ" if isinstance(peak, int) else "не измерен"
    fitting_html = f"""<section><h2>Фактически выполненное обучение</h2><p>{training["train_rows"]:,} обучающих строк; {training["positive_rows"]:,} положительных. Прошедшее время запуска, включая приостановки компьютера: {runtime["elapsed_seconds_this_invocation"] / 3600:.2f} ч. Пик резидентной памяти процесса: {peak_text}. Аппаратная и программная среда зафиксированы в реестре.</p><div class="table-wrap">{search_table}</div><p class="note">Попытки с ранней остановкой Optuna показаны отдельно. Победитель выбран до доступа к контрольным годам.</p></section>"""
    destination = RUN / "report"
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(
        ROOT / "docs/source-quality-verification.md", destination / "source-quality.txt"
    )
    weather_provenance = json.loads(
        (ROOT / "data/real/public_predictors/weather/2023.provenance.json").read_text()
    )
    api_source = next(
        (
            record
            for record in weather_provenance["sources"]
            if record.get("source") == "https://archive-api.open-meteo.com/v1/archive"
        ),
        None,
    )
    if api_source is not None:
        source_directory = ROOT / "data/real/public_predictors/source_adapters/openmeteo_soil_api"
        validation = json.loads((source_directory / "development_validation.json").read_text())
        if not validation["passed"] or validation != api_source["development_validation"]:
            raise ValueError("Source recovery comparison differs from the evaluated input")
        for filename in ["development_validation.json", "acquisition_plan.json"]:
            shutil.copyfile(
                source_directory / filename, destination / ("source-recovery-" + filename)
            )
        difference = max(row["maximum_absolute_difference"] for row in validation["days"])
        fitting_html += f'<section><h2>Восстановление отсутствующих файлов поставщика</h2><p>Четыре отсутствующих S3-файла почвенной влажности за 14 сентября — 6 декабря 2023 получены через официальный API того же поставщика ERA5. Запрошены реальные почасовые наблюдения в исходных узлах сетки. На 200 узлах в каждый из двух обучающих дней максимальное расхождение суточного признака составило {difference:.6g} м³/м³.</p><p>Модель, калибровка, пороги и правила признаков не менялись. Все ответы и контрольные суммы сохранены; загрузка соблюдала бесплатные лимиты. <a href="source-recovery-development_validation.json">Результаты проверки</a> · <a href="source-quality.txt">Полный аудит источников</a>.</p></section>'
    amendment_path = RUN / "budget_amendment.json"
    if amendment_path.is_file():
        amendment = json.loads(amendment_path.read_text())
        shutil.copyfile(amendment_path, destination / amendment_path.name)
        fitting_html += f'<p class="note">До финальной оценки пользователь сократил бюджет поиска с {amendment["old_budget"]} до {amendment["new_budget"]} попыток на ансамбль. Уже рассчитанные варианты Random Forest сохранены; поиску моделей выделено разное число попыток. Результат относится к проверенным кандидатам. <a href="budget_amendment.json">Запись изменения протокола</a>.</p>'
    quality_path = RUN / "development_quality.json"
    quality = json.loads(quality_path.read_text())
    if quality.get("synthetic") is not False or quality.get("test_accessed") is not False:
        raise ValueError("Development coverage must describe genuine pre-test tables")
    for record in quality["tables"]:
        if checksum(RUN / "features" / record["table"]) != record["sha256"]:
            raise ValueError(f"Audited development table changed: {record['table']}")
    coverage = pd.DataFrame(quality["tables"])[
        ["table", "rows", "positives", "ndvi_missing_fraction", "population_missing_fraction"]
    ]
    coverage.to_csv(destination / "development_data_quality.csv", index=False)
    coverage["ndvi_missing_fraction"] *= 100
    coverage["population_missing_fraction"] *= 100
    coverage = coverage.rename(
        columns={
            "table": "Выборка",
            "rows": "Строк",
            "positives": "Положительных",
            "ndvi_missing_fraction": "NDVI: пропуски, %",
            "population_missing_fraction": "Население: пропуски, %",
        }
    )
    quality_html = f'<section><h2>Состав данных и пропуски</h2><p>Реальные подготовленные выборки 2015–2022, до финального удаления промышленных ячеек. Доли пропусков здесь невзвешенные и относятся к строкам выборки. Обучающие и проверочные строки могут пересекаться между годами обучения и валидации; их нельзя суммировать как независимые наблюдения.</p><div class="table-wrap">{coverage.to_html(index=False, float_format=lambda value: f"{value:.2f}", border=0)}</div><p class="note">Обязательные метеоданные, покров и рельеф проверены до включения строки. Пропуски NDVI и населения заполняет медиана, рассчитанная только на обучающих данных каждого разбиения. <a href="development_data_quality.csv">Исходные доли и численность CSV</a>.</p></section>'
    cpu_path = RUN / "training_cpu.json"
    if cpu_path.is_file():
        cpu = json.loads(cpu_path.read_text())
        if cpu.get("training_complete") and cpu.get("process_exited"):
            if cpu["models_sha256"] != training["models_sha256"] or cpu[
                "observer_code_sha256"
            ] != checksum(ROOT / "scripts/monitor_public_training.py"):
                raise ValueError("CPU observation belongs to another model or observer")
            shutil.copyfile(cpu_path, destination / "training_cpu.json")
            fitting_html += f'<p>Процессорное время процесса, суммарно по всем его потокам: {cpu["total_cpu_seconds"] / 3600:.2f} CPU·ч. Это отдельное измерение Windows GetProcessTimes за весь срок жизни процесса; оно не равно календарному времени запуска. <a href="training_cpu.json">Исходная запись времени</a>.</p>'
            policy_path = RUN / "training_execution_policy.json"
            if policy_path.is_file():
                policy = json.loads(policy_path.read_text())
                if (
                    policy["pid"] == cpu["pid"]
                    and policy["created_utc"] == cpu["created_utc"]
                    and policy["helper_code_sha256"]
                    == checksum(ROOT / "scripts/govern_public_training.py")
                ):
                    shutil.copyfile(policy_path, destination / "training_execution_policy.json")
                    fitting_html += '<p class="note">На питании от сети для процесса сравнения использовался HighQoS Windows; исходный режим восстанавливался при работе от батареи. <a href="training_execution_policy.json">Журнал параметров выполнения</a>.</p>'
    from wildfire_kz.public_provenance import register_final_sources

    register_final_sources()
    shutil.copyfile(RUN / "acquisition_manifest.json", destination / "acquisition_manifest.json")
    shutil.copyfile(
        ROOT / "docs/explanation-compatibility.md", destination / "explanation-method.txt"
    )
    explanation_html = ""
    explanation_directory = RUN / "explain"
    if (explanation_directory / "complete.json").is_file():
        proof = json.loads((explanation_directory / "complete.json").read_text())
        if proof["release_sha256"] != checksum(RUN / "release.json"):
            raise ValueError("Explanation belongs to another frozen experiment")
        for name, digest in proof["outputs"].items():
            if checksum(explanation_directory / name) != digest:
                raise ValueError(f"Explanation output changed: {name}")
        shutil.copytree(explanation_directory, destination / "explain", dirs_exist_ok=True)
        explanation_html = f"""<section><h2>Объяснение предиктивных связей</h2><p>{html.escape(proof["method"])}; единицы вклада: {html.escape(proof["unit"])}. Калибровка находится вне объяснения; аддитивное восстановление исходного выхода модели проверено численно.</p><p class="note">Глобальная оценка использует {proof["global_uniform_sample_rows"]} случайно выбранных строк финальной вероятностной выборки с исходными весами. Дополнительные примеры с высоким прогнозом и ошибками не меняют глобальную важность. Эти связи не являются причинными объяснениями.</p><img src="explain/global.png" alt="Измеренная важность признаков выбранной модели"><p><a href="explain/global.csv">Важность CSV</a> · <a href="explain/grouped.csv">Группы признаков по покрову и областям</a> · <a href="explain/local.parquet">Локальные примеры Parquet</a></p></section>"""
    scores = pd.read_csv(RUN / "evaluate/metrics.csv", dtype={"period": str})
    full = scores[scores.period == "2023–2024"].set_index("model")
    intervals = pd.read_csv(RUN / "evaluate/cluster_intervals.csv")
    ap_ci = intervals[intervals.metric == "average_precision"].set_index("model")
    names = list(LABELS)
    values = full.loc[names, "average_precision"].to_numpy()
    lower, upper = ap_ci.loc[names, "lower"].to_numpy(), ap_ci.loc[names, "upper"].to_numpy()
    figure, axes = plt.subplots(1, 2, figsize=(12, 4.6), layout="constrained")
    colors = ["#2d6351" if name == selected else "#c1cbb7" for name in names]
    axes[0].barh([LABELS[n] for n in names], values, color=colors)
    for i, (lo, hi, p) in enumerate(zip(lower, upper, values, strict=True)):
        axes[0].plot([lo, hi], [i, i], color="#364f43", linewidth=1.3)
        axes[0].plot(p, i, "o", color="#364f43", markersize=3)
    axes[0].axvline(
        float(full.prevalence.iloc[0]), color="#a45d35", linestyle="--", label="Prevalence"
    )
    axes[0].set(xlabel="Design-weighted average precision", title="Final holdout: 2023–2024")
    axes[0].legend(frameon=False, fontsize=8)
    axes[1].barh([LABELS[n] for n in names], full.loc[names, "roc_auc"], color=colors)
    axes[1].set(
        xlabel="Design-weighted ROC-AUC", xlim=(0, 1), title="Selection fixed using 2019–2021"
    )
    for ax in axes:
        ax.spines[["top", "right"]].set_visible(False)
        ax.tick_params(axis="y", labelsize=9)
    figure.savefig(destination / "model_comparison.png", dpi=180)
    figure.savefig(destination / "model_comparison.pdf")
    plt.close(figure)
    rel = pd.read_csv(RUN / f"evaluate/calibration_intervals_{selected}.csv").dropna(
        subset=["predicted", "observed"]
    )
    rel.to_csv(destination / "calibration_bins.csv", index=False)
    figure, axis = plt.subplots(figsize=(5.6, 4.7), layout="constrained")
    upper_limit = float(max(rel.predicted.max(), rel.observed.max(), rel.ci_upper.max()) * 1.1)
    axis.plot(
        [0, upper_limit], [0, upper_limit], "--", color="#9aa58e", label="Perfect calibration"
    )
    axis.scatter(
        rel.predicted, rel.observed, s=30 + 160 * rel.weight / rel.weight.max(), color="#2d6351"
    )
    axis.vlines(rel.predicted, rel.ci_lower, rel.ci_upper, color="#2d6351", linewidth=1.2)
    axis.set(
        xlabel="Mean calibrated probability",
        ylabel="Weighted observed frequency",
        title=f"{LABELS[selected]} | final holdout",
        xlim=(0, upper_limit),
        ylim=(0, upper_limit),
    )
    axis.spines[["top", "right"]].set_visible(False)
    axis.legend(frameon=False, fontsize=8)
    figure.savefig(destination / "reliability.png", dpi=180)
    figure.savefig(destination / "reliability.pdf")
    plt.close(figure)
    table_html = (
        full[
            [
                "average_precision",
                "roc_auc",
                "brier",
                "bss",
                "precision",
                "recall",
                "f1",
                "prevalence",
            ]
        ]
        .rename(index=LABELS)
        .to_html(float_format=lambda v: f"{v:.6f}", border=0)
    )
    chosen = full.loc[selected]
    page = f"""<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Steppe · реальные результаты</title><style>body{{margin:0;background:#f6f7f1;color:#203d32;font:16px/1.65 Segoe UI,Arial,sans-serif}}main{{max-width:1120px;margin:auto;padding:55px 28px}}h1{{font-size:42px;line-height:1.15;letter-spacing:-1.5px}}small,.note{{color:#68766b}}.badge{{font-size:12px;letter-spacing:2px}}.tiles{{display:flex;gap:20px;margin:32px 0;flex-wrap:wrap}}.tile{{background:white;padding:22px;min-width:170px;flex:1;border-radius:10px}}.tile strong{{display:block;font-size:28px}}img{{max-width:100%;height:auto;margin:20px 0}}.table-wrap{{overflow:auto}}table{{border-collapse:collapse;font-size:12px;background:white;width:100%}}td,th{{padding:12px;border-bottom:1px solid #e4e9df;text-align:right}}th:first-child{{text-align:left}}a{{color:#2d6351}}code{{word-break:break-all;font-size:12px}}section{{margin:42px 0}}@media(max-width:600px){{h1{{font-size:32px}}main{{padding:30px 17px}}}}</style><main><div class="badge">STEPPE OBSERVATORY · REAL PUBLIC DATA</div><h1>Реальная модель.<br>Финальная проверка.</h1><p>Для карты выбрана <b>{html.escape(LABELS[selected])}</b> по средней взвешенной AP временной валидации 2019–2021. Калибровка выполнена на 2022 году. Контрольные данные 2023–2024 открыты после фиксации моделей и порогов.</p><div class="tiles"><div class="tile"><small>AP · тест 2023–2024</small><strong>{chosen.average_precision:.5f}</strong></div><div class="tile"><small>ROC-AUC</small><strong>{chosen.roc_auc:.4f}</strong></div><div class="tile"><small>Brier score</small><strong>{chosen.brier:.6f}</strong></div></div>{fitting_html}{quality_html}<section><h2>Сравнение замороженных моделей</h2><p class="note">Полосы на AP: 95% интервалы, 1000 одинаковых блочных повторов 100 км × 30 дней. Зелёным отмечена модель, выбранная до доступа к тесту.</p><img src="model_comparison.png" alt="Реальные метрики шести моделей"><div class="table-wrap">{table_html}</div></section><section><h2>Калибровка вероятностей</h2><p class="note">Границы интервалов зафиксированы на 2022 году. Размер точки отражает вес наблюдений.</p><img src="reliability.png" alt="Калибровка выбранной модели"></section>{explanation_html}<section><h2>Что измерено</h2><p>Цель — первое спутниковое обнаружение связанного события, а не подтверждённое время возгорания. Отсутствие детекций не доказывает отсутствие огня. Метрики имеют веса отбора отрицательных примеров и относятся к допустимым ячейкам с обязательными признаками.</p><p>Всего в финальной выборке: {result["rows"]:,} строк, {result["positive_rows"]:,} положительных. Оценка взвешенного числа допустимых ячейко-дней: {result["weighted_cell_days"]:,.0f}.</p><p>Архивы переобработаны после дат наблюдений. ERA5, NOAA NDVI, SRTM 90 м и исторические антропогенные данные — документированные открытые аналоги. Результат представляет ретроспективный эксперимент; оперативная пригодность не подтверждена.</p></section><section><h2>Проверяемые артефакты</h2><p><a href="../evaluate/metrics.csv">Все метрики CSV</a> · <a href="../evaluate/cluster_intervals.csv">Блочные интервалы CSV</a> · <a href="../comparison.csv">Временная валидация</a> · <a href="../source_registry.json">Зафиксированные источники</a> · <a href="acquisition_manifest.json">Полный реестр загрузки и версий</a> · <a href="../frozen.json">Параметры фиксации</a> · <a href="https://steppe-kazakhstan-fire-map.peppy-horse-5926.chatgpt.site/">Интерактивная карта</a></p><p class="note">SHA-256 фиксации: <code>{result["release_sha256"]}</code></p></section></main></html>"""
    (destination / "index.html").write_text(page, encoding="utf-8")
    dump_json(
        destination / "complete.json",
        {
            "synthetic": False,
            "release_sha256": result["release_sha256"],
            "outputs": {
                p.relative_to(destination).as_posix(): checksum(p)
                for p in destination.rglob("*")
                if p.is_file() and p != destination / "complete.json"
            },
        },
    )
    return destination / "index.html"
