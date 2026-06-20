from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_json(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    try:
        with target.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError as exc:
        raise ValueError(f"File not found: {target}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {target}: {exc.msg} at line {exc.lineno}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"Expected top-level JSON object in {target}")
    return data


def require_keys(payload: dict[str, Any], section_name: str, keys: list[str]) -> None:
    missing = [key for key in keys if key not in payload]
    if missing:
        raise ValueError(f"Missing keys in {section_name}: {', '.join(missing)}")


def validate_main_config(config: dict[str, Any]) -> None:
    require_keys(config, "config", ["device", "scheduler", "output", "fast_probe", "telemetry_probe", "modules"])

    device = config["device"]
    require_keys(device, "device", ["device_id", "iface"])

    scheduler = config["scheduler"]
    require_keys(scheduler, "scheduler", ["fast_interval_sec", "telemetry_interval_sec"])
    for key in ("fast_interval_sec", "telemetry_interval_sec", "throughput_interval_sec", "overhead_interval_sec"):
        if key in scheduler and float(scheduler[key]) <= 0:
            raise ValueError(f"scheduler.{key} must be > 0")

    output = config["output"]
    require_keys(output, "output", ["enabled", "output_dir"])

    fast_probe = config["fast_probe"]
    require_keys(fast_probe, "fast_probe", ["enabled", "ping_target", "targets"])
    if fast_probe["enabled"] and not isinstance(fast_probe.get("targets"), list):
        raise ValueError("fast_probe.targets must be a list")

    telemetry_probe = config["telemetry_probe"]
    require_keys(telemetry_probe, "telemetry_probe", ["enabled", "ping_target", "dns_targets", "http_targets"])

    throughput_probe = config.get("throughput_probe")
    if throughput_probe is not None and not isinstance(throughput_probe, dict):
        raise ValueError("throughput_probe must be an object when present")


def validate_detection_config(config: dict[str, Any]) -> None:
    require_keys(config, "detection config", ["detector", "events"])

    detector = config["detector"]
    require_keys(detector, "detector", ["enabled"])
    if bool(detector["enabled"]):
        raise ValueError("sensor-side first pass requires detector.enabled=false")

    events = config["events"]
    if not isinstance(events, dict):
        raise ValueError("events must be an object")

    expected_events = {"S1", "S2", "S3", "S4", "S5", "S6"}
    missing = sorted(expected_events.difference(events.keys()))
    if missing:
        raise ValueError(f"detection events missing placeholders: {', '.join(missing)}")


def normalize_main_config_paths(config: dict[str, Any], base_dir: str | Path) -> dict[str, Any]:
    root = Path(base_dir)

    output_dir = config.get("output", {}).get("output_dir")
    if isinstance(output_dir, str) and output_dir:
        output_path = Path(output_dir)
        if not output_path.is_absolute():
            config["output"]["output_dir"] = str((root / output_path).resolve())

    throughput_cfg = config.get("throughput_probe", {})
    for mode_name in ("routine", "stress"):
        mode_cfg = throughput_cfg.get(mode_name)
        if not isinstance(mode_cfg, dict):
            continue
        upload_cfg = mode_cfg.get("upload")
        if not isinstance(upload_cfg, dict):
            continue
        payload_path = upload_cfg.get("payload_path")
        if isinstance(payload_path, str) and payload_path:
            candidate = Path(payload_path)
            if not candidate.is_absolute():
                upload_cfg["payload_path"] = str((root / candidate).resolve())

    return config
