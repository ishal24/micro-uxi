from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_config(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    try:
        with target.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError as exc:
        raise ValueError(f"Config file not found: {target}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {target}: {exc.msg} at line {exc.lineno}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"Expected top-level JSON object in {target}")

    validate_config(data)
    normalize_paths(data, target.parent.resolve())
    return data


def validate_config(config: dict[str, Any]) -> None:
    for key in ("device", "controller", "scheduler", "targets", "monitoring"):
        if key not in config:
            raise ValueError(f"Missing config section: {key}")

    device = config["device"]
    for key in ("device_id", "iface"):
        if key not in device:
            raise ValueError(f"Missing device.{key}")

    scheduler = config["scheduler"]
    for key in ("fast_interval_sec", "telemetry_interval_sec"):
        if key not in scheduler:
            raise ValueError(f"Missing scheduler.{key}")
        if float(scheduler[key]) <= 0:
            raise ValueError(f"scheduler.{key} must be > 0")

    controller = config["controller"]
    modules = controller.get("modules")
    if not isinstance(modules, dict):
        raise ValueError("controller.modules must be an object")
    if "monitoring" not in modules:
        raise ValueError("controller.modules.monitoring is required")

    targets = config["targets"]
    for key in ("ping_target", "dns_resolver", "dns_targets", "http_targets"):
        if key not in targets:
            raise ValueError(f"Missing targets.{key}")
    if not isinstance(targets["dns_targets"], list):
        raise ValueError("targets.dns_targets must be a list")
    if not isinstance(targets["http_targets"], list):
        raise ValueError("targets.http_targets must be a list")

    monitoring = config["monitoring"]
    if "output_dir" not in monitoring:
        raise ValueError("Missing monitoring.output_dir")


def normalize_paths(config: dict[str, Any], base_dir: Path) -> None:
    output_dir = config.get("monitoring", {}).get("output_dir")
    if isinstance(output_dir, str) and output_dir:
        path = Path(output_dir)
        if not path.is_absolute():
            config["monitoring"]["output_dir"] = str((base_dir / path).resolve())
