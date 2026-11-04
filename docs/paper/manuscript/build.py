"""Assemble the full manuscript: numeric citations, joined Results and Discussion, floats."""

import re
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = Path(r"C:\Users\nured\Downloads\Telegram Desktop\sn-article (19).tex")
BIB = Path(r"C:\Users\nured\Downloads\Telegram Desktop\references (9).bib")
FIGS = HERE.parents[0] / "results/figures"

tex = SRC.read_text(encoding="utf-8")

# ---------- 1. author-name citations -> numeric citations, as in the Introduction ----------
SUBJECTS = [
    ("Jadouli and El Amrani integrate", "jadouli2024morocco"),
    ("Ahajjam et al. link", "ahajjam2025alaska"),
    ("Ejaz and Choudhury place", "ejaz2025pipeline"),
    ("Galv\\'an Lara et al. similarly examine", "galvanlara2026systematic"),
    ("Biswas et al. directly compare", "biswas2025geoai"),
    ("Gupta and Kim apply", "gupta2024geospatial"),
    ("Ouazri et al. combine", "ouazri2026catboost"),
    ("Choi and Chae address", "choi2026burnedarea"),
    ("Benhamza et al. connect", "benhamza2025hybrid"),
    ("Jadouli and El Amrani embed", "jadouli2026physics"),
    ("Saleem et al. combine", "saleem2025neuralxgb"),
    ("Camacho et al. investigate", "camacho2026resampling"),
    ("Apostolakis et al. connect", "apostolakis2025interpretation"),
    ("Babu et al. integrate", "babu2025sfri"),
    ("Chepashev et al. develop", "chepashev2025maxent"),
    ("Nurtas et al. review", "nurtas2026kazakhstan"),
    ("Wilk-Jakubowski et al. synthesize", "wilkjakubowski2026hazard"),
    ("Dossi et al. identify", "dossi2026infrastructure"),
    ("Berchtold et al. introduce", "berchtold2025tipping"),
]
for phrase, key in SUBJECTS:
    start = tex.index(phrase)
    verb = phrase.split(" ")[-1] if " similarly " not in phrase and " directly " not in phrase else " ".join(phrase.split(" ")[-2:])
    tex = tex[:start] + f"\\cite{{{key}}} {verb}" + tex[start + len(phrase):]
    end = tex.index(f" \\cite{{{key}}}", start + 10)
    tex = tex[:end] + tex[end + len(f" \\cite{{{key}}}"):]

PAIRS = [
    (
        "Mambile et al. identify CNNs and LSTMs as frequently used architectures and emphasize meteorological and satellite-derived predictors, while Xu et al. distinguish time-series, segmentation, and spatiotemporal formulations \\cite{mambile2024systematic,xu2025deep}.",
        "\\cite{mambile2024systematic} identify CNNs and LSTMs as frequently used architectures and emphasize meteorological and satellite-derived predictors, while \\cite{xu2025deep} distinguish time-series, segmentation, and spatiotemporal formulations.",
    ),
    (
        "Iban and Aksu examine contributing factors through SHAP-based susceptibility mapping, while Bouzeraa et al. integrate GIS and ML in a regional predictive framework \\cite{iban2024shap,bouzeraa2025wsm}.",
        "\\cite{iban2024shap} examine contributing factors through SHAP-based susceptibility mapping, while \\cite{bouzeraa2025wsm} integrate GIS and ML in a regional predictive framework.",
    ),
    (
        "following the event-oriented principle used by Ahajjam et al. \\cite{ahajjam2025alaska}.",
        "following the event-oriented principle used in \\cite{ahajjam2025alaska}.",
    ),
    (
        "informed by Camacho et al.; synthetic samples will not be allowed in evaluation sets \\cite{camacho2026resampling}.",
        "informed by \\cite{camacho2026resampling}; synthetic samples will not be allowed in evaluation sets.",
    ),
    (
        "Following the probability-based mapping motivation of Apostolakis et al., class boundaries will be selected on calibration data and fixed before testing, with continuous probabilities and observed class frequencies retained \\cite{apostolakis2025interpretation}.",
        "Following the probability-based mapping motivation of \\cite{apostolakis2025interpretation}, class boundaries will be selected on calibration data and fixed before testing, with continuous probabilities and observed class frequencies retained.",
    ),
    (
        "Section~4 will report the experimental results. Section~5 will discuss their meaning, practical value, and limitations. Finally, Section~6 will present the conclusions and directions for future work.",
        "Section~\\ref{sec:results} presents the experimental results and discusses them in relation to the research questions, previous studies, and limitations. Finally, Section~\\ref{sec:conclusion} summarizes the findings and directions for future work.",
    ),
]
for old, new in PAIRS:
    assert old in tex, old[:60]
    tex = tex.replace(old, new)
