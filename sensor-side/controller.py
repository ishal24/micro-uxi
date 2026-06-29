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
from evidence import EvidenceRuntime, load_evidence_config
from exporter import ExporterRuntime, load_exporter_config
from monitoring import MonitoringRuntime, parse_duration
from overhead import OverheadRuntime
from probe.utils import safe_mkdir


class SensorRuntimeController:
    def __init__(self, config: dict, output_override: str | None = None):
        self.config = config
        runtime_cfg = config["runtime"]
        base_output = output_override or runtime_cfg["output_dir"]
        self.output_dir = safe_mkdir(base_output)
        self.monitoring: MonitoringRuntime | None = None
        self.overhead: OverheadRuntime | None = None
        self.detection: DetectionRuntime | None = None
        self.evidence: EvidenceRuntime | None = None
        self.exporter: ExporterRuntime | None = None

        if self.config["monitoring"].get("enabled", True):
            self.monitoring = MonitoringRuntime(config, self.output_dir)
        if self.config["overhead"].get("enabled", True):
            self.overhead = OverheadRuntime(config, self.output_dir)
        if self.config["detection"].get("enabled", False):
            detection_config = load_detection_config(config["detection"]["config_file"])
            self.detection = DetectionRuntime(config, detection_config, self.output_dir)
            if self.monitoring:
                self.monitoring.add_sample_subscriber(self.detection.submit_sample)
        if self.config["evidence"].get("enabled", False):
            evidence_config = load_evidence_config(config["evidence"]["config_file"])
            self.evidence = EvidenceRuntime(config, evidence_config, self.output_dir)
            if self.monitoring:
                self.monitoring.add_sample_subscriber(self.evidence.submit_monitoring)
            if self.overhead:
                self.overhead.add_sample_subscriber(self.evidence.submit_overhead)
            if self.detection:
                self.detection.add_transition_subscriber(self.evidence.submit_detection_transition)
        if self.config["exporter"].get("enabled", False):
            exporter_config = load_exporter_config(config["exporter"]["config_file"])
            self.exporter = ExporterRuntime(config, exporter_config)
            if self.monitoring:
                self.monitoring.add_sample_subscriber(self.exporter.submit_monitoring)
            if self.overhead:
                self.overhead.add_sample_subscriber(self.exporter.submit_overhead)
            if self.detection:
                self.detection.add_transition_subscriber(self.exporter.submit_detection)

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
        print(f"  Evidence    : {'enabled' if self.evidence else 'disabled'}")
        if self.evidence:
            print(
                "  Evidence    : "
                f"pre={self.evidence.pre_window_sec}s "
                f"post={self.evidence.post_window_sec}s "
                f"buffer={self.evidence.buffer_seconds}s "
                f"timeline={self.evidence.write_timeline_jsonl} "
                f"snapshot={self.evidence.write_snapshot_json}"
            )
        print(f"  Exporter    : {'enabled' if self.exporter else 'disabled'}")
        if self.exporter:
            print(
                "  Exporter    : "
                f"base_url={self.exporter.base_url or 'unset'} "
                f"queue_max={self.exporter.max_items} "
                f"retry_delay={self.exporter.retry_delay_sec}s"
            )
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
        if self.evidence:
            self.evidence.start()
        if self.exporter:
            self.exporter.start()

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
            if self.evidence:
                self.evidence.stop_event.set()
            if self.exporter:
                self.exporter.stop_event.set()

            for thread in threads:
                thread.join(timeout=10)
            if self.overhead:
                self.overhead.join()
            if self.detection:
                self.detection.join()
            if self.evidence:
                self.evidence.join()
            if self.exporter:
                self.exporter.join()

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
            if self.evidence:
                print(
                    "  Evidence     : "
                    f"opened={self.evidence.bundle_count} "
                    f"closed={self.evidence.closed_count} "
                    f"active={len(self.evidence.active_bundles)} "
                    f"errors={self.evidence.error_count}"
                )
            if self.exporter:
                print(
                    "  Exporter     : "
                    f"queued={self.exporter.queued_count} "
                    f"sent={self.exporter.sent_count} "
                    f"failed={self.exporter.failed_count} "
                    f"retried={self.exporter.retry_count} "
                    f"dropped={self.exporter.dropped_count}"
                )
            print("=" * 72)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sensor-side master controller")
    parser.add_argument("--config", default=str(Path(__file__).with_name("config.json")), help="Sensor config JSON")
    parser.add_argument("--duration", default=None, help="Run duration: 15m / 1h / 0")
    parser.add_argument("--output", default=None, help="Override runtime output directory")
    parser.add_argument("--disable-monitoring", action="store_true", help="Disable monitoring module")
    parser.add_argument("--disable-overhead", action="store_true", help="Disable overhead module")
    parser.add_argument("--disable-detection", action="store_true", help="Disable detection module")
    parser.add_argument("--enable-detection", action="store_true", help="Enable detection module")
    parser.add_argument("--disable-evidence", action="store_true", help="Disable evidence module")
    parser.add_argument("--enable-evidence", action="store_true", help="Enable evidence module")
    parser.add_argument("--disable-exporter", action="store_true", help="Disable exporter module")
    parser.add_argument("--enable-exporter", action="store_true", help="Enable exporter module")
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
        config["monitoring"]["enabled"] = False
    if args.disable_overhead:
        config["overhead"]["enabled"] = False
    if args.disable_detection:
        config["detection"]["enabled"] = False
    if args.enable_detection:
        config["detection"]["enabled"] = True
    if args.disable_evidence:
        config["evidence"]["enabled"] = False
    if args.enable_evidence:
        config["evidence"]["enabled"] = True
    if args.disable_exporter:
        config["exporter"]["enabled"] = False
    if args.enable_exporter:
        config["exporter"]["enabled"] = True
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
