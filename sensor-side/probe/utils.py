from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_mkdir(path: str | Path) -> Path:
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    return target


def append_jsonl(path: str | Path, record: dict) -> None:
    target = Path(path)
    with target.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        fh.flush()


def run_command(cmd: list[str], timeout: int | float = 15) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return completed.returncode, completed.stdout.strip(), completed.stderr.strip()
    except subprocess.TimeoutExpired:
        return -999, "", "TIMEOUT"
    except Exception as exc:
        return -1, "", str(exc)