left = re.findall(r"[A-Z][\w\\'-]+ (?:et al\.|and [A-Z][\w ]+? (?=[a-z]))", tex)
assert not re.search(r"et al\.", tex), "an et al. citation is left"

# ---------- 2. Results and Discussion, Conclusion with uniform floats ----------
body = (HERE / "results_section.tex").read_text(encoding="utf-8")


def table(label: str, caption: str, spec: str, header: str, rows: list[str], note: str = "") -> str:
    """Every table: caption above, footnotesize, full text width, booktabs rules."""
    lines = [
        "\\begin{table}[htbp]",
        f"\\caption{{{caption}}}\\label{{{label}}}",
        "\\centering\\footnotesize",
        "\\setlength{\\tabcolsep}{3pt}",
        f"\\begin{{tabularx}}{{\\textwidth}}{{@{{}}{spec}@{{}}}}",
        "\\toprule",
        header + " \\\\",
        "\\midrule",
        *[r + " \\\\" for r in rows],
        "\\bottomrule",
        "\\end{tabularx}",
    ]
    if note:
        lines.append(f"\\par\\smallskip\\raggedright\\scriptsize {note}")
    lines.append("\\end{table}")
    return "\n".join(lines) + "\n"


def figure(label: str, path: str, caption: str) -> str:
    return (
        "\\begin{figure}[htbp]\n\\centering\n"
        f"\\includegraphics[width=0.85\\textwidth]{{{path}}}\n"
        f"\\caption{{{caption}}}\\label{{{label}}}\n\\end{{figure}}\n"
    )


