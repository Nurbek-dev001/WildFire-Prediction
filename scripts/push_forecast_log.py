"""Publish the forecast log on its own branch, so every entry gets a timestamp outside this PC.

The branch `forecast-log` holds only the log, the map record of the daily forecasts and the
latest alert bulletin; it shares no history with the code. It lives in a separate worktree
(runs/forecast_live/git), so the checked-out branch is never touched. The GitHub push time
of each commit is the external proof that a forecast existed before its day.
Usage: push_forecast_log.py   (forecast_daily.cmd runs it when FORECAST_PUSH=1)
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TREE = ROOT / "runs/forecast_live/git"
BRANCH = "forecast-log"
FILES = {
    ROOT / "runs/forecast_live/log.jsonl": "log.jsonl",
    ROOT / "platform/dist/assets/forecast-live.json": "forecast-live.json",
    ROOT / "platform/dist/assets/bulletin-latest.csv": "bulletin-latest.csv",
}


def git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def main() -> None:
    if not TREE.exists():
        known = git("branch", "--list", BRANCH) or git("ls-remote", "--heads", "origin", BRANCH)
        if known:
            git("fetch", "origin", BRANCH)
            git("worktree", "add", str(TREE), BRANCH)
        else:
            git("worktree", "add", "--orphan", "-b", BRANCH, str(TREE))
    for source, name in FILES.items():
        if source.exists():
            shutil.copyfile(source, TREE / name)
    git("add", *FILES.values(), cwd=TREE)
    if not git("status", "--porcelain", cwd=TREE):
        print("forecast log: nothing new")
        return
    last = (TREE / "log.jsonl").read_text(encoding="utf-8").splitlines()[-1]
    day = last.split('"target_day": "')[1][:10]
    git("commit", "-m", f"Forecast log through {day}", cwd=TREE)
    git("push", "origin", BRANCH, cwd=TREE)
    print(f"forecast log through {day} pushed to {BRANCH}")


if __name__ == "__main__":
    main()
