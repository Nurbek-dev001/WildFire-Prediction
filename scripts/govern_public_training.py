"""Use process-scoped HighQoS on AC for the owned comparison; respect user changes."""

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


class PowerState(ctypes.Structure):
    _fields_ = [
        ("Version", wintypes.ULONG),
        ("ControlMask", wintypes.ULONG),
        ("StateMask", wintypes.ULONG),
    ]


def checksum(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    args = parser.parse_args()
    if sys.platform != "win32":
        raise SystemExit("This optional execution helper is Windows-specific")
    process = psutil.Process(args.pid)
    if process.cwd() != str(ROOT) or "compare" not in process.cmdline():
        raise ValueError("PID is not this workspace's public comparison")
    created = process.create_time()
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    signature: list[Any] = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.GetProcessInformation.argtypes = signature
    kernel.GetProcessInformation.restype = wintypes.BOOL
    kernel.SetProcessInformation.argtypes = signature
    kernel.SetProcessInformation.restype = wintypes.BOOL
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    # Query, set information and synchronize on this one owned process only.
    handle = kernel.OpenProcess(0x1000 | 0x200 | 0x100000, False, args.pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())

    def read() -> tuple[int, int]:
        value = PowerState(1, 0, 0)
        if not kernel.GetProcessInformation(handle, 4, ctypes.byref(value), ctypes.sizeof(value)):
            raise ctypes.WinError(ctypes.get_last_error())
        return int(value.ControlMask), int(value.StateMask)

    def write(value: tuple[int, int]) -> None:
        state = PowerState(1, *value)
        if not kernel.SetProcessInformation(handle, 4, ctypes.byref(state), ctypes.sizeof(state)):
            raise ctypes.WinError(ctypes.get_last_error())
        if read() != value:
            raise ValueError("Windows did not confirm the requested process QoS")

    original: tuple[int, int] | None = None
    last_written: tuple[int, int] | None = None
    external_change = False
    record: dict[str, Any] = {
        "pid": args.pid,
        "created_utc": datetime.fromtimestamp(created, UTC).isoformat(),
        "started_utc": datetime.now(UTC).isoformat(),
        "helper_code_sha256": checksum(Path(__file__)),
        "policy": "HighQoS on AC; original process policy on battery; priority unchanged",
        "priority_class_at_start": int(process.nice()),
        "events": [],
        "status": "starting",
    }

    def save() -> None:
        path = RUN / "training_execution_policy.json"
        temporary = path.with_suffix(".json.tmp")
        record["recorded_utc"] = datetime.now(UTC).isoformat()
        temporary.write_text(json.dumps(record, indent=2), encoding="utf-8")
        temporary.replace(path)

    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *[ctypes.byref(t) for t in times]):
            raise ctypes.WinError(ctypes.get_last_error())
        native_creation = (
            ((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime) - 116444736000000000
        ) / 10**7
        if abs(native_creation - created) > 0.001:
            raise ValueError("Process identity changed")
        original = last_written = read()
        record["original"] = list(original)
        if original[0] & 1 and original[1] & 1:
            record["status"] = "existing_explicit_EcoQoS_respected"
            save()
            return
        high = (original[0] | 1, original[1] & ~1)
        while True:
            if read() != last_written:
                external_change = True
                record["status"] = "external_process_policy_change_respected"
                save()
                break
            battery = psutil.sensors_battery()
            plugged = battery is None or bool(battery.power_plugged)
            desired = high if plugged else original
            if desired != last_written:
                write(desired)
                last_written = desired
                record["events"].append(
                    {
                        "utc": datetime.now(UTC).isoformat(),
                        "plugged": plugged,
                        "policy": list(desired),
                    }
                )
                print(
                    f"Owned comparison QoS: {'HighQoS on AC' if plugged else 'original on battery'}",
                    flush=True,
                )
            record.update(status="active", current=list(last_written), plugged=plugged)
            save()
            outcome = kernel.WaitForSingleObject(handle, 30000)
            if outcome == 0:
                record["status"] = "process_exited"
                save()
                break
            if outcome != 258:
                raise ctypes.WinError(ctypes.get_last_error())
    finally:
        if original is not None and not external_change:
            if kernel.WaitForSingleObject(handle, 0) == 258:
                if read() == last_written and last_written != original:
                    write(original)
                    record.update(status="original_policy_restored", current=list(original))
                    save()
        kernel.CloseHandle(handle)


if __name__ == "__main__":
    main()
