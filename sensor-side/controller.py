from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent))

from config import load_config
from monitoring import MonitoringRuntime, parse_duration


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sensor-side master controller")
    parser.add_argument("--config", default=str(Path(__file__).with_name("config.json")), help="Sensor config JSON")
    parser.add_argument("--duration", default="0", help="Run duration: 15m / 1h / 0")
    parser.add_argument("--output", default=None, help="Override monitoring output directory")
    return parser


def main() -> None:
    args = build_parser().parse_args()

    try:
        config = load_config(args.config)
    except ValueError as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc

    runtime = MonitoringRuntime(config, output_override=args.output)
    runtime.run(parse_duration(args.duration))


if __name__ == "__main__":
    main()
