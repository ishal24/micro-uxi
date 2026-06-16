#!/usr/bin/env python3
"""
Monitoring master for Micro-UXI.

Place this file and monitor_config.json in the monitoring/ folder.
Output dataset: detection_log.jsonl, with optional evidence bundle.
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

from evidence_recorder import EvidenceRecorder

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


def configure_dynamic_thresholds(cfg: dict[str, Any], enabled: bool) -> None:
    tester_config = cfg.setdefault("tester_config", {})
    dynamic_cfg = tester_config.setdefault("dynamic_thresholds", {})
    dynamic_cfg["enabled"] = bool(enabled)


def next_run_output(scenario_dir: Path, event_driven: bool) -> tuple[int, Path]:
    max_index = 0
    pattern = re.compile(r"^run_id_(\d+)(?:_event)?$")

    if scenario_dir.exists():
        for child in scenario_dir.iterdir():
            if not child.is_dir():
                continue
            match = pattern.match(child.name)
            if match:
                max_index = max(max_index, int(match.group(1)))

    next_index = max_index + 1
    suffix = "_event" if event_driven else ""
    return next_index, scenario_dir / f"run_id_{next_index:02d}{suffix}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one monitoring script and append detection rows.")
    parser.add_argument("--event", required=True, help="S1, S2, S3, S4, S5, or S6")
    parser.add_argument("--run-id", default=None, help="Example: S3_RUN_01. Auto-generated when omitted.")
    parser.add_argument("--config", default="monitor_config.json")
    parser.add_argument("--output", default=None, help="Override output JSONL file")
    parser.add_argument(
        "--evidence-bundle",
        action="store_true",
        help="Record evidence_timeline.jsonl and diagnostic_snapshot.json",
    )
    parser.add_argument(
        "--evidence-dir",
        default=None,
        help="Override evidence bundle directory",
    )
    parser.add_argument(
        "--evidence-pre-sec",
        type=int,
        default=None,
        help="Seconds of samples to keep before each ALARM",
    )
    parser.add_argument(
        "--evidence-post-sec",
        type=int,
        default=None,
        help="Seconds of samples to keep after each RECOVERY",
    )
    parser.add_argument(
        "--event-driven",
        action="store_true",
        help="Use run_id_XX_event output folder naming. --evidence-bundle also enables this.",
    )
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

    configure_dynamic_thresholds(cfg, args.event_driven)

    if cfg.get("write_tester_config", True):
        write_tester_config(cfg, base_dir)

    event_cfg = events[event_code]
    expected_event_type = event_cfg["event_type"]
    script_path = base_dir / event_cfg["script"]

    if not script_path.exists():
        raise SystemExit(f"Monitoring script not found: {script_path}")

    scenario_out_dir = base_dir / "out" / f"test_{event_code}"
    scenario_out_dir.mkdir(parents=True, exist_ok=True)

    event_output = args.event_driven or args.evidence_bundle
    run_index, out_dir = next_run_output(scenario_out_dir, event_output)
    out_dir.mkdir(parents=True, exist_ok=False)
    run_id = args.run_id or f"{event_code}_RUN_{run_index:02d}"

    output_file = Path(args.output or cfg.get("output_file", "detection_log.jsonl"))
    if not output_file.is_absolute():
        output_file = out_dir / output_file.name

    raw_log_file = out_dir / "raw_monitor.log"
    evidence_recorder = None
    evidence_enabled = args.evidence_bundle or args.event_driven
    if evidence_enabled:
        evidence_cfg = cfg.get("evidence", {})
        pre_event_sec = args.evidence_pre_sec
        if pre_event_sec is None:
            pre_event_sec = int(evidence_cfg.get("pre_event_sec", 60))
        post_event_sec = args.evidence_post_sec
        if post_event_sec is None:
            post_event_sec = int(evidence_cfg.get("post_event_sec", 60))

        evidence_dir = Path(args.evidence_dir) if args.evidence_dir else out_dir / "evidence"
        if not evidence_dir.is_absolute():
            evidence_dir = out_dir / evidence_dir
        evidence_recorder = EvidenceRecorder(
            evidence_dir,
            run_id,
            event_code,
            expected_event_type,
            cfg.get("tester_config", {}),
            pre_event_sec=pre_event_sec,
            post_event_sec=post_event_sec,
        )

    print(f"[MONITOR_MASTER] run_id={run_id} event={event_code} expected={expected_event_type}")
    print(f"[MONITOR_MASTER] output_dir={out_dir}")
    print(f"[MONITOR_MASTER] script={script_path.name}")
    print(f"[MONITOR_MASTER] dataset={output_file}")
    print(f"[MONITOR_MASTER] raw_log={raw_log_file}")
    if evidence_recorder:
        print(f"[MONITOR_MASTER] evidence_bundle={evidence_recorder.bundle_dir}")
        print(f"[MONITOR_MASTER] evidence_window=pre:{pre_event_sec}s post:{post_event_sec}s")
    if args.event_driven:
        print("[MONITOR_MASTER] dynamic_thresholds=enabled")
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
            [sys.executable, "-u", str(overhead_script), "--run-id", run_id, "--output", str(overhead_out)],
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
                
                f_raw.write(f"[{run_id}] {line}\n")
                f_raw.flush()

                match = EVENT_RE.search(line)
                if not match:
                    if evidence_recorder:
                        evidence_recorder.record_monitor_line(line)
                    continue

                status_type = match.group(1).upper()  # Akan berisi 'ALARM' atau 'RECOVERY'
                detected_event_code = match.group(2).upper()
                detected_event_type = match.group(3).upper()
                record = {
                    "run_id": run_id,
                    "event_type": detected_event_type,
                    "detection_time": now_iso(),
                    "status": status_type
                }
                append_jsonl(output_file, record)
                if evidence_recorder:
                    evidence_recorder.record_detection_event(status_type, detected_event_code, detected_event_type)

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
        if evidence_recorder:
            evidence_recorder.close()
        if overhead_proc:
            overhead_proc.terminate()
            try:
                overhead_proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                overhead_proc.kill()

    return proc.poll() or 0


if __name__ == "__main__":
    raise SystemExit(main())
