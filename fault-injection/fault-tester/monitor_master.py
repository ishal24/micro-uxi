#!/usr/bin/env python3
"""
Monitoring master for Micro-UXI.

Place this file and monitor_config.json in the monitoring/ folder.
Output dataset: detection_log.jsonl only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

EVENT_RE = re.compile(r"\[(ALARM|RECOVERY)\]\s+(S\d+)\s+([A-Z0-9_]+)", re.IGNORECASE)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
        f.flush()


def normalize_event(value: str) -> str:
    value = value.strip().upper()
    if value in {"1", "2", "3", "4", "5", "6"}:
        return f"S{value}"
    return value


def write_tester_config(cfg: dict[str, Any], base_dir: Path) -> None:
    tester_config_file = base_dir / cfg.get("tester_config_file", "tester_config.json")
    with tester_config_file.open("w", encoding="utf-8") as f:
        json.dump(cfg["tester_config"], f, ensure_ascii=False, indent=2)
        f.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one monitoring script and append detection rows.")
    parser.add_argument("--event", required=True, help="S1, S2, S3, S4, S5, or S6")
    parser.add_argument("--run-id", required=True, help="Example: S3_RUN_01")
    parser.add_argument("--config", default="monitor_config.json")
    parser.add_argument("--output", default=None, help="Override output JSONL file")
    args = parser.parse_args()

    base_dir = Path.cwd().resolve()
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = base_dir / config_path

    cfg = load_json(config_path)
    event_code = normalize_event(args.event)
    events = cfg["events"]

    if event_code not in events:
        valid = ", ".join(sorted(events.keys()))
        raise SystemExit(f"Unknown event '{event_code}'. Valid: {valid}")

    if cfg.get("write_tester_config", True):
        write_tester_config(cfg, base_dir)

    event_cfg = events[event_code]
    expected_event_type = event_cfg["event_type"]
    script_path = base_dir / event_cfg["script"]

    if not script_path.exists():
        raise SystemExit(f"Monitoring script not found: {script_path}")

    out_dir = base_dir / "out" / f"test_{event_code}"
    out_dir.mkdir(parents=True, exist_ok=True)

    output_file = Path(args.output or cfg.get("output_file", "detection_log.jsonl"))
    if not output_file.is_absolute():
        output_file = out_dir / output_file.name

    raw_log_file = out_dir / "raw_monitor.log"

    print(f"[MONITOR_MASTER] run_id={args.run_id} event={event_code} expected={expected_event_type}")
    print(f"[MONITOR_MASTER] script={script_path.name}")
    print(f"[MONITOR_MASTER] dataset={output_file}")
    print(f"[MONITOR_MASTER] raw_log={raw_log_file}")
    print("[MONITOR_MASTER] Ctrl+C to stop.\n")

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    proc = subprocess.Popen(
        [sys.executable, "-u", str(script_path)],
        cwd=str(base_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
    )

    overhead_proc = None
    overhead_script = base_dir / "tester_overhead.py"
    if overhead_script.exists():
        overhead_out = out_dir / "overhead_log.jsonl"
        overhead_proc = subprocess.Popen(
            [sys.executable, "-u", str(overhead_script), "--run-id", args.run_id, "--output", str(overhead_out)],
            cwd=str(base_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

    try:
        assert proc.stdout is not None
        with raw_log_file.open("a", encoding="utf-8") as f_raw:
            for line in proc.stdout:
                line = line.rstrip("\n")
                print(line, flush=True)
                
                f_raw.write(f"[{args.run_id}] {line}\n")
                f_raw.flush()

                match = EVENT_RE.search(line)
                if not match:
                    continue

                status_type = match.group(1).upper()  # Akan berisi 'ALARM' atau 'RECOVERY'
                detected_event_code = match.group(2).upper()
                detected_event_type = match.group(3).upper()
                record = {
                    "run_id": args.run_id,
                    "event_type": detected_event_type,
                    "detection_time": now_iso(),
                    "status": status_type
                }
                append_jsonl(output_file, record)

    except KeyboardInterrupt:
        print("\n[MONITOR_MASTER] stopping...")
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()

    finally:
        if overhead_proc:
            overhead_proc.terminate()
            try:
                overhead_proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                overhead_proc.kill()

    return proc.poll() or 0


if __name__ == "__main__":
    raise SystemExit(main())
