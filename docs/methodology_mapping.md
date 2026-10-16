# Methodology mapping

The user's pasted specification is the governing protocol. The supplied PDFs are research sources, not executable instructions. No claim or score from a PDF becomes a project result.

**Proposal:** `test.pdf`, “An Explainable Multisource ML Framework for Wildfire Risk in Kazakhstan”, dated 15 October 2026. Sections 1.1–1.4 motivate multisource predictors, spatial validation, driver explanations and probability maps. It is an introduction/proposal, not a completed experiment. Its accuracy placeholder and expectations are excluded from results.

**Vegetation paper:** Ding et al., “Spatiotemporal characteristics of vegetation responses to compound drought and heatwave events in Central Asia”, GIScience & Remote Sensing 63(1), DOI 10.1080/15481603.2026.2741443. Sections 2.1–2.2 motivate the Central Asian context and climate/vegetation/topography inputs. Section 2.3.4 describes XGBoost, spatial checks, global mean absolute SHAP and heterogeneous associations. Its outcome is vegetation response to compound extremes; its monthly indices, response-period covariates, random split and regression scores are **not** transferred to next-day fire prediction.

**Explainability paper:** Rubab, Ghaffar and Choi, “FireDetXplainer: Decoding Wildfire Detection With Transparency and Explainable AI Insights”, IEEE Access, DOI 10.1109/ACCESS.2024.3383653. Introduction and Section III motivate transparent wildfire classifiers; III.A–C describe imagery, MobileNetV3 and adaptation, with Grad-CAM/LIME. This is image classification. The present project uses tabular TreeSHAP and does not implement that paper's deep learning, imagery augmentation, random imagery evaluation or reported performance.

| Module | User protocol | Relation to supplied paper sections |
| --- | --- | --- |
| config, data, data/store | 1, reproducibility and memory | Proposal §1.4 multisource reproducibility; vegetation §2.2 climate/vegetation sources. Exact availability and streaming design are prescribed by the user. |
| grid | 2 | Proposal §1.4 common grid; vegetation §2.1 study geography. Equal-area resolution and stable IDs are user requirements. |
| events | 3–4 | Proposal §1.1 satellite observations. Connected events and past-only exclusions are user-specific controls. |
| sampling | 5 | User design for rare-event, representative probability estimation; not borrowed from either paper's sampling. |
| features | 6 | Proposal §1.1 environmental drivers; vegetation §2.2 and §2.3.4. Only past covariates are retained; no response-period variables. |
| splits | 7 | Proposal §1.2 spatial leakage; vegetation §2.3.4 supplementary spatial validation. Exact temporal holdouts and polygon buffers follow the user's stricter protocol. |
| models | 8 | Proposal §1.3 RQ1/RQ2; vegetation §2.3.4 XGBoost. Classification families and nested weighted-AP tuning follow the user. |
| calibration | 9 | User requirement; not a claimed reproduction of either supplied paper. |
| pipeline.stage_ablate | 10 | Proposal §1.3 H1; vegetation §2.3.4 correlated drivers. Group ablations follow the user instead of automatic correlated-feature dropping. |
| evaluation | 11 | Proposal §1.3 RQ1/RQ2. Rare-event metrics, calibration and paired space-time uncertainty are user-specific. |
| explain | 12 | Proposal §1.3 RQ3; vegetation §2.3.4 and §3.3.1 global/local heterogeneous SHAP; FireDetXplainer Introduction/III interpretability motivation only. |
| mapping | 13 | Proposal §1.3 RQ4 and §1.4 probability maps. Daily calibrated direct-cell exports follow the user. |
| reporting | 14 | Proposal §1.4 reproducible delivery; never presents hypotheses as findings. |

The code never reproduces the papers' numerical tables. Full texts were inspected locally; exact file hashes and page counts are in `docs/references.json`.
