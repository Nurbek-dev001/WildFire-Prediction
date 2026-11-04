# Defense presentation

`wildfire_presentation.pptx` follows the structure of the course template: title, problem
statement (input/output, research questions), collection and processing of input data, models
and methods, results, conclusion, thanks. Speaker notes are on every content slide.
Fill in "Group" and "Supervisor" on the title slide.

All numbers come from `runs/public_hindcast`. The code-cell outputs on the slides were produced
by running `cell_outputs.py` on that data.

Rebuild (from a folder with `pptxgenjs`, `react-icons`, `react`, `react-dom`, `sharp` installed):

1. `python cell_outputs.py cells.json`
2. `python slide_figures.py figs`
3. `node build_deck.js wildfire_presentation.pptx` (set `PPTX_SKILL` to the pptx skill folder
   for `apply_theme.js`)
4. `powershell render.ps1 wildfire_presentation.pptx out` renders the slides with PowerPoint.
