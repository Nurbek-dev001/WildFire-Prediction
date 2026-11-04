"""Keep the forecast record on its own branch, so every entry gets a timestamp outside this machine.

The branch `forecast-log` holds the log, each day's payloads and heat-source list, the
day-ahead log (dayahead.jsonl) and its payloads, the map
record of the daily forecasts, the latest alert bulletin and the status of the last cloud run.
It shares no history with the code and lives in a separate worktree (runs/forecast_live/git),
so the checked-out branch is never touched. The GitHub push time of each commit is the external
proof that a forecast existed before its day.
Usage: push_forecast_log.py [--pull] [--status OUTCOME]
  --pull     copy the log and payloads from the branch into runs/forecast_live (cloud start)
  --status   also record the outcome of this run in status.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / "runs/forecast_live"
TREE = LIVE / "git"
BRANCH = "forecast-log"
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
FILES = {
    LIVE / "log.jsonl": "log.jsonl",
    LIVE / "dayahead.jsonl": "dayahead.jsonl",
    ROOT / "platform/dist/assets/forecast-live.json": "forecast-live.json",
    ROOT / "platform/dist/assets/bulletin-latest.csv": "bulletin-latest.csv",
}


def git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def worktree() -> None:
    if TREE.exists():
        return
    if git("ls-remote", "--heads", "origin", BRANCH):
        git("fetch", "origin", f"{BRANCH}:refs/remotes/origin/{BRANCH}")
        if not git("branch", "--list", BRANCH):
            git("branch", BRANCH, f"origin/{BRANCH}")
        git("worktree", "add", str(TREE), BRANCH)
    else:
        git("worktree", "add", "--orphan", "-b", BRANCH, str(TREE))


def pull() -> None:
    worktree()
    if (TREE / "log.jsonl").exists():
        LIVE.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(TREE / "log.jsonl", LIVE / "log.jsonl")
    if (TREE / "forecasts").exists():
        shutil.copytree(TREE / "forecasts", LIVE / "forecasts", dirs_exist_ok=True)
    if (TREE / "dayahead.jsonl").exists():
        shutil.copyfile(TREE / "dayahead.jsonl", LIVE / "dayahead.jsonl")
    if (TREE / "dayahead").exists():
        shutil.copytree(TREE / "dayahead", LIVE / "dayahead", dirs_exist_ok=True)
    print(
        "forecast log: pulled",
        len((LIVE / "log.jsonl").read_text().splitlines()) if (LIVE / "log.jsonl").exists() else 0,
        "entries",
    )


def push(status: str | None) -> None:
    worktree()
    for source, name in FILES.items():
        if source.exists():
            shutil.copyfile(source, TREE / name)
    if (LIVE / "forecasts").exists():
        shutil.copytree(LIVE / "forecasts", TREE / "forecasts", dirs_exist_ok=True)
    if (LIVE / "dayahead").exists():
        shutil.copytree(
            LIVE / "dayahead",
            TREE / "dayahead",
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("replay"),
        )
    if status:
        # STATUS_FILE and STATUS_LOG let the bot workflow record its own run beside the forecast's.
        source = Path(os.environ.get("STATUS_LOG", LIVE / "runs.log"))
        text = source.read_text(encoding="utf-8", errors="replace") if source.exists() else ""
        # Secrets never reach the branch, even if a tool printed one.
        for name in ("TELEGRAM_TOKEN", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"):
            if os.environ.get(name):
                text = text.replace(os.environ[name], "***")
        # Nor personal data: wrangler prints the account's e-mail address on every deploy.
        text = EMAIL.sub("<e-mail>", text)
        tail = text.splitlines()[-60:]
        (TREE / os.environ.get("STATUS_FILE", "status.json")).write_text(
            json.dumps(
                {
                    "finished_utc": datetime.now(UTC).isoformat(timespec="seconds"),
                    "outcome": status,
                    "run": os.environ.get("GITHUB_RUN_ID"),
                    "runner": os.environ.get("RUNNER_OS", "local"),
                    "output_tail": tail,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    git("add", "-A", ".", cwd=TREE)
    if not git("status", "--porcelain", cwd=TREE):
        print("forecast log: nothing new")
        return
    log = TREE / "log.jsonl"
    last = (
        json.loads(log.read_text(encoding="utf-8").splitlines()[-1])["target_day"]
        if log.exists()
        else "-"
    )
    git(
        "commit",
        "-m",
        f"Forecast log through {last}" + (f" ({status})" if status else ""),
        cwd=TREE,
    )
    # Another job (the bot deploy, a parallel run) may have pushed meanwhile: rebase and retry.
    for attempt in range(4):
        try:
            git("push", "origin", BRANCH, cwd=TREE)
            break
        except subprocess.CalledProcessError:
            if attempt == 3:
                raise
            git("fetch", "origin", BRANCH, cwd=TREE)
            git("rebase", f"origin/{BRANCH}", cwd=TREE)
    print(f"forecast log through {last} pushed to {BRANCH}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pull", action="store_true")
    parser.add_argument("--status")
    args = parser.parse_args()
    pull() if args.pull else push(args.status)
