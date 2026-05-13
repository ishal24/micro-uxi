from __future__ import annotations

import os
import time

from monitoring.probes.common import sample_header

try:
    import psutil

    HAS_PSUTIL = True
except ImportError:  # pragma: no cover - depends on target device
    psutil = None
    HAS_PSUTIL = False


DEFAULT_PROCESS_NAMES = (
    "monitoring.controller",
    "controller.py",
    "telemetry_probe.py",
    "fast_probe.py",
    "throughput_probe.py",
)


class OverheadProbe:
    def __init__(self, config: dict):
        self.config = config
        self.device_cfg = config["device"]
        self.probe_cfg = config.get("overhead_probe", {})
        self._seq = 0
        self._procs = []
        self._last_refresh_seq = -1
        self._last_io_read = 0
        self._last_io_write = 0
        self._last_io_ts = time.monotonic()
        self._last_net_tx = 0
        self._last_net_rx = 0
        self._last_net_ts = time.monotonic()

        if not HAS_PSUTIL:
            return

        io = psutil.disk_io_counters()
        if io:
            self._last_io_read = io.read_bytes
            self._last_io_write = io.write_bytes

        net = psutil.net_io_counters()
        if net:
            self._last_net_tx = net.bytes_sent
            self._last_net_rx = net.bytes_recv

        psutil.cpu_percent(interval=None)
        self._refresh_procs(force=True)

    def collect(self) -> dict:
        self._seq += 1
        sample = sample_header(self.device_cfg, "overhead", self._seq)

        if not HAS_PSUTIL:
            sample.update(
                {
                    "error": "psutil_not_installed",
                    "cpu_pct": None,
                    "temp_c": None,
                    "mem_used_mb": None,
                    "mem_avail_mb": None,
                    "mem_total_mb": None,
                    "mem_pct": None,
                    "disk_pct": None,
                    "disk_used_mb": None,
                    "disk_free_mb": None,
                    "net_tx_kbs": None,
                    "net_rx_kbs": None,
                    "disk_read_kbs": None,
                    "disk_write_kbs": None,
                    "proc_pids": [],
                    "proc_rss_mb": None,
                    "proc_vms_mb": None,
                    "proc_cpu_pct": None,
                    "proc_threads": None,
                }
            )
            return sample

        refresh_every = int(self.probe_cfg.get("refresh_process_every_samples", 30))
        if self._seq == 1 or self._seq - self._last_refresh_seq >= refresh_every:
            self._refresh_procs()

        mono = time.monotonic()
        mem = psutil.virtual_memory()

        read_kb = write_kb = None
        try:
            io = psutil.disk_io_counters()
            if io:
                dt = max(mono - self._last_io_ts, 0.001)
                read_kb = max(round((io.read_bytes - self._last_io_read) / 1024 / dt, 2), 0.0)
                write_kb = max(round((io.write_bytes - self._last_io_write) / 1024 / dt, 2), 0.0)
                self._last_io_read = io.read_bytes
                self._last_io_write = io.write_bytes
                self._last_io_ts = mono
        except Exception:
            pass

        net_tx_kbs = net_rx_kbs = 0.0
        try:
            net = psutil.net_io_counters()
            if net:
                dt_net = max(mono - self._last_net_ts, 0.001)
                net_tx_kbs = max(round((net.bytes_sent - self._last_net_tx) / 1024 / dt_net, 2), 0.0)
                net_rx_kbs = max(round((net.bytes_recv - self._last_net_rx) / 1024 / dt_net, 2), 0.0)
                self._last_net_tx = net.bytes_sent
                self._last_net_rx = net.bytes_recv
                self._last_net_ts = mono
        except Exception:
            pass

        disk_pct = disk_used_mb = disk_free_mb = None
        try:
            disk = psutil.disk_usage("/")
            disk_pct = round(disk.percent, 2)
            disk_used_mb = round(disk.used / 1024 / 1024, 1)
            disk_free_mb = round(disk.free / 1024 / 1024, 1)
        except Exception:
            pass

        temp_c = None
        try:
            temps = psutil.sensors_temperatures() if hasattr(psutil, "sensors_temperatures") else {}
            for entries in temps.values():
                if entries:
                    temp_c = round(entries[0].current, 1)
                    break
        except Exception:
            pass

        proc_rss_mb = 0.0
        proc_vms_mb = 0.0
        proc_cpu_pct = 0.0
        proc_threads = 0
        proc_pids = []
        for proc in list(self._procs):
            try:
                with proc.oneshot():
                    mem_info = proc.memory_info()
                    proc_rss_mb += mem_info.rss / 1024 / 1024
                    proc_vms_mb += mem_info.vms / 1024 / 1024
                    proc_cpu_pct += proc.cpu_percent(interval=None)
                    proc_threads += proc.num_threads()
                    proc_pids.append(proc.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                self._procs.remove(proc)

        sample.update(
            {
                "cpu_pct": round(psutil.cpu_percent(interval=None), 2),
                "temp_c": temp_c,
                "mem_used_mb": round(mem.used / 1024 / 1024, 2),
                "mem_avail_mb": round(mem.available / 1024 / 1024, 2),
                "mem_total_mb": round(mem.total / 1024 / 1024, 2),
                "mem_pct": round(mem.percent, 2),
                "disk_pct": disk_pct,
                "disk_used_mb": disk_used_mb,
                "disk_free_mb": disk_free_mb,
                "net_tx_kbs": net_tx_kbs,
                "net_rx_kbs": net_rx_kbs,
                "disk_read_kbs": read_kb,
                "disk_write_kbs": write_kb,
                "proc_pids": proc_pids,
                "proc_rss_mb": round(proc_rss_mb, 2),
                "proc_vms_mb": round(proc_vms_mb, 2),
                "proc_cpu_pct": round(proc_cpu_pct, 2),
                "proc_threads": proc_threads,
            }
        )
        return sample

    def _refresh_procs(self, force: bool = False) -> None:
        if not HAS_PSUTIL:
            return
        if not force and self._seq == self._last_refresh_seq:
            return

        names = tuple(self.probe_cfg.get("process_names") or DEFAULT_PROCESS_NAMES)
        procs = []
        own_pid = os.getpid()
        for proc in psutil.process_iter(["pid", "cmdline"]):
            try:
                cmdline = " ".join(proc.info.get("cmdline") or [])
                if proc.info["pid"] == own_pid or any(name in cmdline for name in names):
                    procs.append(psutil.Process(proc.info["pid"]))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        self._procs = procs
        self._last_refresh_seq = self._seq
        for proc in self._procs:
            try:
                proc.cpu_percent(interval=None)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
