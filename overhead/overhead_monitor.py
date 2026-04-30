#!/usr/bin/env python3
"""
overhead_monitor.py — Micro-UXI System Overhead Monitor
=========================================================

Mengukur overhead sistem yang ditimbulkan oleh proses monitoring Micro-UXI
yang berjalan di Arduino Uno Q. Dirancang seringan mungkin: hanya psutil,
tidak ada dependensi berat, tidak ada I/O jaringan.

Metrik yang diukur (per sampel):
  CPU      — cpu_pct, cpu_pct_sensor (proses sensor), n_threads
  Memori   — rss_mb, vms_mb, mem_pct, mem_avail_mb, mem_used_mb
  Storage  — disk_pct, disk_used_mb, disk_free_mb
  Bandwidth— net_tx_kbs, net_rx_kbs
  Suhu     — temp_c (jika didukung perangkat keras)
  Disk I/O — read_kb, write_kb (delta dari sampel sebelumnya)
  Waktu    — ts (ISO Local), elapsed_sec

Mode:
  default     — cetak ringkasan tiap N detik, simpan ke output
  --verbose   — streaming tabel metrik real-time ke terminal
  --daemon    — jalankan di background, hanya simpan ke output (no stdout)

Penggunaan:
  python overhead_monitor.py
  python overhead_monitor.py --verbose
  python overhead_monitor.py --daemon --output out/overhead.jsonl
  python overhead_monitor.py --interval 5 --duration 10m --verbose
  python overhead_monitor.py --target-pid 1234  # pantau PID spesifik
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import signal
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    import psutil
except ImportError:
    sys.exit("[ERROR] psutil tidak ditemukan. Jalankan install_overhead.sh terlebih dahulu.")


# ─── Konstanta ────────────────────────────────────────────────────────────────

VERSION = "1.0.0"

# Nama proses sensor yang akan dicari secara otomatis jika --target-pid
# tidak diberikan.
SENSOR_PROCESS_NAMES = (
    "event_detector.py",
    "controller.py",
    "telemetry_probe.py",
    "fast_probe.py",
    "throughput_probe.py",
)

# ANSI
_RST = "\033[0m"
_BLD = "\033[1m"
_GRN = "\033[92m"
_YLW = "\033[93m"
_CYN = "\033[96m"
_RED = "\033[91m"
_GRY = "\033[90m"
_MAG = "\033[95m"


# ─── Helper ───────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _parse_duration(s: str) -> float | None:
    """Parse '10m', '2h', '30s' -> seconds. '0' / 'inf' -> None (infinite)."""
    s = s.strip().lower()
    if s in ("0", "inf", "forever", "indefinite"):
        return None
    if s.endswith("h"):
        return float(s[:-1]) * 3600
    if s.endswith("m"):
        return float(s[:-1]) * 60
    if s.endswith("s"):
        return float(s[:-1])
    return float(s)


def _find_sensor_pids() -> list[int]:
    """Cari PID proses sensor Micro-UXI yang sedang berjalan."""
    found = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmdline = " ".join(proc.info.get("cmdline") or [])
            for name in SENSOR_PROCESS_NAMES:
                if name in cmdline:
                    found.append(proc.info["pid"])
                    break
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return found


def _colorize_pct(val: float, warn: float = 50.0, crit: float = 80.0) -> str:
    if val >= crit:
        return f"{_RED}{val:6.1f}{_RST}"
    if val >= warn:
        return f"{_YLW}{val:6.1f}{_RST}"
    return f"{_GRN}{val:6.1f}{_RST}"


# ─── Kelas pengukur ───────────────────────────────────────────────────────────

class OverheadSampler:
    """
    Mengambil satu sampel metrik sistem + metrik proses sensor.
    Menggunakan psutil non-blocking; overhead dari sampler sendiri minimal.
    """

    def __init__(self, sensor_pids: list[int]):
        self._pids   = sensor_pids
        self._procs  = self._build_procs(sensor_pids)

        # Baseline I/O untuk delta
        self._last_io_read  = 0
        self._last_io_write = 0
        self._last_io_ts    = time.monotonic()
        try:
            io = psutil.disk_io_counters()
            if io:
                self._last_io_read  = io.read_bytes
                self._last_io_write = io.write_bytes
        except Exception:
            pass

        # Baseline Network untuk delta
        self._last_net_tx = 0
        self._last_net_rx = 0
        self._last_net_ts = time.monotonic()
        try:
            net = psutil.net_io_counters()
            if net:
                self._last_net_tx = net.bytes_sent
                self._last_net_rx = net.bytes_recv
        except Exception:
            pass

        # Inisialisasi: cpu_percent() butuh satu panggilan dummy dulu
        psutil.cpu_percent(interval=None)
        for p in self._procs:
            try:
                p.cpu_percent(interval=None)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

    @staticmethod
    def _build_procs(pids: list[int]) -> list[psutil.Process]:
        procs = []
        for pid in pids:
            try:
                procs.append(psutil.Process(pid))
            except psutil.NoSuchProcess:
                pass
        return procs

    def refresh_pids(self, pids: list[int]):
        """Perbarui daftar proses yang dipantau."""
        self._pids  = pids
        self._procs = self._build_procs(pids)

    def sample(self) -> dict:
        ts_now = _now_iso()
        mono   = time.monotonic()

        # ── CPU sistem ────────────────────────────────────────────────────────
        cpu_pct = psutil.cpu_percent(interval=None)

        # ── Memori sistem ─────────────────────────────────────────────────────
        mem = psutil.virtual_memory()
        mem_used_mb  = round(mem.used  / 1024 / 1024, 2)
        mem_avail_mb = round(mem.available / 1024 / 1024, 2)
        mem_total_mb = round(mem.total / 1024 / 1024, 2)
        mem_pct      = mem.percent

        # ── Disk I/O delta (hanya jika tersedia) ─────────────────────────────
        read_kb = write_kb = None
        try:
            io = psutil.disk_io_counters()
            if io is not None:
                dt = max(mono - self._last_io_ts, 0.001)
                read_kb  = round((io.read_bytes  - self._last_io_read)  / 1024 / dt, 2)
                write_kb = round((io.write_bytes - self._last_io_write) / 1024 / dt, 2)
                # Clamping negatif (reset counter OS)
                read_kb  = max(read_kb,  0.0)
                write_kb = max(write_kb, 0.0)
                self._last_io_read  = io.read_bytes
                self._last_io_write = io.write_bytes
                self._last_io_ts    = mono
        except (psutil.AccessDenied, AttributeError):
            pass

        # ── Storage (Disk Usage) ──────────────────────────────────────────────
        disk_pct = 0.0
        disk_used_mb = 0.0
        disk_free_mb = 0.0
        try:
            du = psutil.disk_usage('/')
            disk_pct = du.percent
            disk_used_mb = round(du.used / 1024 / 1024, 1)
            disk_free_mb = round(du.free / 1024 / 1024, 1)
        except Exception:
            pass

        # ── Bandwidth (Network I/O) ───────────────────────────────────────────
        net_tx_kbs = 0.0
        net_rx_kbs = 0.0
        try:
            net = psutil.net_io_counters()
            if net is not None:
                dt_net = max(mono - self._last_net_ts, 0.001)
                net_tx_kbs = round((net.bytes_sent - self._last_net_tx) / 1024 / dt_net, 2)
                net_rx_kbs = round((net.bytes_recv - self._last_net_rx) / 1024 / dt_net, 2)
                net_tx_kbs = max(net_tx_kbs, 0.0)
                net_rx_kbs = max(net_rx_kbs, 0.0)
                self._last_net_tx = net.bytes_sent
                self._last_net_rx = net.bytes_recv
                self._last_net_ts = mono
        except Exception:
            pass

        # ── Suhu (Temperature) ────────────────────────────────────────────────
        temp_c = None
        try:
            if hasattr(psutil, "sensors_temperatures"):
                temps = psutil.sensors_temperatures()
                if temps:
                    # Ambil nilai temperatur pertama yang tersedia (umumnya cpu_thermal atau coretemp)
                    for name, entries in temps.items():
                        if entries:
                            temp_c = round(entries[0].current, 1)
                            break
        except Exception:
            pass

        # ── Metrik proses sensor ───────────────────────────────────────────────
        proc_rss_mb   = 0.0
        proc_vms_mb   = 0.0
        proc_cpu_pct  = 0.0
        proc_threads  = 0
        proc_pids_ok  = []

        for p in list(self._procs):
            try:
                with p.oneshot():
                    mi = p.memory_info()
                    proc_rss_mb  += mi.rss / 1024 / 1024
                    proc_vms_mb  += mi.vms / 1024 / 1024
                    proc_cpu_pct += p.cpu_percent(interval=None)
                    proc_threads += p.num_threads()
                    proc_pids_ok.append(p.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                self._procs.remove(p)

        return {
            "ts":             ts_now,
            # Sistem
            "cpu_pct":        round(cpu_pct, 2),
            "temp_c":         temp_c,
            "mem_used_mb":    mem_used_mb,
            "mem_avail_mb":   mem_avail_mb,
            "mem_total_mb":   mem_total_mb,
            "mem_pct":        round(mem_pct, 2),
            "disk_pct":       round(disk_pct, 2),
            "disk_used_mb":   disk_used_mb,
            "disk_free_mb":   disk_free_mb,
            "net_tx_kbs":     net_tx_kbs,
            "net_rx_kbs":     net_rx_kbs,
            "disk_read_kbs":  read_kb,
            "disk_write_kbs": write_kb,
            # Proses sensor
            "proc_pids":      proc_pids_ok,
            "proc_rss_mb":    round(proc_rss_mb, 2),
            "proc_vms_mb":    round(proc_vms_mb, 2),
            "proc_cpu_pct":   round(proc_cpu_pct, 2),
            "proc_threads":   proc_threads,
        }


# ─── Output writer ────────────────────────────────────────────────────────────

class _OutputWriter:
    """Menulis sampel ke JSONL dan/atau CSV secara efisien (append mode)."""

    CSV_FIELDS = [
        "ts", "cpu_pct", "temp_c", "mem_used_mb", "mem_avail_mb", "mem_pct",
        "disk_pct", "disk_used_mb", "disk_free_mb", "net_tx_kbs", "net_rx_kbs",
        "disk_read_kbs", "disk_write_kbs",
        "proc_rss_mb", "proc_vms_mb", "proc_cpu_pct", "proc_threads",
    ]

    def __init__(self, jsonl_path: str | None, csv_path: str | None):
        self._jf = self._cf = self._cw = None

        if jsonl_path:
            Path(jsonl_path).parent.mkdir(parents=True, exist_ok=True)
            self._jf = open(jsonl_path, "a", encoding="utf-8", buffering=1)

        if csv_path:
            Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
            new = not Path(csv_path).exists() or Path(csv_path).stat().st_size == 0
            self._cf = open(csv_path, "a", newline="", encoding="utf-8")
            self._cw = csv.DictWriter(self._cf, fieldnames=self.CSV_FIELDS,
                                      extrasaction="ignore")
            if new:
                self._cw.writeheader()
                self._cf.flush()

    def write(self, sample: dict):
        if self._jf:
            self._jf.write(json.dumps(sample) + "\n")
        if self._cw:
            self._cw.writerow(sample)
            self._cf.flush()

    def close(self):
        for f in (self._jf, self._cf):
            if f:
                try:
                    f.close()
                except Exception:
                    pass


# ─── Printer verbose ──────────────────────────────────────────────────────────

_HDR_PRINTED = False

def _print_verbose(s: dict, seq: int):
    global _HDR_PRINTED
    if not _HDR_PRINTED or seq % 20 == 0:
        print(
            f"\n{_BLD}"
            f"{'#':>5}  {'TIME':>8}  "
            f"{'CPU%':>5}  {'MEM%':>5}  {'DSK%':>5}  "
            f"{'RX_KB/s':>8}  {'TX_KB/s':>8}  "
            f"{'RD_KB/s':>8}  {'WR_KB/s':>8}  "
            f"{'P_RSS_MB':>8}  {'P_CPU%':>6}"
            f"{_RST}"
        )
        _HDR_PRINTED = True

    t = s["ts"][11:19]  # HH:MM:SS
    rd  = f"{s['disk_read_kbs']:8.1f}"  if s["disk_read_kbs"]  is not None else f"{'N/A':>8}"
    wr  = f"{s['disk_write_kbs']:8.1f}" if s["disk_write_kbs"] is not None else f"{'N/A':>8}"
    
    rx  = f"{s['net_rx_kbs']:8.1f}"
    tx  = f"{s['net_tx_kbs']:8.1f}"

    tc = f"{s['temp_c']:4.1f}C" if s["temp_c"] is not None else " N/A"

    print(
        f"{seq:>5}  {t:>8}  "
        f"{_colorize_pct(s['cpu_pct']):>5}  "
        f"{_colorize_pct(s['mem_pct']):>5}  "
        f"{_colorize_pct(s['disk_pct']):>5}  "
        f"{_GRY}{rx}  {tx}{_RST}  "
        f"{_GRY}{rd}  {wr}{_RST}  "
        f"{_CYN}{s['proc_rss_mb']:>8.2f}  "
        f"{_colorize_pct(s['proc_cpu_pct'], 20, 50):>6}{_RST}"
    )
    sys.stdout.flush()


def _print_summary(s: dict, seq: int):
    """Cetak ringkasan satu baris (mode default, non-verbose)."""
    t = s["ts"][11:19]
    tc = f"temp={s['temp_c']}C  " if s["temp_c"] is not None else ""
    pids_str = ",".join(str(p) for p in s["proc_pids"]) or "none"
    print(
        f"[{t}] #{seq:>4}  "
        f"cpu={s['cpu_pct']:.1f}%  {tc}mem={s['mem_pct']:.1f}%  disk={s['disk_pct']:.1f}%  "
        f"net_tx={s['net_tx_kbs']:.1f}  net_rx={s['net_rx_kbs']:.1f}  "
        f"proc_rss={s['proc_rss_mb']:.1f}MB  proc_cpu={s['proc_cpu_pct']:.1f}%"
    )
    sys.stdout.flush()


# ─── Main monitor loop ────────────────────────────────────────────────────────

def _upload_overhead(url: str, device_id: str, sample: dict):
    payload = {**sample, "device_id": device_id}
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(f"{url}/api/ingest/overhead", data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=2.0) as _:
            pass
    except Exception:
        pass

def run(args):
    # ── Resolve PID target ────────────────────────────────────────────────────
    sensor_pids = []
    if args.target_pid:
        sensor_pids = [args.target_pid]
    else:
        sensor_pids = _find_sensor_pids()
        if not args.daemon and not args.quiet:
            if sensor_pids:
                print(f"[i] Proses sensor ditemukan: PID {sensor_pids}")
            else:
                print("[!] Tidak ada proses sensor terdeteksi. Hanya sistem yang dipantau.")

    sampler = OverheadSampler(sensor_pids)
    writer  = _OutputWriter(args.output, args.csv)

    duration_sec = _parse_duration(args.duration)
    t_start      = time.monotonic()
    seq          = 0

    def _cleanup(signum=None, frame=None):
        writer.close()
        elapsed = time.monotonic() - t_start
        if not args.daemon and not args.quiet:
            print(f"\n[i] Selesai. {seq} sampel dalam {elapsed:.1f}s.")
        sys.exit(0)

    signal.signal(signal.SIGTERM, _cleanup)
    signal.signal(signal.SIGINT,  _cleanup)

    if not args.daemon and not args.quiet:
        dur_label = f"{args.duration}" if args.duration != "0" else "tidak terbatas"
        print(
            f"{'='*60}\n"
            f"  Micro-UXI Overhead Monitor v{VERSION}\n"
            f"  Interval : {args.interval}s  |  Durasi: {dur_label}\n"
            f"  Output   : {args.output or '-'}  CSV: {args.csv or '-'}\n"
            f"  Verbose  : {'ya' if args.verbose else 'tidak'}\n"
            f"{'='*60}"
        )

    try:
        while True:
            t0 = time.monotonic()

            # Re-cari PID sensor setiap 30 sampel (supaya bisa detect proses
            # yang baru start setelah monitor jalan), tapi hanya jika user
            # tidak memberikan --target-pid secara eksplisit.
            if not args.target_pid and seq % 30 == 0:
                new_pids = _find_sensor_pids()
                if new_pids != sampler._pids:
                    sampler.refresh_pids(new_pids)

            sample = sampler.sample()
            seq   += 1

            writer.write(sample)
            
            if args.server_url:
                import threading
                threading.Thread(
                    target=_upload_overhead, 
                    args=(args.server_url.rstrip('/'), args.device_id, sample), 
                    daemon=True
                ).start()

            if not args.daemon:
                if args.verbose:
                    _print_verbose(sample, seq)
                elif not args.quiet:
                    _print_summary(sample, seq)

            # ── Cek durasi ────────────────────────────────────────────────────
            if duration_sec is not None:
                if (time.monotonic() - t_start) >= duration_sec:
                    break

            # ── Sleep sisa interval ───────────────────────────────────────────
            elapsed = time.monotonic() - t0
            remaining = args.interval - elapsed
            if remaining > 0:
                time.sleep(remaining)

    except KeyboardInterrupt:
        pass
    finally:
        _cleanup()


# ─── Daemon helper ────────────────────────────────────────────────────────────

def daemonize(pidfile: str | None):
    """Fork proses menjadi daemon UNIX (double-fork)."""
    if os.fork() > 0:
        sys.exit(0)
    os.setsid()
    if os.fork() > 0:
        sys.exit(0)

    # Redirect stdin/stdout/stderr ke /dev/null
    devnull = os.open(os.devnull, os.O_RDWR)
    for fd in (sys.stdin.fileno(), sys.stdout.fileno(), sys.stderr.fileno()):
        os.dup2(devnull, fd)

    if pidfile:
        Path(pidfile).parent.mkdir(parents=True, exist_ok=True)
        Path(pidfile).write_text(str(os.getpid()))


# ─── Entry point ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="overhead_monitor.py",
        description="Micro-UXI Overhead Monitor — mengukur beban sistem di Arduino Uno Q.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Contoh:
  # Pantau normal, cetak ringkasan tiap 2 detik:
  python overhead_monitor.py

  # Mode verbose (tabel streaming):
  python overhead_monitor.py --verbose

  # Simpan JSONL + CSV, jalankan 10 menit:
  python overhead_monitor.py --output out/overhead.jsonl --csv out/overhead.csv --duration 10m

  # Daemon background, simpan ke file:
  python overhead_monitor.py --daemon --output out/overhead.jsonl --pidfile /tmp/overhead.pid

  # Pantau PID spesifik dengan interval 5 detik selama 1 jam:
  python overhead_monitor.py --target-pid 1234 --interval 5 --duration 1h --verbose
""",
    )

    parser.add_argument(
        "--interval", type=float, default=2.0, metavar="SEC",
        help="Interval antar sampel dalam detik (default: 2)",
    )
    parser.add_argument(
        "--duration", default="0", metavar="DUR",
        help="Durasi pengambilan data: '10m', '1h', '30s', '0'=tidak terbatas (default: 0)",
    )
    parser.add_argument(
        "--output", default=None, metavar="PATH",
        help="Path file output JSONL (default: tidak disimpan)",
    )
    parser.add_argument(
        "--csv", default=None, metavar="PATH",
        help="Path file output CSV (default: tidak disimpan)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Tampilkan tabel metrik streaming di terminal",
    )
    parser.add_argument(
        "--quiet", "-q", action="store_true",
        help="Tidak cetak apapun ke stdout (berguna jika hanya butuh file output)",
    )
    parser.add_argument(
        "--daemon", "-d", action="store_true",
        help="Jalankan sebagai daemon background (implies --quiet)",
    )
    parser.add_argument(
        "--pidfile", default=None, metavar="PATH",
        help="Simpan PID daemon ke file ini (hanya berlaku dengan --daemon)",
    )
    parser.add_argument(
        "--target-pid", type=int, default=None, metavar="PID",
        help="Pantau proses dengan PID tertentu (default: auto-deteksi proses sensor)",
    )
    parser.add_argument(
        "--server-url", default=None, metavar="URL",
        help="URL server untuk upload data (contoh: http://127.0.0.1:5000)",
    )
    parser.add_argument(
        "--device-id", default="uno-q-01", metavar="ID",
        help="Device ID untuk upload (default: uno-q-01)",
    )

    args = parser.parse_args()

    # Validasi
    if args.daemon and args.verbose:
        parser.error("--daemon dan --verbose tidak bisa dipakai bersamaan.")
    if args.daemon and not args.output and not args.csv:
        parser.error("--daemon membutuhkan minimal satu --output atau --csv.")

    if args.daemon:
        daemonize(args.pidfile)

    run(args)


if __name__ == "__main__":
    main()
