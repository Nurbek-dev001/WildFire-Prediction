# Manuscript package: notes

Upload `sn-article.tex`, `references.bib` and the `figures/` folder to the Overleaf project
(next to `sn-jnl.cls`). Compile with pdfLaTeX + BibTeX.

## How it is built

- `results_section.tex` holds Section 4 (Results and Discussion) and Section 5 (Conclusion);
  lines `%FLOAT:<name>` mark where each table or figure goes.
- `build.py` takes the original manuscript, changes author-name citations to numeric ones,
  inserts the section with its tables and figures, and writes `sn-article.tex` and
  `references.bib`.
- `scripts/article_figures.py` draws the six article figures into `figures/` and writes
  `docs/paper/results/tables/T17_comparability.csv`.
- `check.py` runs static checks; `wordcount.py` counts the body words.

## AI use

The paper ends with a "Declaration of generative AI use" (`\bmhead` in the back matter).
It states that Claude (Anthropic) helped with the experiment code, the analysis, the figures
and tables, and the drafting and editing of Sections 4 and 5. Check that it matches how you
worked before you submit.

## Data

All numbers come from the study's own experiment (`runs/public_hindcast`, 2015-2024); nothing
is simulated. The "0.925 at 1:1 balance" value re-weights the same test predictions so they can
be compared with studies that test on balanced samples; nothing is refitted.

## Word counts (body text, without tables and captions)

Results and Discussion: 1,396 words (required 1,200-1,500). Conclusion: 385 words (300-400).

## Tables and figures

Tables 1-7: dataset, plan versus implementation, test performance, transfer, map classes, land
cover, comparison with related studies. All use one layout: caption above, footnotesize, full
text width, booktabs rules.

Figures 1-6: performance (precision-recall and daily capture), predictor-group ablation,
transfer (spatial folds and regions), reliability, SHAP, June 2023 case map.

## Not done here

- No LaTeX is installed on this computer, so the PDF was not compiled; compile on Overleaf.
- Section 3 is still written as a plan ("will"); Table 2 lists every difference from the plan.
- The manuscript has no abstract or keywords yet.
