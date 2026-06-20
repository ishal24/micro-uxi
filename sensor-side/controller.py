from __future__ import annotations

import argparse
import queue
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[1]))
    sys.path.append(str(Path(__file__).resolve().parent))

from monitoring.probes import FastProbe, OverheadProbe, TelemetryProbe, ThroughputProbe
from monitoring.utils import append_jsonl, safe_mkdir
from config import load_json, normalize_main_config_paths, validate_detection_config, validate_main_config


def parse_duration(value: str) -> float | None:
    raw = value.strip().lower()
    if raw in {"0", "inf", "indefinite", "forever"}:
        return None
    if raw.endswith("h"):
        return float(raw[:-1]) * 3600
    if raw.endswith("m"):
        return float(raw[:-1]) * 60
    if raw.endswith("s"):
        return float(raw[:-1])
    return float(raw)


@dataclass
class WorkerSpec:
    name: str
    interval_sec: float
    probe: object


class SensorController:
    def __init__(self, config: dict[str, Any], detection_config: dict[str, Any], output_override: str | None = None):
        self.config = config
        self.detection_config = detection_config
        output_cfg = config["output"]
        self.output_enabled = bool(output_cfg.get("enabled", True))
        self.verbose = bool(output_cfg.get("verbose", False))
        self.run_id = f"run-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        base_output_dir = output_override or output_cfg.get("output_dir", "./sensor-side/out")
        self.output_dir = safe_mkdir(base_output_dir) / self.run_id if self.output_enabled else None
        self.samples_dir = safe_mkdir(self.output_dir / "samples") if self.output_enabled else None
        self.stop_event = threading.Event()
        self.print_lock = threading.Lock()
        self.sample_queue: queue.Queue[tuple[str, dict[str, Any] | None, str | None]] = queue.Queue()
        self.sample_counts = {"fast": 0, "telemetry": 0, "throughput": 0, "overhead": 0}
        self.error_counts = {"fast": 0, "telemetry": 0, "throughput": 0, "overhead": 0}
        self.worker_intervals = {
            "fast": float(config["scheduler"].get("fast_interval_sec", 5)),
            "telemetry": float(config["scheduler"].get("telemetry_interval_sec", 30)),
            "throughput": float(config["scheduler"].get("throughput_interval_sec", 300)),
            "overhead": float(config["scheduler"].get("overhead_interval_sec", 30)),
        }
        self.sample_paths = (
            {
                "fast": self.samples_dir / f"fast_{self.run_id}.jsonl",
                "telemetry": self.samples_dir / f"telemetry_{self.run_id}.jsonl",
                "throughput": self.samples_dir / f"throughput_{self.run_id}.jsonl",
                "overhead": self.samples_dir / f"overhead_{self.run_id}.jsonl",
            }
            if self.output_enabled
            else {}
        )

    def build_workers(self) -> list[WorkerSpec]:
        workers: list[WorkerSpec] = []
        if self.config.get("modules", {}).get("fast", True) and self.config.get("fast_probe", {}).get("enabled", True):
            workers.append(WorkerSpec("fast", self.worker_intervals["fast"], FastProbe(self.config)))
        if self.config.get("modules", {}).get("telemetry", True) and self.config.get("telemetry_probe", {}).get("enabled", True):
            workers.append(WorkerSpec("telemetry", self.worker_intervals["telemetry"], TelemetryProbe(self.config)))
        if self.config.get("modules", {}).get("throughput", False) and self.config.get("throughput_probe", {}).get("enabled", False):
            workers.append(WorkerSpec("throughput", self.worker_intervals["throughput"], ThroughputProbe(self.config)))
        if self.config.get("modules", {}).get("overhead", True) and self.config.get("overhead_probe", {}).get("enabled", True):
            workers.append(WorkerSpec("overhead", self.worker_intervals["overhead"], OverheadProbe(self.config)))
        return workers

    def _worker_loop(self, spec: WorkerSpec) -> None:
        while not self.stop_event.is_set():
            started = time.monotonic()
            try:
                sample = spec.probe.collect()
                self.sample_queue.put((spec.name, sample, None))
            except Exception as exc:  # pragma: no cover
                self.sample_queue.put((spec.name, None, str(exc)))

            elapsed = time.monotonic() - started
            self.stop_event.wait(max(0.0, spec.interval_sec - elapsed))

    def _write_sample(self, probe_name: str, sample: dict[str, Any]) -> None:
        if not self.output_enabled:
            return
        append_jsonl(self.sample_paths[probe_name], sample)

    def _print(self, message: str) -> None:
        with self.print_lock:
            print(message, flush=True)

    def _print_banner(self, workers: list[WorkerSpec], duration_sec: float | None) -> None:
        duration_label = f"{duration_sec:.0f}s ({duration_sec / 60:.1f} min)" if duration_sec else "indefinite (Ctrl+C to stop)"
        detection_state = "disabled" if not self.detection_config["detector"]["enabled"] else "enabled"
        with self.print_lock:
            print("=" * 72)
            print("  Micro-UXI Sensor-Side Controller")
            print("=" * 72)
            print(f"  Run ID      : {self.run_id}")
            print(f"  Device      : {self.config['device']['device_id']} @ {self.config['device'].get('site_name', '?')}")
            print(f"  Interface   : {self.config['device']['iface']}")
            print(f"  Duration    : {duration_label}")
            print(f"  Detection   : {detection_state} (loaded from detection.json, not evaluated)")
            print(f"  Output dir  : {self.output_dir.resolve() if self.output_enabled else 'disabled'}")
            print(f"  Verbose     : {'on' if self.verbose else 'off'}")
            for worker in workers:
                print(f"  {worker.name:<11}: every {worker.interval_sec:g}s")
            print("=" * 72)

    def _print_sample_line(self, probe_name: str, sample: dict[str, Any]) -> None:
        ts = sample.get("ts", "")[11:19] if sample.get("ts") else "--:--:--"

        if probe_name == "fast":
            wifi = sample.get("wifi", {})
            ping = sample.get("ping", {})
            dns_rows = sample.get("dns", [])
            dns_text = ", ".join(
                f"{row.get('target')}={'OK' if row.get('success') else row.get('status')}"
                for row in dns_rows
            )
            self._print(
                f"[FAST] {ts} wifi={'UP' if wifi.get('wifi_up') else 'DOWN'} "
                f"ping={'OK' if ping.get('success') else 'FAIL'} dns=[{dns_text}]"
            )
            return

        if probe_name == "telemetry":
            wifi = sample.get("wifi", {})
            ping = sample.get("ping", {})
            self._print(
                f"[TELEMETRY] {ts} wifi={'UP' if wifi.get('wifi_connected') else 'DOWN'} "
                f"rssi={wifi.get('wifi_rssi_dbm')} rtt={ping.get('rtt_avg_ms')}ms loss={ping.get('loss_pct')}%"
            )
            return

        if probe_name == "throughput":
            summary = sample.get("summary", {})
            dl = ((summary.get("download") or {}).get("throughput_total_mbps") or {}).get("avg")
            ul = ((summary.get("upload") or {}).get("upload_throughput_total_mbps") or {}).get("avg")
            self._print(f"[THROUGHPUT] {ts} dl_avg={dl}Mbps ul_avg={ul}Mbps")
            return

        if probe_name == "overhead":
            self._print(
                f"[OVERHEAD] {ts} cpu={sample.get('cpu_pct')}% mem={sample.get('mem_pct')}% "
                f"disk={sample.get('disk_pct')}% rx={sample.get('net_rx_kbs')}KB/s tx={sample.get('net_tx_kbs')}KB/s"
            )

    def _print_summary(self, elapsed_sec: float) -> None:
        with self.print_lock:
            print("=" * 72)
            print("  Session complete")
            print("=" * 72)
            print(f"  Elapsed      : {elapsed_sec:.1f}s ({elapsed_sec / 60:.1f} min)")
            for probe_name in ("fast", "telemetry", "throughput", "overhead"):
                print(
                    f"  {probe_name:<12}: samples={self.sample_counts[probe_name]} "
                    f"errors={self.error_counts[probe_name]}"
                )
            if self.output_enabled:
                print(f"  Samples      : {self.samples_dir.resolve()}")
            else:
                print("  Output       : disabled")
            print("=" * 72)

    def run(self, duration_sec: float | None = None) -> None:
        workers = self.build_workers()
        if not workers:
            raise SystemExit("No monitoring workers are enabled in config.")

        threads = [
            threading.Thread(target=self._worker_loop, args=(worker,), daemon=True, name=worker.name)
            for worker in workers
        ]

        self._print_banner(workers, duration_sec)
        started = time.monotonic()
        deadline = started + duration_sec if duration_sec is not None else None
        for thread in threads:
            thread.start()

        try:
            while not self.stop_event.is_set():
                if deadline is not None and time.monotonic() >= deadline:
                    self._print("[i] Target duration reached.")
                    break
                try:
                    probe_name, sample, error = self.sample_queue.get(timeout=0.5)
                except queue.Empty:
                    continue

                if error is not None:
                    self.error_counts[probe_name] += 1
                    self._print(f"[{probe_name.upper()} ERROR] {error}")
                    continue

                assert sample is not None
                self.sample_counts[probe_name] += 1
                self._write_sample(probe_name, sample)
                self._print_sample_line(probe_name, sample)
        except KeyboardInterrupt:
            self._print("[!] Stopped by user.")
        finally:
            self.stop_event.set()
            for thread in threads:
                thread.join(timeout=10)
            self._print_summary(time.monotonic() - started)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Monitoring-first controller for Micro-UXI sensor-side")
    parser.add_argument("--config", default=str(Path(__file__).with_name("config.json")), help="Main sensor config JSON")
    parser.add_argument(
        "--detection-config",
        default=str(Path(__file__).with_name("detection.json")),
        help="Detection placeholder config JSON",
    )
    parser.add_argument("--duration", default="0", help="Run duration: 15m / 1h / 0")
    parser.add_argument("--output", default=None, help="Override output directory")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    try:
        main_config = load_json(args.config)
        main_config = normalize_main_config_paths(main_config, Path(args.config).resolve().parent)
        detection_config = load_json(args.detection_config)
        validate_main_config(main_config)
        validate_detection_config(detection_config)
    except ValueError as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc

    controller = SensorController(main_config, detection_config, output_override=args.output)
    controller.run(parse_duration(args.duration))


if __name__ == "__main__":
    main()
