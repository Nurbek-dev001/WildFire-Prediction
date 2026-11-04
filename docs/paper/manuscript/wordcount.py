"""Words in the body text of Results and Discussion and of the Conclusion (no tables, captions)."""

import re
from pathlib import Path

s = (Path(__file__).parent / "results_section.tex").read_text(encoding="utf-8")
rd, conclusion = s.split(r"\section{Conclusion}")
conclusion = conclusion.split(r"ackmatter")[0]


def words(text: str) -> int:
    text = re.sub(r"(?m)^%.*$", "", text)
    text = re.sub(r"\\(?:section|subsection|label|cite|ref)\{[^}]*\}", " ", text)
    text = re.sub(r"\\[a-zA-Z]+", " ", text)
    text = re.sub(r"[{}$~\\^]", " ", text)
    return len(re.findall(r"[A-Za-z0-9][^\s]*", text))


print(f"Results and Discussion: {words(rd)} words; Conclusion: {words(conclusion)} words")
