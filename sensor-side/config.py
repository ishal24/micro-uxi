from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _require(mapping: dict[str, Any], key: str, ctx: str) -> Any:
    if key not in mapping:
        raise ValueError(f"Missing required key '{ctx}.{key}'")
    return mapping[key]


def _merge(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    merged = dict(a)
    for key, value in b.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


DEFAULT_CONFIG: dict[str, Any] = {
    "device": {
        "device_id": "uno-q-01",
        "site_name": "ITS",
        "iface": "wlan0",
    },
    "runtime": {
        "output_dir": "./out",
        "default_duration": "0",
    },
    "monitoring": {
        "enabled": True,
        "write_jsonl": False,
        "output_filename": "monitoring.jsonl",
        "verbose_terminal": True,
        "scheduler": {
            "fast_interval_sec": 2,
            "telemetry_interval_sec": 20,
        },
        "targets": {
            "ping_target": "8.8.8.8",
            "ping_timeout_sec": 1,
            "dns_targets": [
                {"name": "google.com", "scope": "external"},
            ],
            "dns_timeout_sec": 2,
            "dns_resolver": "8.8.8.8",
            "dns_resolvers": ["system"],
            "telemetry_ping_count": 5,
            "telemetry_ping_interval_sec": 0.2,
            "telemetry_ping_timeout_sec": 10,
            "telemetry_dns_timeout_sec": 5,
            "http_targets": [
                {"url": "https://example.com", "scope": "external"},
            ],
            "http_connect_timeout_sec": 5,
            "http_max_time_sec": 15,
        },
    },
    "overhead": {
        "enabled": True,
        "write_jsonl": False,
        "output_filename": "overhead.jsonl",
        "verbose_terminal": True,
        "interval_sec": 2,
        "metrics": {
            "cpu": True,
            "memory": True,
            "disk": True,
            "network": True,
        },
    },
    "detection": {
        "enabled": False,
        "config_file": "./detection_config.json",
    },
    "evidence": {
        "enabled": False,
        "buffer_seconds": 60,
    },
    "exporter": {
        "enabled": False,
        "config_file": "./exporter_config.json",
    },
}


def load_config(path: str) -> dict[str, Any]:
    config_path = Path(path).resolve()
    with config_path.open("r", encoding="utf-8") as fh:
        loaded = json.load(fh)

    config = _merge(DEFAULT_CONFIG, loaded)

    device = _require(config, "device", "config")
    _require(device, "device_id", "device")
    _require(device, "iface", "device")

    runtime = _require(config, "runtime", "config")
    output_dir = runtime.get("output_dir", "./out")
    runtime["output_dir"] = str((config_path.parent / output_dir).resolve()) if not Path(output_dir).is_absolute() else str(Path(output_dir))

    monitoring = _require(config, "monitoring", "config")
    monitoring.setdefault("enabled", True)
    _require(monitoring, "scheduler", "monitoring")
    targets = _require(monitoring, "targets", "monitoring")
    _require(targets, "ping_target", "monitoring.targets")
    targets.setdefault("dns_targets", [])
    targets.setdefault("http_targets", [])

    overhead = _require(config, "overhead", "config")
    overhead.setdefault("enabled", True)
    overhead.setdefault("metrics", {})

    detection = _require(config, "detection", "config")
    detection.setdefault("enabled", False)
    detection_config_file = detection.get("config_file", "./detection_config.json")
    detection["config_file"] = str((config_path.parent / detection_config_file).resolve()) if not Path(detection_config_file).is_absolute() else str(Path(detection_config_file))

    evidence = _require(config, "evidence", "config")
    evidence.setdefault("enabled", False)

    exporter = _require(config, "exporter", "config")
    exporter.setdefault("enabled", False)
    exporter_config_file = exporter.get("config_file", "./exporter_config.json")
    exporter["config_file"] = str((config_path.parent / exporter_config_file).resolve()) if not Path(exporter_config_file).is_absolute() else str(Path(exporter_config_file))

    # Backward compatibility for older configs that still use config.modules.*.
    # The module block itself remains the single runtime switch after this mapping.
    legacy_modules = config.get("modules") or {}
    for module_name in ("monitoring", "overhead", "detection", "evidence", "exporter"):
        legacy_enabled = ((legacy_modules.get(module_name) or {}).get("enabled"))
        if "enabled" not in loaded.get(module_name, {}) and legacy_enabled is not None:
            config[module_name]["enabled"] = bool(legacy_enabled)

    return config