C = ">{\\centering\\arraybackslash}X"
floats = {
    "so every model was tested on rarer events than it was trained on.\n": table(
        "tab:dataset",
        "New-event starts and prevalence by year and role",
        "l l" + f" {C}" * 3,
        "Year & Role & New-event starts & Eligible cell-days ($\\times10^{6}$) & Prevalence ($\\times10^{-4}$)",
        [
            "2015 & Development & 15,326 & 40.1 & 3.82",
            "2016 & Development & 13,050 & 40.2 & 3.24",
            "2017 & Development & 21,819 & 40.1 & 5.44",
            "2018 & Development & 14,844 & 40.1 & 3.70",
            "2019 & Development & 18,773 & 40.1 & 4.68",
            "2020 & Development & 16,679 & 40.2 & 4.15",
            "2021 & Development & 12,951 & 40.1 & 3.23",
            "2022 & Calibration & 10,134 & 40.1 & 2.52",
            "2023 & Test & 9,563 & 39.8 & 2.40",
            "2024 & Test & 6,187 & 40.3 & 1.54",
        ],
        "All positives are retained; eligible cell-days are inverse-inclusion weighted totals of the sampled negatives and positives.",
    ),
    "but it weakens the meteorological signal.\n": table(
        "tab:implementation",
        "Planned design (Section~\\ref{sec:methods}) and its implementation",
        "l X X",
        "Component & Planned & Implemented",
        [
            "Weather & ERA5-Land (9\\,km), observations before $t$ & ERA5 (0.25$^{\\circ}$) from the Open-Meteo archive \\cite{hersbach2020era5,openmeteoOpenData}; day $t-7$ and 7/14-day windows ending $t-7$",
            "Vegetation & MOD13A2 NDVI/EVI, 16-day & NOAA CDR NDVI (0.05$^{\\circ}$), weekly, used $\\geq$12 days after observation \\cite{noaaCdrNdvi}",
            "Human pressure & Dated WorldPop, OSM roads & WorldPop 2010 \\cite{worldpop2010}; distance to Natural Earth settlements \\cite{naturalEarthPlaces}; no roads",
            "Tuning & 50 Optuna trials per ensemble & 5 trials (budget amended before test access)",
            "Spatial blocks & 50, 100, 150\\,km; re-tuned per fold & 100\\,km with 25\\,km buffer; hyperparameters fixed",
            "Ablation & Human, lagged weather, vegetation & Seven predictor groups and a weather-only model, refitted post hoc",
        ],
    ),
    "compared with 14.3\\% for the seasonal reference and 8.4\\% for the weather-only model.\n": table(
        "tab:performance",
        "Test performance 2023--2024 (prevalence $1.96\\times10^{-4}$); thresholds fixed on 2022",
        "l" + f" {C}" * 9,
        "Model & AP & AP/prev. & ROC-AUC & BSS & Precision & Recall & $F_1$ & Top-5\\% capture & XGBoost $-$ model AP (95\\% CI)",
        [
            "XGBoost & 0.0204 & 104 & 0.924 & 0.0002 & 0.098 & 0.052 & 0.068 & 0.556 & --",
            "CatBoost & 0.0175 & 89 & 0.908 & 0.0085 & 0.046 & 0.072 & 0.056 & 0.502 & $-$0.0017, 0.0124",
            "Random Forest & 0.0070 & 36 & 0.879 & 0.0032 & 0.024 & 0.052 & 0.033 & 0.492 & 0.0095, 0.0231",
            "Logistic regression & 0.0010 & 5 & 0.793 & 0.0001 & 0.002 & 0.048 & 0.004 & 0.256 & 0.0156, 0.0301",
            "Weather-only logistic & 0.0004 & 2 & 0.662 & 0.0002 & 0.000 & 0.055 & 0.001 & 0.084 & 0.0162, 0.0307",
            "Seasonal frequency & 0.0006 & 3 & 0.731 & 0.0000 & 0.002 & 0.055 & 0.003 & 0.143 & 0.0161, 0.0306",
        ],
        "BSS is relative to the seasonal reference; intervals from 1,000 paired space--time block-bootstrap resamples.",
    )
    + figure(
        "fig:pr",
        "figures/F1_precision_recall.pdf",
        "Precision--recall curves on the test years 2023--2024; the dotted line marks the no-skill precision (prevalence).",
    ),
    "close to the weather-only logistic reference. Rolling validation agreed: terrain was again the largest loss (mean AP 0.0096 against 0.0159).\n": table(
        "tab:ablation",
        "Predictor-group ablation of XGBoost (frozen hyperparameters, refitted)",
        "l" + f" {C}" * 4,
        "Variant & Inputs & Test AP & AP lost (95\\% CI) & Rolling-validation mean AP",
        [
            "Full model & 26 & 0.0234 & -- & 0.0159",
            "Without daily weather ($t-7$) & 20 & 0.0303 & $-$0.0068 ($-$0.0144, 0.0011) & 0.0166",
            "Without 7/14-day weather & 22 & 0.0241 & $-$0.0007 ($-$0.0082, 0.0029) & 0.0162",
            "Without vegetation & 23 & 0.0211 & 0.0023 ($-$0.0028, 0.0062) & 0.0156",
            "Without land cover & 21 & 0.0140 & 0.0094 (0.0021, 0.0134) & 0.0150",
            "Without terrain & 22 & 0.0081 & 0.0154 (0.0118, 0.0233) & 0.0096",
            "Without human pressure & 24 & 0.0155 & 0.0079 (0.0002, 0.0123) & 0.0145",
            "Without season & 24 & 0.0190 & 0.0045 (0.0006, 0.0076) & 0.0144",
            "Weather only & 10 & 0.0006 & 0.0228 (0.0184, 0.0321) & 0.0018",
        ],
        "Post hoc analysis after the final test; it explains the result and selects nothing.",
    )
    + figure(
        "fig:ablation",
        "figures/F14_ablation.pdf",
        "Average precision lost when each predictor group is removed (test 2023--2024, paired 95\\% intervals); red bars exclude zero.",
    ),
    "but Brier skill was negative in four of five folds.\n": table(
        "tab:transfer",
        "Temporal and geographic transfer of XGBoost",
        "l" + f" {C}" * 4,
        "Evaluation & AP & AP/prevalence & ROC-AUC & BSS",
        [
            "Rolling validation 2019--2021 (mean) & 0.0191 & -- & -- & --",
            "Temporal test 2023 & 0.0192 & 80 & 0.924 & $-$0.006",
            "Temporal test 2024 & 0.0277 & 181 & 0.923 & 0.010",
            "Temporal test 2023--2024 & 0.0204 & 104 & 0.924 & 0.000",
            "Spatial fold 1 & 0.0005 & 6 & 0.808 & $-$0.048",
            "Spatial fold 2 & 0.0083 & 37 & 0.882 & 0.001",
            "Spatial fold 3 & 0.0043 & 12 & 0.890 & $-$0.022",
            "Spatial fold 4 & 0.0030 & 10 & 0.859 & $-$0.004",
            "Spatial fold 5 & 0.0031 & 12 & 0.890 & $-$0.010",
            "Spatial folds (mean) & 0.0039 & 15 & 0.866 & $-$0.017",
        ],
        "Spatial folds: 100\\,km blocks with a 25\\,km buffer, development period, hyperparameters fixed.",
    ),
    "Accuracy (0.9997) is uninformative at this prevalence.\n": table(
        "tab:classes",
        "XGBoost map classes fixed on 2022: predicted and observed frequency, 2023--2024",
        "l" + f" {C}" * 5,
        "Class & Probability range & Cell-days ($\\times10^{6}$) & Mean predicted & Observed & Predicted/observed",
        [
            "1 & 0 -- $4.8\\times10^{-5}$ & 39.8 & $1.2\\times10^{-5}$ & $9.0\\times10^{-6}$ & 1.33",
            "2 & $4.8\\times10^{-5}$ -- $2.3\\times10^{-4}$ & 25.3 & $1.2\\times10^{-4}$ & $6.7\\times10^{-5}$ & 1.82",
            "3 & $2.3\\times10^{-4}$ -- $7.9\\times10^{-4}$ & 11.0 & $3.9\\times10^{-4}$ & $3.0\\times10^{-4}$ & 1.28",
            "4 & $7.9\\times10^{-4}$ -- 1 & 4.0 & $3.4\\times10^{-3}$ & $2.6\\times10^{-3}$ & 1.32",
        ],
    )
    + figure(
        "fig:reliability",
        "figures/F3_reliability.pdf",
        "Reliability diagrams on the test years; marker size grows with the number of cell-days per bin.",
    ),
    "the dominant factors change between land-cover groups and regions.\n": table(
        "tab:landcover",
        "XGBoost performance and leading SHAP groups by dominant land cover, 2023--2024",
        "l" + f" {C}" * 4 + " X",
        "Land cover & Test starts & AP & AP/prev. & BSS & Leading predictor groups (mean $|$SHAP$|$)",
        [
            "Grassland & 12,805 & 0.0413 & 225 & 0.016 & human 0.65; season 0.61; antecedent weather 0.57",
            "Cropland & 1,947 & 0.0134 & 21 & 0.005 & antecedent weather 1.15; land cover 0.81; season 0.44",
            "Other & 947 & 0.0359 & 263 & $-$0.228 & land cover 1.20; terrain 0.77; human 0.73",
            "Forest & 5 & 0.0014 & 40 & $-$0.005 & land cover 0.94; antecedent weather 0.81; human 0.73",
            "Shrubland & 0 & -- & -- & -- & land cover 1.75; weather 0.74; season 0.47",
        ],
        "SHAP values are in uncalibrated log-odds and describe predictive associations, not causes.",
    )
    + figure(
        "fig:shap",
        "figures/F5_shap_global.pdf",
        "Global TreeSHAP importance of the fifteen strongest predictors of XGBoost.",
    ),
    "the distinction between occurrence probability and risk \\cite{dossi2026infrastructure,berchtold2025tipping}.\n": figure(
        "fig:case",
        "figures/F13_case_june_2023.pdf",
        "Next-day forecasts for 7--9 June 2023 as daily percentile classes, with the new event starts of each day.",
    ),
}
for anchor, block in floats.items():
    assert body.count(anchor) == 1, anchor[:60]
    body = body.replace(anchor, anchor + "\n" + block)

