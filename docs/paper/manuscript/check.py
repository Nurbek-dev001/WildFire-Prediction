"""Static checks of the assembled manuscript: environments, braces, citations, references."""

import re
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
text = (HERE / "sn-article.tex").read_text(encoding="utf-8")
body = re.sub(r"(?<!\\)%.*", "", text)
opens = Counter(re.findall(r"\\begin\{(\w+\*?)\}", body))
closes = Counter(re.findall(r"\\end\{(\w+\*?)\}", body))
print("environments balanced:", opens == closes, dict(opens))
depth, negative = 0, False
for ch in body.replace("\\{", "").replace("\\}", ""):
    depth += (ch == "{") - (ch == "}")
    negative |= depth < 0
print("braces balanced:", depth == 0 and not negative)
keys = {k.strip() for g in re.findall(r"\\cite\{([^}]*)\}", body) for k in g.split(",")}
bib = set(re.findall(r"@\w+\{([^,]+),", (HERE / "references.bib").read_text(encoding="utf-8")))
print("missing bib keys:", keys - bib or "none")
labels = set(re.findall(r"\\label\{([^}]*)\}", body))
refs = set(re.findall(r"\\ref\{([^}]*)\}", body))
print("unresolved refs:", refs - labels or "none")
print("floats never referenced:", {x for x in labels if x.startswith(("tab:", "fig:"))} - refs or "none")
figures = re.findall(r"\\includegraphics\[[^]]*\]\{([^}]*)\}", body)
print("figure files present:", all((HERE / f).exists() for f in figures), figures)
layout = "\\centering\\footnotesize\n\\setlength{\\tabcolsep}{3pt}\n\\begin{tabularx}{\\textwidth}"
print("tables:", body.count("\\begin{table}"), "with the shared layout:", body.count(layout))
print("et al. left:", len(re.findall(r"et al\.", body)))
