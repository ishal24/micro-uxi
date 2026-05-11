from __future__ import annotations

import json
import math
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Iterable


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def iso_add_seconds(value: str, seconds: float) -> str:
    return (parse_ts(value) + timedelta(seconds=seconds)).isoformat()


def run_command(cmd: list[str], timeout: float = 10.0) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except subprocess.TimeoutExpired:
        return -999, "", "TIMEOUT"
    except Exception as exc:  # pragma: no cover - defensive for target device
        return -1, "", str(exc)


def percentile(values: Iterable[float], p: float) -> float | None:
    ordered = sorted(values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]

    k = (len(ordered) - 1) * (p / 100.0)
    floor_idx = math.floor(k)
    ceil_idx = math.ceil(k)
    if floor_idx == ceil_idx:
        return ordered[int(k)]
    return ordered[floor_idx] * (ceil_idx - k) + ordered[ceil_idx] * (k - floor_idx)


def median_abs_deviation(values: Iterable[float]) -> float | None:
    ordered = list(values)
    if not ordered:
        return None
    med = median(ordered)
    deviations = [abs(v - med) for v in ordered]
    return median(deviations)


def safe_mkdir(path: str | Path) -> Path:
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    return target


def write_json(path: str | Path, payload: dict | list) -> None:
    with Path(path).open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)


def append_jsonl(path: str | Path, payload: dict) -> None:
    with Path(path).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, separators=(",", ":")) + "\n")


def json_text(payload: object) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=True)

