"""Publication figures and a self-contained, offline research dashboard."""

from __future__ import annotations

import base64
import html
import json
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from wildfire_kz.config import Config


def _embed(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def build_report(root: Path, out: Path, cfg: Config) -> None:
    """Render only measured values, with conspicuous synthetic provenance where applicable."""
    scores = pd.read_csv(root / "evaluate" / "metrics.csv")
    overall = scores[scores.stratum == "overall"].copy()
    selection = json.loads((root / "train" / "selection.json").read_text())
    selected = selection["selected_model"]
    current = overall[overall.model == selected].iloc[0]
    reliability = pd.read_csv(root / "evaluate" / "reliability.csv")
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.titleweight": "bold",
            "figure.facecolor": "#fbfaf6",
            "axes.facecolor": "#fbfaf6",
            "axes.labelcolor": "#364340",
            "text.color": "#16382f",
        }
    )
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), constrained_layout=True)
    main = overall[~overall.model.str.startswith("without_")].sort_values("average_precision")
    axes[0].barh(main.model.str.replace("_", " "), main.average_precision, color="#176859")
    axes[0].axvline(
        float(current.prevalence), color="#d87a36", ls="--", label="No-skill prevalence"
    )
    axes[0].set(xlabel="Weighted average precision", title="Discrimination on the final holdout")
    axes[0].legend(frameon=False, fontsize=8)
    rel = reliability[(reliability.model == selected) & (reliability["count"] > 0)]
    axes[1].plot([0, 1], [0, 1], ls="--", color="#a4aaa3")
    axes[1].errorbar(
        rel.predicted,
        rel.observed,
        yerr=[
            np.maximum(0, rel.observed - rel.ci_lower),
            np.maximum(0, rel.ci_upper - rel.observed),
        ],
        fmt="o-",
        color="#176859",
        capsize=3,
    )
    axes[1].set(
        xlabel="Mean calibrated probability",
        ylabel="Observed frequency",
        title="Reliability with space-time uncertainty",
        xlim=(0, 1),
        ylim=(0, 1),
    )
    for row in rel.itertuples():
        axes[1].annotate(
            f"n={row.count}",
            (row.predicted, row.observed),
            xytext=(4, 8),
            textcoords="offset points",
            fontsize=7,
        )
    fig.suptitle(
        "SYNTHETIC PIPELINE VERIFICATION" if cfg.data.synthetic else "Kazakhstan | final holdout",
        fontsize=10,
    )
    fig.savefig(out / "evaluation.png", dpi=180)
    fig.savefig(out / "evaluation.pdf")
    plt.close(fig)
    overall.to_csv(out / "model_summary.csv", index=False)
    negative = overall[overall.bss < 0][["model", "bss"]]
    intervals = pd.read_csv(root / "evaluate" / "paired_intervals.csv")
    unstable = intervals[(intervals.lower <= 0) & (intervals.upper >= 0)]
    (out / "findings.txt").write_text(
        f"Provenance: {'SYNTHETIC ONLY' if cfg.data.synthetic else 'registered observations'}\n"
        + "Selection fixed from development CV: "
        + selected
        + "\n"
        + "Negative skill vs seasonal reference (BSS < 0):\n"
        + negative.to_string(index=False)
        + "\nPaired differences whose confidence interval spans zero:\n"
        + unstable.to_string(index=False)
        + "\nNo superiority is inferred from intervals spanning zero. Predictive associations are not causal.\n",
        encoding="utf-8",
    )
    grid = gpd.read_parquet(root / "grid" / "grid.parquet")
    xmin, ymin, xmax, ymax = grid.total_bounds
    width, height = xmax - xmin, ymax - ymin
    cells = []
    for row in grid.itertuples():
        geom = row.geometry
        parts = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
        paths = []
        for part in parts:
            coords = list(part.exterior.coords)
            if cfg.data.synthetic:
                patch = int(row.x // 300000)
                # Explicitly schematic fixtures: equal display size for the five patches.
                projected = [
                    (65 + patch * 180 + 110 * (x - patch * 300000) / 10000, 170 - 110 * y / 10000)
                    for x, y in coords
                ]
            else:
                scale = min(920 / width, 200 / height)
                projected = [(40 + (x - xmin) * scale, 220 - (y - ymin) * scale) for x, y in coords]
            paths.append("M" + " L".join(f"{x:.2f},{y:.2f}" for x, y in projected) + "Z")
        cells.append({"id": row.cell_id, "path": " ".join(paths)})
    predictions = pd.read_parquet(root / "evaluate" / "predictions.parquet")
    dates = sorted(predictions.day.dt.strftime("%Y-%m-%d").unique())
    by_date = {
        day: group.set_index("cell_id")[[selected, "label"]]
        .rename(columns={selected: "p", "label": "y"})
        .to_dict("index")
        for day, group in predictions.groupby(predictions.day.dt.strftime("%Y-%m-%d"))
    }
    payload = json.dumps(
        {"cells": cells, "days": dates, "predictions": by_date}, separators=(",", ":")
    ).replace("</", "<\\/")
    table = "".join(
        f"<tr><td>{html.escape(str(r.model).replace('_', ' '))}</td><td>{r.average_precision:.4f}</td><td>{r.brier:.4f}</td><td>{r.bss:+.3f}</td><td>{r.f1:.4f}</td></tr>"
        for r in overall.itertuples()
    )
    stages = []
    for name in [
        "ingest",
        "grid",
        "events",
        "risk_set",
        "sampling",
        "features",
        "splits",
        "train",
        "calibrate",
        "ablate",
        "evaluate",
        "explain",
        "map",
    ]:
        record = json.loads((root / name / "_stage.json").read_text())
        stages.append(
            f"<span title='{record['seconds']:.2f} measured seconds'>✓ {name.replace('_', ' ')}</span>"
        )
    badge = (
        "SYNTHETIC DEMONSTRATION" if cfg.data.synthetic else "REGISTERED OBSERVATIONAL EXPERIMENT"
    )
    disclaimer = (
        "Artificial cells and generated observations. These results verify the software; they provide no evidence of predictive skill in Kazakhstan."
        if cfg.data.synthetic
        else "Retrospective occurrence-hazard experiment. Source availability and satellite detection limits govern interpretation."
    )
    document = TEMPLATE.replace("@@BADGE@@", badge).replace("@@DISCLAIMER@@", disclaimer)
    replacements = {
        "MODEL": selected.replace("_", " "),
        "AP": f"{current.average_precision:.4f}",
        "PREVALENCE": f"{current.prevalence:.4f}",
        "BRIER": f"{current.brier:.4f}",
        "BSS": f"{current.bss:+.3f}",
        "TABLE": table,
        "STAGES": "".join(stages),
        "PAYLOAD": payload,
        "FIGURE": _embed(out / "evaluation.png"),
        "SHAP": _embed(root / "explain" / "global.png"),
        "RESAMPLES": str(cfg.evaluation.bootstrap_resamples),
        "TRIALS": str(cfg.models.trials),
        "SEED": str(cfg.seed),
        "ROWS": f"{len(predictions):,}",
        "NEGATIVE": html.escape(negative.to_string(index=False)),
        "MAPNOTE": "Artificial patches shown schematically; distances are not to scale."
        if cfg.data.synthetic
        else "Equal-area national cells. Ineligible cells are nodata.",
        "DRAWNOTE": "Map shows the weighted evaluation sample; complete rasters are in the map folder.",
    }
    for key, value in replacements.items():
        document = document.replace(f"@@{key}@@", value)
    (out / "index.html").write_text(document, encoding="utf-8")


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Steppe Observatory | Wildfire KZ</title><style>
:root{--ink:#16382f;--muted:#64766c;--paper:#f7f6f0;--line:#dce1d6;--orange:#cf6834;--green:#b9d5b0}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.6 'Segoe UI',Arial,sans-serif}header{padding:22px 5vw;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between}.brand{font-size:17px;font-weight:700;letter-spacing:-.5px}.brand b{background:var(--ink);color:var(--paper);border-radius:50%;padding:8px 12px;margin-right:10px}nav a{color:var(--muted);text-decoration:none;margin-left:26px;font-size:12px}main{max-width:1440px;padding:0 5vw 60px;margin:auto}.hero{padding:50px 0 32px;display:grid;grid-template-columns:1.5fr 1fr;gap:60px}.eyebrow{letter-spacing:2px;font-size:10px;font-weight:700;text-transform:uppercase;color:var(--muted)}h1{font-family:Georgia,serif;font-size:clamp(38px,4.6vw,68px);line-height:1.05;letter-spacing:-2px;font-weight:400;margin:15px 0 22px}h1 em{color:var(--orange);font-weight:400}h2{font:32px/1.2 Georgia,serif;letter-spacing:-.6px;margin:10px 0}h3{font-size:15px;margin:0 0 12px}p{color:var(--muted);max-width:680px}.heroaside{border-left:1px solid var(--line);padding:24px 0 0 36px;align-self:center}.stamp{display:inline-block;color:#8b4a1b;background:#f3e3ce;padding:5px 10px;font-size:10px;letter-spacing:1px;font-weight:700;border-radius:3px}.heroaside p{font-size:13px}.equation{font:19px Georgia,serif;padding:16px 0}.rule{display:flex;gap:20px;font-size:11px;color:var(--muted);border-top:1px solid var(--line);padding:14px 0}.metrics{display:grid;grid-template-columns:repeat(4,1fr);border:1px solid var(--line);border-radius:8px;overflow:hidden;margin:15px 0 35px;background:#fffdf8}.metric{padding:22px 26px;border-right:1px solid var(--line)}.metric:last-child{border:0}.metric strong{font:38px Georgia,serif;display:block;margin:6px 0}.metric small{font-size:11px;color:var(--muted)}.metric label{font-size:11px;text-transform:uppercase;letter-spacing:1px}.sectionhead{display:flex;justify-content:space-between;align-items:end;margin:30px 0 18px}.pill{background:#e6eddf;padding:5px 12px;border-radius:30px;font-size:11px}.mapcard{background:#153c32;color:#e8eedf;border-radius:9px;overflow:hidden;position:relative}.maptop{display:flex;justify-content:space-between;padding:25px 28px 0;align-items:center}.maptop p{color:#adc3b5;font-size:12px;margin:2px 0}.maptop input{accent-color:#e6aa67;width:180px}.mapcard svg{width:100%;height:290px;display:block;background:radial-gradient(ellipse at center,#285546 0,transparent 70%);}.mapcard path{stroke:#7f9e81;stroke-width:.45;cursor:pointer;transition:fill .2s}.mapfooter{padding:15px 28px;border-top:1px solid #3a5a4c;display:flex;justify-content:space-between;gap:25px;font-size:11px;color:#bdcdbd}.gradient{display:inline-block;width:100px;height:7px;background:linear-gradient(90deg,#a1c497,#e6c273,#d46c3c);margin:0 10px;border-radius:2px}.twocol{display:grid;grid-template-columns:1fr 1fr;gap:25px;margin:22px 0}.card{background:#fffdf8;border:1px solid var(--line);border-radius:8px;padding:24px}.card p{font-size:12px}.card img{width:100%;height:auto}.widefigure{width:100%;border:1px solid var(--line);border-radius:8px;background:#fbfaf6}table{border-collapse:collapse;width:100%;font-size:12px}td,th{text-align:right;border-bottom:1px solid var(--line);padding:11px 7px}td:first-child,th:first-child{text-align:left}th{color:var(--muted);font-size:10px;text-transform:uppercase;font-weight:600}tr:hover{background:#edf0e7}.timeline{display:grid;grid-template-columns:2.8fr .4fr .8fr;gap:4px;margin:24px 0}.timeline div{padding:18px;background:#e6eddf;border-top:3px solid #437653;font-size:12px}.timeline div:nth-child(2){background:#f5e5cf;border-color:#cf8d49}.timeline div:last-child{background:#e4e8ed;border-color:#5a7087}.timeline strong{display:block;font-size:17px}.stages{display:flex;flex-wrap:wrap;gap:8px}.stages span{background:#e9eee1;padding:6px 10px;font-size:11px;border-radius:4px}pre{white-space:pre-wrap;font-size:12px;background:#f4eee3;padding:15px;overflow:auto}footer{font-size:11px;color:var(--muted);padding-top:25px;border-top:1px solid var(--line);margin-top:30px}a{color:#286b55}details{font-size:12px}summary{cursor:pointer;font-weight:600}button{border:1px solid #6d8b75;background:transparent;color:#e8eedf;padding:5px 10px;border-radius:4px;cursor:pointer}#cellinfo{font-variant-numeric:tabular-nums} @media(max-width:850px){.hero,.twocol{grid-template-columns:1fr;gap:15px}.heroaside{border-left:0;border-top:1px solid var(--line);padding:20px 0}.metrics{grid-template-columns:1fr 1fr}.metric{border-bottom:1px solid var(--line)}nav{display:none}.maptop{gap:10px;flex-wrap:wrap}.mapfooter{flex-direction:column;gap:8px}.hero{padding-top:30px}}
</style></head><body><header><div class="brand"><b>∿</b> STEPPE / OBSERVATORY</div><nav><a href="#atlas">Occurrence atlas</a><a href="#evidence">Model evidence</a><a href="#protocol">Research protocol</a></nav><span class="eyebrow">KAZAKHSTAN · 2015–2024</span></header>
<main><section class="hero"><div><div class="eyebrow">Explainable multisource machine learning</div><h1>Reading the conditions<br>before <em>the first fire.</em></h1><p>A reproducible framework for next-day vegetation-fire occurrence, connecting weather, vegetation, terrain and human activity on an equal-area grid.</p><div class="rule"><span>5 km cells</span><span>UTC daily forecasts</span><span>Strict as-of features</span><span>Seed @@SEED@@</span></div></div><aside class="heroaside"><span class="stamp">@@BADGE@@</span><p>@@DISCLAIMER@@</p><div class="equation">P(new event in cell i on day t | information before t)</div><p>Occurrence hazard. Damage, exposure and vulnerability are outside this model.</p></aside></section>
<div class="eyebrow">Measured final-holdout results · selected from development CV: @@MODEL@@</div><section class="metrics"><div class="metric"><label>Average precision</label><strong>@@AP@@</strong><small>Recall-increment AP</small></div><div class="metric"><label>No-skill reference</label><strong>@@PREVALENCE@@</strong><small>Weighted event prevalence</small></div><div class="metric"><label>Brier score</label><strong>@@BRIER@@</strong><small>Weighted probability error</small></div><div class="metric"><label>Brier skill score</label><strong>@@BSS@@</strong><small>Against seasonal cover × month</small></div></section>
<section id="atlas"><div class="sectionhead"><div><div class="eyebrow">01 / Spatial perspective</div><h2>The occurrence atlas</h2></div><span class="pill">Direct grid probabilities</span></div><div class="mapcard"><div class="maptop"><div><h3>Next-day calibrated probability</h3><p>@@MAPNOTE@@</p></div><div><button id="previous" aria-label="Previous day">←</button> <input id="day" type="range" min="0" value="0" aria-label="Target day"> <button id="next" aria-label="Next day">→</button> <span id="date"></span></div></div><svg id="map" viewBox="0 0 1000 240" role="img" aria-label="Equal-area cell probability map"></svg><div class="mapfooter"><span>Lower <i class="gradient"></i> Higher · relative display scale · outlined = observed event</span><span id="cellinfo">Select a cell to inspect its probability.</span></div></div><p style="font-size:11px">@@DRAWNOTE@@ Excluded and unavailable cells remain nodata. GeoTIFFs retain continuous probabilities, a documented CRS, and frozen classes.</p></section>
<section id="evidence"><div class="sectionhead"><div><div class="eyebrow">02 / Evidence & uncertainty</div><h2>Discrimination is only part of the picture.</h2></div><span class="pill">@@ROWS@@ evaluated cell-days</span></div><img class="widefigure" src="@@FIGURE@@" alt="Measured average precision and reliability with bootstrap intervals"><div class="twocol"><div class="card"><h3>All models, same final holdout</h3><p>Selection uses development data. Test scores do not change the selected model, threshold or class boundaries.</p><table><thead><tr><th>Model</th><th>AP</th><th>Brier</th><th>BSS</th><th>F1</th></tr></thead><tbody>@@TABLE@@</tbody></table><p>@@RESAMPLES@@ paired space-time bootstrap resamples. The primary configuration uses the full research budget; demonstration budgets are recorded separately.</p></div><div class="card"><h3>What contributed to the tree prediction?</h3><p>TreeSHAP explains uncalibrated log-odds. Correlated predictors are also analyzed as semantic groups. These are predictive associations.</p><img src="@@SHAP@@" alt="TreeSHAP predictive association rankings"><details><summary>Negative results are part of the record</summary><pre>@@NEGATIVE@@</pre><p>See findings.txt and paired_intervals.csv for differences whose interval includes zero.</p></details></div></div></section>
<section id="protocol"><div class="sectionhead"><div><div class="eyebrow">03 / Protocol before prediction</div><h2>Time is a boundary. So is geography.</h2></div><span class="pill">Reproducible by construction</span></div><div class="timeline"><div><strong>2015–2021</strong>Development · rolling origin + buffered spatial folds</div><div><strong>2022</strong>Sigmoid + threshold</div><div><strong>2023–2024</strong>Final evaluation</div></div><div class="twocol"><div class="card"><h3>Source → availability → predictor</h3><p>VIIRS event labels; hourly ERA5-Land; lagged MOD13A2 composites; preceding-year cover fractions; native-resolution terrain; dated human factors. Every nonmissing predictor has a timestamp strictly before its target day.</p><p>Historical roads are omitted when unavailable. Their absence is recorded, never replaced by current roads.</p></div><div class="card"><h3>Rebuild the evidence</h3><pre>python -m wildfire_kz synthetic
python -m wildfire_kz run-all -c configs/synthetic.yaml
python -m pytest -q</pre><p>@@TRIALS@@ tuning trial(s) per ensemble in this configuration. Package versions, hardware, source hashes, exclusions and split manifests accompany the report.</p></div></div><div class="stages">@@STAGES@@</div></section><footer>STEPPE / OBSERVATORY · Research software · Predictive association, not causal attribution · Report generated only from executed artifacts.<br>Outputs: model_summary.csv · evaluation.png / .pdf · findings.txt · reproducibility.json</footer></main>
<script type="application/json" id="payload">@@PAYLOAD@@</script><script>
const data=JSON.parse(document.getElementById('payload').textContent),slider=document.getElementById('day'),svg=document.getElementById('map');slider.max=data.days.length-1;
const all=Object.values(data.predictions).flatMap(d=>Object.values(d).map(v=>v.p)),scale=all.reduce((m,p)=>Math.max(m,p),0.001);
const nodes={};data.cells.forEach(c=>{let p=document.createElementNS('http://www.w3.org/2000/svg','path');p.setAttribute('d',c.path);p.setAttribute('tabindex','0');p.setAttribute('aria-label',c.id);svg.appendChild(p);nodes[c.id]=p;p.addEventListener('click',()=>inspect(c.id));p.addEventListener('focus',()=>inspect(c.id));});
function inspect(id){const value=data.predictions[data.days[+slider.value]][id];document.getElementById('cellinfo').textContent=value?`${id} · p = ${value.p.toFixed(5)} · observed = ${value.y}`:`${id} · excluded or outside evaluation sample`;}
function render(){const day=data.days[+slider.value],values=data.predictions[day];document.getElementById('date').textContent=day;data.cells.forEach(c=>{let v=values[c.id],p=nodes[c.id];if(!v){p.setAttribute('fill','#284d40');p.style.strokeWidth='.45';return;}const t=Math.min(v.p/scale,1);p.setAttribute('fill',`rgb(${Math.round(155+60*t)},${Math.round(194-96*t)},${Math.round(143-87*t)})`);p.setAttribute('stroke',v.y?'#fff7dc':'#72917a');p.style.strokeWidth=v.y?'2':'.45';});}
slider.addEventListener('input',render);document.getElementById('previous').onclick=()=>{slider.value=Math.max(0,+slider.value-1);render();};document.getElementById('next').onclick=()=>{slider.value=Math.min(data.days.length-1,+slider.value+1);render();};render();
</script></body></html>"""
