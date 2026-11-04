# Manuscript package: notes

Upload `sn-article.tex`, `references.bib` and the `figures/` folder to the Overleaf project
(next to `sn-jnl.cls`). Compile with pdfLaTeX + BibTeX.

## Status of the new text

Section 4 (Results and Discussion) and Section 5 (Conclusion) were drafted with AI assistance
as a research-organizing and review aid; a LaTeX comment above Section 4 says so. The
assignment states "DON'T use AI", so this draft is not presented as eligible for submission
under that policy. Use it to understand and organize the evidence, and rewrite it yourselves.

All numbers come from the study's own experiment (`runs/public_hindcast`, 2015-2024); nothing
is simulated, imaginary or adapted from another study.

## What changed in the existing text

- Citations written as author names ("Ahajjam et al.", "Gupta and Kim", ...) in Sections 2
  and 3 now use numeric citations as subjects, as in the Introduction (e.g. `\cite{x} link`).
- The last paragraph of the Introduction now describes the joined Section 4 and Section 5.
- Five data-source entries were added to `references.bib` (ERA5, Open-Meteo, NOAA CDR NDVI,
  WorldPop 2010, Natural Earth), because the implemented experiment used them.
- Section 3 is unchanged (it still reads as a plan); Table 2 states every difference between
  the plan and the implementation.

## Word counts (body text, without tables and captions)

Results and Discussion: 1,395 words (required 1,200-1,500). Conclusion: 369 words (300-400).

## Tables and figures

Main text: Tables 1-7 (one layout: caption above, footnotesize, full text width, booktabs
rules) and Figures 1-5 (precision-recall, ablation, reliability, SHAP, June 2023 case).

Suggested supplementary material (in `docs/paper/results`): bootstrap intervals (T5), region
and month strata (T8, T9), top-k capture for all models (T10), SHAP by region (T13),
compute (T14), June 2023 starts (T15), and figures F2, F4, F6-F12.
