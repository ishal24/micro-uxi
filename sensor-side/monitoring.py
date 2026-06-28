from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from probe.fast_probe import FastProbe
from probe.telemetry_probe import TelemetryProbe
from probe.utils import append_jsonl


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
    def __init__(self, config: dict[str, Any], output_dir: Path):
        self.config = config
        self.run_id = f"run-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        self.module_cfg = config["monitoring"]
        self.output_dir = output_dir
        self.output_path = self.output_dir / self.module_cfg.get("output_filename", "monitoring.jsonl")
        self.verbose_terminal = bool(self.module_cfg.get("verbose_terminal", True))
        self.write_jsonl = bool(self.module_cfg.get("write_jsonl", False))
        self.stop_event = threading.Event()
        self.print_lock = threading.Lock()
        self.sample_queue: queue.Queue[tuple[str, dict[str, Any] | None, str | None]] = queue.Queue()
        self.sample_counts = {"fast": 0, "telemetry": 0}
        self.error_counts = {"fast": 0, "telemetry": 0}

    def build_workers(self) -> list[WorkerSpec]:
        scheduler = self.module_cfg["scheduler"]
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

    def _write_sample(self, sample: dict[str, Any]) -> None:
        if self.write_jsonl:
            append_jsonl(self.output_path, sample)

    def _print(self, message: str) -> None:
        with self.print_lock:
            print(message, flush=True)

    def _format_fast_line(self, sample: dict[str, Any]) -> str:
        ts = sample.get("ts", "")[11:19] if sample.get("ts") else "--:--:--"
        wifi = sample.get("wifi", {})
        ping = sample.get("ping", {})
        dns_rows = sample.get("dns", [])
        dns_text = ", ".join(
            f"{row.get('target')}={row.get('latency_ms'):.1f}ms/{row.get('status')}"
            if row.get("latency_ms") is not None
            else f"{row.get('target')}={row.get('status')}"
            for row in dns_rows
        )
        return (
            f"[FAST #{sample.get('seq', '?'):>4}] {ts} "
            f"wifi_up={wifi.get('wifi_up')} "
            f"conn_ok={sample.get('connectivity_ok')} "
            f"ping_success={ping.get('success')} ping_rtt={ping.get('rtt_ms')}ms "
            f"dns=[{dns_text}]"
        )

    def _format_telemetry_lines(self, sample: dict[str, Any]) -> list[str]:
        ts = sample.get("ts", "")[11:19] if sample.get("ts") else "--:--:--"
        wifi = sample.get("wifi", {})
        network = sample.get("network", {})
        ping = sample.get("ping", {})
        dns_rows = sample.get("dns", [])
        http_rows = sample.get("http", [])

        lines = [
            f"[TELEMETRY #{sample.get('seq', '?'):>4}] {ts} device={sample.get('device_id')} iface={sample.get('iface')}",
            (
                "  wifi: "
                f"up={wifi.get('wifi_up')} connected={wifi.get('wifi_connected')} "
                f"ssid={wifi.get('wifi_ssid')} bssid={wifi.get('wifi_bssid')} "
                f"rssi={wifi.get('wifi_rssi_dbm')} bitrate={wifi.get('wifi_bitrate_mbps')}Mbps "
                f"freq={wifi.get('wifi_freq_mhz')}MHz"
            ),
            (
                "  network: "
                f"ip={network.get('ip_address')} gw={network.get('gateway_ip')} "
                f"dns_resolvers={network.get('dns_resolvers')}"
            ),
            (
                "  ping: "
                f"success={ping.get('success')} loss={ping.get('loss_pct')}% "
                f"rtt_min={ping.get('rtt_min_ms')} rtt_avg={ping.get('rtt_avg_ms')} "
                f"rtt_max={ping.get('rtt_max_ms')} rtt_mdev={ping.get('rtt_mdev_ms')}"
            ),
        ]

        if dns_rows:
            lines.append("  dns:")
            for row in dns_rows:
                lines.append(
                    "    "
                    f"{row.get('target')}@{row.get('resolver')} scope={row.get('scope')} "
                    f"ok={row.get('success')} status={row.get('status')} "
                    f"latency={row.get('latency_ms')}ms answers={row.get('answers')}"
                )

        if http_rows:
            lines.append("  http:")
            for row in http_rows:
                lines.append(
                    "    "
                    f"{row.get('host')} scope={row.get('scope')} ok={row.get('http_ok')} "
                    f"status={row.get('http_status')} dns={row.get('http_dns_ms')}ms "
                    f"connect={row.get('http_connect_ms')}ms tls={row.get('http_tls_ms')}ms "
                    f"ttfb={row.get('http_ttfb_ms')}ms total={row.get('http_total_ms')}ms "
                    f"bytes={row.get('http_download_bytes')} rc={row.get('curl_rc')}"
                )
        return lines

    def print_sample(self, probe_name: str, sample: dict[str, Any]) -> None:
        if not self.verbose_terminal:
            return
        if probe_name == "fast":
            self._print(self._format_fast_line(sample))
        else:
            for line in self._format_telemetry_lines(sample):
                self._print(line)

    def run_forever(self) -> None:
        workers = self.build_workers()
        threads = [
            threading.Thread(target=self._worker_loop, args=(worker,), daemon=True, name=worker.name)
            for worker in workers
        ]

        for thread in threads:
            thread.start()

        try:
            while not self.stop_event.is_set():
                try:
                    probe_name, sample, error = self.sample_queue.get(timeout=0.5)
                except queue.Empty:
                    continue

                if error is not None:
                    self.error_counts[probe_name] += 1
                    self._print(f"[MONITORING {probe_name.upper()} ERROR] {error}")
                    continue

                assert sample is not None
                self.sample_counts[probe_name] += 1
                self._write_sample(sample)
                self.print_sample(probe_name, sample)
        finally:
            self.stop_event.set()
            for thread in threads:
                thread.join(timeout=10)