tex = tex.replace("\n\n\\bibliography{references}", "\n\n" + body + "\n\\bibliography{references}")
(HERE / "sn-article.tex").write_text(tex, encoding="utf-8")

# ---------- 3. bibliography: the datasets actually used ----------
extra = r"""

% -------------------- Data sources used in the implemented experiment --------------------
@article{hersbach2020era5,
  author  = {Hersbach, Hans and Bell, Bill and Berrisford, Paul and others},
  title   = {The {ERA5} Global Reanalysis},
  journal = {Quarterly Journal of the Royal Meteorological Society},
  year    = {2020},
  volume  = {146},
  number  = {730},
  pages   = {1999--2049},
  doi     = {10.1002/qj.3803}
}
@misc{openmeteoOpenData,
  author = {{Open-Meteo}},
  title  = {Open-Meteo Open-Data Archive of Weather Model and Reanalysis Data},
  url    = {https://github.com/open-meteo/open-data},
  note   = {Accessed October 2026}
}
@misc{noaaCdrNdvi,
  author = {{NOAA National Centers for Environmental Information}},
  title  = {Climate Data Record of Normalized Difference Vegetation Index},
  url    = {https://www.ncei.noaa.gov/products/climate-data-records/normalized-difference-vegetation-index},
  note   = {Accessed October 2026}
}
@misc{worldpop2010,
  author = {{WorldPop}},
  title  = {Global High Resolution Population Denominators, 2010, 1\,km, {Kazakhstan}},
  url    = {https://data.worldpop.org/GIS/Population/Global_2000_2020_1km/2010/KAZ/},
  note   = {Accessed October 2026}
}
@misc{naturalEarthPlaces,
  author = {{Natural Earth}},
  title  = {Populated Places, 1:10m Cultural Vectors},
  url    = {https://www.naturalearthdata.com/downloads/10m-cultural-vectors/},
  note   = {Accessed October 2026}
}
"""
(HERE / "references.bib").write_text(BIB.read_text(encoding="utf-8").rstrip() + "\n" + extra, encoding="utf-8")

out = HERE / "figures"
out.mkdir(exist_ok=True)
for name in ["F1_precision_recall", "F3_reliability", "F5_shap_global", "F13_case_june_2023", "F14_ablation"]:
    shutil.copyfile(FIGS / f"{name}.pdf", out / f"{name}.pdf")
print("ok")
