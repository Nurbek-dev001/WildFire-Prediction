"""Read the owned Windows comparison worker's lifetime CPU time without changing it."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import sys
from ctypes import wintypes
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psutil

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs/public_hindcast"


def checksum(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def ticks(value: wintypes.FILETIME) -> int:
    return (value.dwHighDateTime << 32) | value.dwLowDateTime


def timestamp(value: wintypes.FILETIME) -> str | None:
    return (
        datetime.fromtimestamp((ticks(value) - 116444736000000000) / 10**7, UTC).isoformat()
        if ticks(value)
        else None
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    args = parser.parse_args()
    if sys.platform != "win32":
        raise SystemExit("This optional observer uses Windows GetProcessTimes")
    process = psutil.Process(args.pid)
    if process.cwd() != str(ROOT) or "compare" not in process.cmdline():
        raise ValueError("PID is not this workspace's public comparison worker")
    creation_time = process.create_time()
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    # QUERY_LIMITED_INFORMATION | SYNCHRONIZE; no process-modification rights.
    handle = kernel.OpenProcess(0x1000 | 0x100000, False, args.pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    attached = datetime.now(UTC).isoformat()
    observer_digest = checksum(Path(__file__))

    def capture(ended: bool) -> dict[str, Any]:
        created, exited, system, user = (wintypes.FILETIME() for _ in range(4))
        if not kernel.GetProcessTimes(
            handle,
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(system),
            ctypes.byref(user),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        if abs((ticks(created) - 116444736000000000) / 10**7 - creation_time) > 0.001:
            raise ValueError("Process creation time differs; refusing a reused PID")
        result: dict[str, Any] = {
            "pid": args.pid,
            "created_utc": timestamp(created),
            "exit_utc": timestamp(exited),
            "observer_attached_utc": attached,
            "recorded_utc": datetime.now(UTC).isoformat(),
            "observer_code_sha256": observer_digest,
            "measurement": "Windows GetProcessTimes; lifetime sum over all process threads",
            "user_cpu_seconds": ticks(user) / 10**7,
            "kernel_cpu_seconds": ticks(system) / 10**7,
            "total_cpu_seconds": (ticks(user) + ticks(system)) / 10**7,
            "process_exited": ended,
            "training_complete": False,
        }
        completed = RUN / "training_complete.json"
        if ended and completed.is_file():
            training = json.loads(completed.read_text())
            digest = checksum(RUN / "models.joblib")
            if digest != training["models_sha256"]:
                raise ValueError("Completed training model hash differs")
            result.update(training_complete=True, models_sha256=digest)
        return result

    try:
        while True:
            value = capture(False)
            path = RUN / "training_cpu.json"
            temporary = path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
            temporary.replace(path)
            outcome = kernel.WaitForSingleObject(handle, 30000)
            if outcome == 0:
                value = capture(True)
                temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
                temporary.replace(path)
                print(json.dumps(value), flush=True)
                break
            if outcome != 258:
                raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.CloseHandle(handle)


if __name__ == "__main__":
    main()
