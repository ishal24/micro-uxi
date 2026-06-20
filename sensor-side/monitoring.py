from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from probe.fast_probe import FastProbe
from probe.telemetry_probe import TelemetryProbe
from probe.utils import append_jsonl, safe_mkdir


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


class MonitoringRuntime:
    def __init__(self, config: dict[str, Any], output_override: str | None = None):
        self.config = config
        self.run_id = f"run-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        monitoring_cfg = config["monitoring"]
        base_output = output_override or monitoring_cfg["output_dir"]
        self.verbose = bool(monitoring_cfg.get("verbose", True))
        self.output_enabled = bool(monitoring_cfg.get("write_jsonl", True))
        self.output_dir = safe_mkdir(base_output) / self.run_id if self.output_enabled else None
        self.samples_dir = safe_mkdir(self.output_dir / "samples") if self.output_enabled else None
        self.stop_event = threading.Event()
        self.print_lock = threading.Lock()
        self.sample_queue: queue.Queue[tuple[str, dict[str, Any] | None, str | None]] = queue.Queue()
        self.sample_counts = {"fast": 0, "telemetry": 0}
        self.error_counts = {"fast": 0, "telemetry": 0}
        self.sample_paths = (
            {
                "fast": self.samples_dir / "fast.jsonl",
                "telemetry": self.samples_dir / "telemetry.jsonl",
            }
            if self.output_enabled
            else {}
        )

    def build_workers(self) -> list[WorkerSpec]:
        scheduler = self.config["scheduler"]
        return [
            WorkerSpec("fast", float(scheduler["fast_interval_sec"]), FastProbe(self.config)),
            WorkerSpec("telemetry", float(scheduler["telemetry_interval_sec"]), TelemetryProbe(self.config)),
        ]

    def _worker_loop(self, spec: WorkerSpec) -> None:
        while not self.stop_event.is_set():
            started = time.monotonic()
            try:
                self.sample_queue.put((spec.name, spec.probe.collect(), None))
            except Exception as exc:  # pragma: no cover
                self.sample_queue.put((spec.name, None, str(exc)))

            elapsed = time.monotonic() - started
            self.stop_event.wait(max(0.0, spec.interval_sec - elapsed))

    def _write_sample(self, probe_name: str, sample: dict[str, Any]) -> None:
        if self.output_enabled:
            append_jsonl(self.sample_paths[probe_name], sample)

    def _print(self, message: str) -> None:
        with self.print_lock:
            print(message, flush=True)

    def _print_banner(self, workers: list[WorkerSpec], duration_sec: float | None) -> None:
        duration_label = f"{duration_sec:.0f}s ({duration_sec / 60:.1f} min)" if duration_sec else "indefinite (Ctrl+C to stop)"
        modules = self.config["controller"].get("modules", {})
        with self.print_lock:
            print("=" * 72)
            print("  Micro-UXI Sensor Controller")
            print("=" * 72)
            print(f"  Run ID      : {self.run_id}")
            print(f"  Device      : {self.config['device']['device_id']} @ {self.config['device'].get('site_name', '?')}")
            print(f"  Interface   : {self.config['device']['iface']}")
            print(f"  Duration    : {duration_label}")
            print(f"  Monitoring  : {'enabled' if modules.get('monitoring', True) else 'disabled'}")
            print("  Detection   : planned, not running")
            print("  Overhead    : planned, not running")
            print("  Exporter    : planned, not running")
            print(f"  Output dir  : {self.output_dir.resolve() if self.output_enabled else 'disabled'}")
            for worker in workers:
                print(f"  {worker.name:<11}: every {worker.interval_sec:g}s")
            print("=" * 72)

    def _print_fast_line(self, sample: dict[str, Any]) -> None:
        ts = sample.get("ts", "")[11:19] if sample.get("ts") else "--:--:--"
        wifi = sample.get("wifi", {})
        ping = sample.get("ping", {})
        dns_rows = sample.get("dns", [])
        dns_text = ", ".join(
            (
                f"{row.get('target')}={row.get('latency_ms'):.1f}ms"
                if row.get("success") and row.get("latency_ms") is not None
                else f"{row.get('target')}={row.get('status')}"
            )
            for row in dns_rows
        )
        ping_text = (
            f"{ping.get('rtt_ms'):.1f}ms"
            if ping.get("success") and ping.get("rtt_ms") is not None
            else "FAIL"
        )
        self._print(
            f"[FAST] {ts} wifi={'UP' if wifi.get('wifi_up') else 'DOWN'} "
            f"ping={ping_text} dns=[{dns_text}]"
        )

    def _print_telemetry_line(self, sample: dict[str, Any]) -> None:
        ts = sample.get("ts", "")[11:19] if sample.get("ts") else "--:--:--"
        wifi = sample.get("wifi", {})
        ping = sample.get("ping", {})
        dns_rows = sample.get("dns", [])
        http_rows = sample.get("http", [])
        dns_text = ", ".join(
            (
                f"{row.get('target')}@{row.get('resolver')}={row.get('latency_ms'):.1f}ms"
                if row.get("success") and row.get("latency_ms") is not None
                else f"{row.get('target')}@{row.get('resolver')}={row.get('status')}"
            )
            for row in dns_rows
        )
        http_text = ", ".join(
            f"{row.get('host')}={row.get('http_status')}/{row.get('http_total_ms'):.1f}ms ttfb={row.get('http_ttfb_ms'):.1f}ms"
            if row.get("http_total_ms") is not None
            else f"{row.get('host')}=FAIL(rc={row.get('curl_rc')})"
            for row in http_rows
        )
        self._print(
            f"[TELEMETRY] {ts} wifi={'UP' if wifi.get('wifi_connected') else 'DOWN'} "
            f"rtt={ping.get('rtt_avg_ms')}ms loss={ping.get('loss_pct')}% "
            f"dns=[{dns_text}] http=[{http_text}]"
        )

    def _print_summary(self, elapsed_sec: float) -> None:
        with self.print_lock:
            print("=" * 72)
            print("  Monitoring complete")
            print("=" * 72)
            print(f"  Elapsed      : {elapsed_sec:.1f}s ({elapsed_sec / 60:.1f} min)")
            for probe_name in ("fast", "telemetry"):
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
                if self.verbose or probe_name == "telemetry":
                    if probe_name == "fast":
                        self._print_fast_line(sample)
                    else:
                        self._print_telemetry_line(sample)
        except KeyboardInterrupt:
            self._print("[!] Stopped by user.")
        finally:
            self.stop_event.set()
            for thread in threads:
                thread.join(timeout=10)
            self._print_summary(time.monotonic() - started)
