from __future__ import annotations

import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from probe.utils import append_jsonl, run_command

try:
    import psutil

    HAS_PSUTIL = True
except ImportError:  # pragma: no cover
    HAS_PSUTIL = False


class OverheadRuntime:
    def __init__(self, config: dict[str, Any], output_dir: Path):
        self.config = config
        self.device_cfg = config["device"]
        self.module_cfg = config["overhead"]
        self.output_path = output_dir / self.module_cfg.get("output_filename", "overhead.jsonl")
        self.write_jsonl = bool(self.module_cfg.get("write_jsonl", False))
        self.verbose_terminal = bool(self.module_cfg.get("verbose_terminal", False))
        self.interval_sec = float(self.module_cfg.get("interval_sec", 2))
        self.metrics_cfg = self.module_cfg.get("metrics", {})
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.sample_count = 0
        self.error_count = 0
        self.sample_subscribers: list = []

    def add_sample_subscriber(self, subscriber) -> None:
        self.sample_subscribers.append(subscriber)

    def start(self) -> None:
        self.thread = threading.Thread(target=self._worker_loop, daemon=True, name="overhead")
        self.thread.start()

    def join(self) -> None:
        if self.thread is not None:
            self.thread.join(timeout=10)

    def _fallback_disk_usage(self) -> dict[str, Any]:
        total, used, free = shutil.disk_usage("/")
        return {
            "total_bytes": total,
            "used_bytes": used,
            "free_bytes": free,
            "used_pct": round((used / total) * 100, 2) if total else None,
        }

    def _fallback_net_io(self) -> dict[str, Any] | None:
        rc, out, _ = run_command(["cat", "/proc/net/dev"], timeout=5)
        if rc != 0:
            return None
        rx_bytes = 0
        tx_bytes = 0
        for line in out.splitlines()[2:]:
            _, payload = line.split(":", 1)
            parts = payload.split()
            rx_bytes += int(parts[0])
            tx_bytes += int(parts[8])
        return {"bytes_sent": tx_bytes, "bytes_recv": rx_bytes}

    def collect(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "module": "overhead",
            "device_id": self.device_cfg.get("device_id"),
            "iface": self.device_cfg.get("iface"),
        }

        if HAS_PSUTIL:
            if self.metrics_cfg.get("cpu", True):
                record["cpu"] = {
                    "percent": psutil.cpu_percent(interval=None),
                    "loadavg": list(psutil.getloadavg()) if hasattr(psutil, "getloadavg") else None,
                }
            if self.metrics_cfg.get("memory", True):
                vm = psutil.virtual_memory()
                record["memory"] = {
                    "total_bytes": vm.total,
                    "available_bytes": vm.available,
                    "used_bytes": vm.used,
                    "used_pct": vm.percent,
                }
            if self.metrics_cfg.get("disk", True):
                du = psutil.disk_usage("/")
                record["disk"] = {
                    "total_bytes": du.total,
                    "used_bytes": du.used,
                    "free_bytes": du.free,
                    "used_pct": du.percent,
                }
            if self.metrics_cfg.get("network", True):
                io = psutil.net_io_counters()
                record["network"] = {
                    "bytes_sent": io.bytes_sent,
                    "bytes_recv": io.bytes_recv,
                    "packets_sent": io.packets_sent,
                    "packets_recv": io.packets_recv,
                    "errin": io.errin,
                    "errout": io.errout,
                    "dropin": io.dropin,
                    "dropout": io.dropout,
                }
        else:
            if self.metrics_cfg.get("disk", True):
                record["disk"] = self._fallback_disk_usage()
            if self.metrics_cfg.get("network", True):
                record["network"] = self._fallback_net_io()

        return record

    def _print(self, record: dict[str, Any]) -> None:
        cpu = (record.get("cpu") or {}).get("percent")
        memory = record.get("memory") or {}
        disk = record.get("disk") or {}
        network = record.get("network") or {}
        print(
            "[OVERHEAD] "
            f"cpu={cpu}% "
            f"mem={memory.get('used_pct')}% "
            f"disk={disk.get('used_pct')}% "
            f"tx={network.get('bytes_sent')}B "
            f"rx={network.get('bytes_recv')}B",
            flush=True,
        )

    def _publish_sample(self, sample: dict[str, Any]) -> None:
        for subscriber in self.sample_subscribers:
            try:
                subscriber(sample)
            except Exception as exc:  # pragma: no cover
                print(f"[OVERHEAD PUBLISH ERROR] {exc}", flush=True)

    def _worker_loop(self) -> None:
        while not self.stop_event.is_set():
            started = time.monotonic()
            try:
                record = self.collect()
                self.sample_count += 1
                if self.write_jsonl:
                    append_jsonl(self.output_path, record)
                self._publish_sample(record)
                if self.verbose_terminal:
                    self._print(record)
            except Exception as exc:  # pragma: no cover
                self.error_count += 1
                print(f"[OVERHEAD ERROR] {exc}", flush=True)

            elapsed = time.monotonic() - started
            self.stop_event.wait(max(0.0, self.interval_sec - elapsed))
