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
    "modules": {
        "monitoring": {"enabled": True},
        "overhead": {"enabled": True},
        "detection": {"enabled": False},
        "evidence": {"enabled": False},
        "exporter": {"enabled": False},
    },
    "monitoring": {
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
        "config_file": None,
    },
    "evidence": {
        "enabled": False,
        "buffer_seconds": 60,
    },
    "exporter": {
        "enabled": False,
        "endpoint": None,
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

    modules = _require(config, "modules", "config")
    for module_name in ("monitoring", "overhead", "detection", "evidence", "exporter"):
        modules.setdefault(module_name, {"enabled": False})
        modules[module_name].setdefault("enabled", False)

    monitoring = _require(config, "monitoring", "config")
    _require(monitoring, "scheduler", "monitoring")
    targets = _require(monitoring, "targets", "monitoring")
    _require(targets, "ping_target", "monitoring.targets")
    targets.setdefault("dns_targets", [])
    targets.setdefault("http_targets", [])

    overhead = _require(config, "overhead", "config")
    overhead.setdefault("metrics", {})

    return config
