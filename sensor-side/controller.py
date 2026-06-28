from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent))

from config import load_config
from detection import DetectionRuntime, load_detection_config
from monitoring import MonitoringRuntime, parse_duration
from overhead import OverheadRuntime
from probe.utils import safe_mkdir


class SensorRuntimeController:
    def __init__(self, config: dict, output_override: str | None = None):
        self.config = config
        runtime_cfg = config["runtime"]
        base_output = output_override or runtime_cfg["output_dir"]
        self.output_dir = safe_mkdir(base_output)
        self.modules_cfg = config["modules"]
        self.monitoring: MonitoringRuntime | None = None
        self.overhead: OverheadRuntime | None = None
        self.detection: DetectionRuntime | None = None

        if self.modules_cfg["monitoring"]["enabled"]:
            self.monitoring = MonitoringRuntime(config, self.output_dir)
        if self.modules_cfg["overhead"]["enabled"]:
            self.overhead = OverheadRuntime(config, self.output_dir)
        if self.modules_cfg["detection"]["enabled"]:
            detection_config = load_detection_config(config["detection"]["config_file"])
            self.detection = DetectionRuntime(config, detection_config, self.output_dir)
            if self.monitoring:
                self.monitoring.add_sample_subscriber(self.detection.submit_sample)

    def _banner(self, duration_sec: float | None) -> None:
        duration_label = f"{duration_sec:.0f}s ({duration_sec / 60:.1f} min)" if duration_sec else "indefinite (Ctrl+C to stop)"
        monitoring_cfg = self.config["monitoring"]
        overhead_cfg = self.config["overhead"]
        print("=" * 72)
        print("  Micro-UXI Sensor Runtime")
        print("=" * 72)
        print(f"  Device      : {self.config['device']['device_id']} @ {self.config['device'].get('site_name', '?')}")
        print(f"  Interface   : {self.config['device']['iface']}")
        print(f"  Duration    : {duration_label}")
        print(f"  Output dir  : {self.output_dir.resolve()}")
        print(f"  Monitoring  : {'enabled' if self.monitoring else 'disabled'}")
        if self.monitoring:
            print(
                "  Monitoring  : "
                f"fast={monitoring_cfg['scheduler']['fast_interval_sec']}s "
                f"telemetry={monitoring_cfg['scheduler']['telemetry_interval_sec']}s "
                f"write_jsonl={monitoring_cfg.get('write_jsonl', False)} "
                f"verbose_terminal={monitoring_cfg.get('verbose_terminal', True)}"
            )
        print(f"  Overhead    : {'enabled' if self.overhead else 'disabled'}")
        if self.overhead:
            print(
                "  Overhead    : "
                f"interval={overhead_cfg.get('interval_sec', 2)}s "
                f"write_jsonl={overhead_cfg.get('write_jsonl', False)} "
                f"verbose_terminal={overhead_cfg.get('verbose_terminal', False)}"
            )
        print(f"  Detection   : {'enabled' if self.detection else 'disabled'}")
        if self.detection:
            print(
                "  Detection   : "
                f"mode={self.detection.mode} "
                f"write_jsonl={self.detection.write_jsonl} "
                f"verbose_terminal={self.detection.verbose_terminal}"
            )
        print(f"  Evidence    : placeholder (enabled={self.modules_cfg['evidence']['enabled']})")
        print(f"  Exporter    : placeholder (enabled={self.modules_cfg['exporter']['enabled']})")
        print("=" * 72)

    def run(self, duration_sec: float | None = None) -> None:
        self._banner(duration_sec)
        started = time.monotonic()
        deadline = started + duration_sec if duration_sec is not None else None
        threads: list[threading.Thread] = []

        if self.overhead:
            self.overhead.start()
        if self.detection:
            self.detection.start()

        if self.monitoring:
            thread = threading.Thread(target=self.monitoring.run_forever, daemon=True, name="monitoring")
            threads.append(thread)
            thread.start()

        try:
            while True:
                if deadline is not None and time.monotonic() >= deadline:
                    print("[RUNTIME] Target duration reached.", flush=True)
                    break
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("[RUNTIME] Stopped by user.", flush=True)
        finally:
            if self.monitoring:
                self.monitoring.stop_event.set()
            if self.overhead:
                self.overhead.stop_event.set()
            if self.detection:
                self.detection.stop_event.set()

            for thread in threads:
                thread.join(timeout=10)
            if self.overhead:
                self.overhead.join()
            if self.detection:
                self.detection.join()

            elapsed = time.monotonic() - started
            print("=" * 72)
            print("  Runtime Complete")
            print("=" * 72)
            print(f"  Elapsed      : {elapsed:.1f}s ({elapsed / 60:.1f} min)")
            if self.monitoring:
                print(
                    "  Monitoring   : "
                    f"fast_samples={self.monitoring.sample_counts['fast']} "
                    f"telemetry_samples={self.monitoring.sample_counts['telemetry']} "
                    f"fast_errors={self.monitoring.error_counts['fast']} "
                    f"telemetry_errors={self.monitoring.error_counts['telemetry']}"
                )
            if self.overhead:
                print(
                    "  Overhead     : "
                    f"samples={self.overhead.sample_count} "
                    f"errors={self.overhead.error_count}"
                )
            if self.detection:
                print(
                    "  Detection    : "
                    f"samples={self.detection.sample_count} "
                    f"events={self.detection.event_count} "
                    f"errors={self.detection.error_count}"
                )
            print("=" * 72)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sensor-side master controller")
    parser.add_argument("--config", default=str(Path(__file__).with_name("config.json")), help="Sensor config JSON")
    parser.add_argument("--duration", default=None, help="Run duration: 15m / 1h / 0")
    parser.add_argument("--output", default=None, help="Override runtime output directory")
    parser.add_argument("--disable-monitoring", action="store_true", help="Disable monitoring module")
    parser.add_argument("--disable-overhead", action="store_true", help="Disable overhead module")
    parser.add_argument("--enable-monitoring-jsonl", action="store_true", help="Force monitoring JSONL output on")
    parser.add_argument("--enable-overhead-jsonl", action="store_true", help="Force overhead JSONL output on")
    parser.add_argument("--quiet-monitoring", action="store_true", help="Disable verbose monitoring terminal output")
    return parser


def main() -> None:
    args = build_parser().parse_args()

    try:
        config = load_config(args.config)
    except ValueError as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc

    if args.disable_monitoring:
        config["modules"]["monitoring"]["enabled"] = False
    if args.disable_overhead:
        config["modules"]["overhead"]["enabled"] = False
    if args.enable_monitoring_jsonl:
        config["monitoring"]["write_jsonl"] = True
    if args.enable_overhead_jsonl:
        config["overhead"]["write_jsonl"] = True
    if args.quiet_monitoring:
        config["monitoring"]["verbose_terminal"] = False

    duration_input = args.duration or config["runtime"].get("default_duration", "0")
    runtime = SensorRuntimeController(config, output_override=args.output)
    runtime.run(parse_duration(duration_input))


if __name__ == "__main__":
    main()
