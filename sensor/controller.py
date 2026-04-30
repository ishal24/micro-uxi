#!/usr/bin/env python3
"""
Micro-UXI Monitoring Controller — threaded, multi-rate sampler.

Three independent threads run concurrently:
  fast_probe    1–2 Hz   Catches burst events (S2 DNS Burst, S3 Loss Burst, S6 Flap)
  telemetry     30 s     Full Wi-Fi / ping / DNS / HTTP snapshot (S1, S4)
  throughput    300 s    Download bandwidth test (S5)

Output formats: jsonl (default), csv, json
Duration:       --duration 15m | 1h | 3600 | 0 (indefinite)
"""

import csv
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone

from fast_probe import FastProbe
from telemetry_probe import TelemetryProbe
from throughput_probe import ThroughputProbe
from uploader import Uploader


# ---------------------------------------------------------------------------
# Duration parser
# ---------------------------------------------------------------------------

def parse_duration(s: str):
    """
    Parse a duration string → seconds (float), or None for indefinite.
      "0" | "inf" | "indefinite"  →  None
      "15m"  →  900.0
      "1h"   →  3600.0
      "30s"  →  30.0
      "900"  →  900.0
    """
    s = s.strip().lower()
    if s in ("0", "inf", "indefinite", "forever"):
        return None
    if s.endswith("h"):
        return float(s[:-1]) * 3600
    if s.endswith("m"):
        return float(s[:-1]) * 60
    if s.endswith("s"):
        return float(s[:-1])
    return float(s)


# ---------------------------------------------------------------------------
# CSV flatteners
# ---------------------------------------------------------------------------

def flatten_fast(result: dict) -> dict:
    row = {
        "ts":               result.get("ts"),
        "seq":              result.get("seq"),
        "device_id":        result.get("device_id"),
        "wifi_up":          result.get("wifi_up"),
        "connectivity_ok":  result.get("connectivity_ok"),
        "ping_target":      result.get("ping", {}).get("target"),
        "ping_success":     result.get("ping", {}).get("success"),
        "ping_rtt_ms":      result.get("ping", {}).get("rtt_ms"),
    }
    for entry in result.get("dns") or []:
        slug = (entry.get("domain") or "").replace(".", "_")
        row[f"dns_{slug}_success"]    = entry.get("success")
        row[f"dns_{slug}_latency_ms"] = entry.get("latency_ms")
    return row


def flatten_telemetry(result: dict) -> dict:
    row = {
        "collected_at_utc": result.get("collected_at_utc"),
        "device_id":        result.get("device_id"),
        "site_name":        result.get("site_name"),
        "iface":            result.get("iface"),
    }
    t = result.get("telemetry") or {}

    wifi = t.get("wifi") or {}
    for k in ["wifi_connected", "wifi_ssid", "wifi_bssid",
              "wifi_rssi_dbm", "wifi_bitrate_mbps", "wifi_freq_mhz"]:
        row[k] = wifi.get(k)

    net = t.get("network") or {}
    row["ip_address"]    = net.get("ip_address")
    row["gateway_ip"]    = net.get("gateway_ip")
    row["dns_resolvers"] = ",".join(net.get("dns_resolvers") or [])

    ping = t.get("ping") or {}
    for k in ["ping_target", "loss_pct",
              "rtt_min_ms", "rtt_avg_ms", "rtt_max_ms", "rtt_mdev_ms"]:
        row[k] = ping.get(k)

    for entry in t.get("dns") or []:
        domain   = (entry.get("domain") or "").replace(".", "_")
        resolver = (entry.get("resolver") or "system").replace(".", "_")
        pfx = f"dns_{domain}_{resolver}"
        row[f"{pfx}_latency_ms"] = entry.get("dns_latency_ms")
        row[f"{pfx}_success"]    = entry.get("dns_success")
        row[f"{pfx}_status"]     = entry.get("status_text")

    for entry in t.get("http") or []:
        url  = entry.get("http_url") or ""
        slug = (url.replace("https://", "").replace("http://", "")
                   .replace("/", "_").replace(".", "_"))[:30]
        pfx = f"http_{slug}"
        for k in ["http_status", "http_dns_ms", "http_connect_ms",
                  "http_tls_ms", "http_ttfb_ms", "http_total_ms",
                  "http_download_bytes", "curl_rc"]:
            row[f"{pfx}_{k.replace('http_', '')}"] = entry.get(k)

    return row


def flatten_throughput(result: dict) -> dict:
    cfg = result.get("config_used") or {}
    row = {
        "collected_at_utc": result.get("collected_at_utc"),
        "device_id":        result.get("device_id"),
        "site_name":        result.get("site_name"),
        "iface":            result.get("iface"),
        "mode":             result.get("mode"),
        "url":              cfg.get("url"),
        "runs":             cfg.get("runs"),
    }
    summary = result.get("summary") or {}
    for metric in ["throughput_total_mbps", "throughput_transfer_mbps",
                   "http_total_ms", "http_ttfb_ms", "http_dns_ms",
                   "http_download_bytes", "transfer_only_ms"]:
        m = summary.get(metric)
        for stat in ["avg", "median", "p95", "min", "max"]:
            row[f"{metric}_{stat}"] = m.get(stat) if isinstance(m, dict) else None
    rh = summary.get("run_health") or {}
    row["run_health_total"]        = rh.get("total_runs")
    row["run_health_successful"]   = rh.get("successful_http_runs")
    row["run_health_failed"]       = rh.get("failed_runs")
    row["download_complete_true"]  = rh.get("download_complete_true")
    row["download_complete_false"] = rh.get("download_complete_false")
    return row


# ---------------------------------------------------------------------------
# CSV writer — append-safe, auto-header
# ---------------------------------------------------------------------------

class CsvWriter:
    def __init__(self, path: str):
        self.path = path
        self._header_written = os.path.exists(path) and os.path.getsize(path) > 0

    def write(self, row: dict):
        write_header = not self._header_written
        with open(self.path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(row.keys()), extrasaction="ignore")
            if write_header:
                w.writeheader()
                self._header_written = True
            w.writerow(row)


# ---------------------------------------------------------------------------
# Main controller
# ---------------------------------------------------------------------------

class MonitorController:

    def __init__(self, config: dict, output_format: str = "jsonl"):
        self.config        = config
        self.output_format = output_format.lower()

        out = config.get("output") or {}
        self.output_dir   = out.get("output_dir", "./out")
        self.save_output  = out.get("save_output", True)
        self.print_pretty = out.get("print_pretty", False)

        os.makedirs(self.output_dir, exist_ok=True)

        sched = config.get("scheduler") or {}
        self.telemetry_interval  = sched.get("telemetry_interval_sec", 30)
        self.throughput_interval = sched.get("throughput_interval_sec", 300)
        fp = config.get("fast_probe") or {}
        self.fast_interval       = fp.get("interval_sec", 2)
        self.fast_enabled        = fp.get("enabled", True)

        # Unique session ID — stamps all files from this run
        self.session_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        # Threading
        self._stop       = threading.Event()
        self._print_lock = threading.Lock()
        
        self.uploader = Uploader(config)

        # Per-type lazy CSV writers
        self._csv: dict[str, CsvWriter] = {}

        # Counters (int += is atomic in CPython under the GIL)
        self.fast_count        = 0
        self.fast_errors       = 0
        self.fast_anomalies    = 0
        self.tel_count         = 0
        self.tel_errors        = 0
        self.thr_count         = 0
        self.thr_errors        = 0

    # ------------------------------------------------------------------
    # Thread-safe helpers
    # ------------------------------------------------------------------

    def _print(self, msg: str):
        with self._print_lock:
            print(msg, flush=True)

    def _output_path(self, prefix: str, ext: str) -> str:
        return os.path.join(self.output_dir, f"{prefix}_{self.session_id}.{ext}")

    def _csv_writer(self, prefix: str) -> CsvWriter:
        if prefix not in self._csv:
            self._csv[prefix] = CsvWriter(self._output_path(prefix, "csv"))
        return self._csv[prefix]

    # ------------------------------------------------------------------
    # Save dispatcher — each prefix writes to its own file
    # ------------------------------------------------------------------

    def _save(self, prefix: str, result: dict):
        self.uploader.push_sensor(result)
        if not self.save_output:
            return

        fmt = self.output_format

        if fmt == "json":
            ts   = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            path = os.path.join(self.output_dir, f"{prefix}_{ts}.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2)

        elif fmt == "jsonl":
            path = self._output_path(prefix, "jsonl")
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(result, separators=(",", ":")) + "\n")

        elif fmt == "csv":
            flatteners = {
                "fast":       flatten_fast,
                "telemetry":  flatten_telemetry,
                "throughput": flatten_throughput,
            }
            fn = flatteners.get(prefix)
            if fn:
                self._csv_writer(prefix).write(fn(result))

    # ------------------------------------------------------------------
    # Status line formatters
    # ------------------------------------------------------------------

    @staticmethod
    def _fmt(val, fmt_str, fallback="--"):
        try:
            return fmt_str.format(val) if val is not None else fallback
        except Exception:
            return fallback

    def _fast_anomaly_line(self, result: dict) -> str:
        """Compact anomaly line — only printed when something is wrong."""
        ts   = result.get("ts", "?")[-15:-7]   # HH:MM:SS portion
        seq  = result.get("seq", "?")
        wifi = "UP" if result.get("wifi_up") else "DOWN"

        ping     = result.get("ping") or {}
        ping_str = f"rtt={self._fmt(ping.get('rtt_ms'), '{:.1f}ms')}" \
                   if ping.get("success") else "FAIL"

        dns_parts = []
        for d in result.get("dns") or []:
            ok  = d.get("success")
            dom = d.get("domain", "?")
            dns_parts.append(f"{dom}={'OK' if ok else 'FAIL'}")
        dns_str = "  ".join(dns_parts)

        return (f"[FAST ⚠ #{seq:>5}] {ts}  wifi={wifi}  ping={ping_str}  dns={dns_str}")

    def _tel_line(self, result: dict) -> str:
        t    = result.get("telemetry") or {}
        wifi = t.get("wifi") or {}
        ping = t.get("ping") or {}
        ts   = (result.get("collected_at_utc") or "?")[-15:-7]

        connected = wifi.get("wifi_connected")
        rssi      = wifi.get("wifi_rssi_dbm")
        rtt_avg   = ping.get("rtt_avg_ms")
        loss      = ping.get("loss_pct")

        # DNS failures summary
        dns_fails = [d.get("domain") for d in (t.get("dns") or [])
                     if not d.get("dns_success")]
        dns_str = f"  dns_fail={','.join(dns_fails)}" if dns_fails else ""

        # Fast probe anomaly count since last telemetry line (reset it)
        fa = self.fast_anomalies
        fa_str  = f"  [{fa} fast anomalies]" if fa > 0 else ""

        return (
            f"[TEL #{self.tel_count:>4}] {ts}"
            f"  wifi={'UP  ' if connected else 'DOWN'}"
            f"  rssi={self._fmt(rssi, '{:>4}dBm')}"
            f"  rtt={self._fmt(rtt_avg, '{:>7.2f}ms')}"
            f"  loss={self._fmt(loss, '{:>5.1f}%')}"
            f"{dns_str}{fa_str}"
        )

    def _thr_line(self, result: dict) -> str:
        ts   = (result.get("collected_at_utc") or "?")[-15:-7]
        summ = result.get("summary") or {}
        tp   = summ.get("throughput_total_mbps")
        rh   = summ.get("run_health") or {}

        tp_avg = tp.get("avg") if isinstance(tp, dict) else None
        tp_p95 = tp.get("p95") if isinstance(tp, dict) else None
        ok     = rh.get("successful_http_runs", 0)
        total  = rh.get("total_runs", 0)

        status = "FAIL" if ok == 0 else ("PARTIAL" if ok < total else "OK")

        return (
            f"[THR #{self.thr_count:>4}] {ts}"
            f"  avg={self._fmt(tp_avg, '{:>7.3f}Mbps')}"
            f"  p95={self._fmt(tp_p95, '{:>7.3f}Mbps')}"
            f"  runs={ok}/{total} [{status}]"
        )

    # ------------------------------------------------------------------
    # Worker threads
    # ------------------------------------------------------------------

    def _fast_worker(self):
        """1–2 Hz fast probe — runs in its own thread."""
        probe = FastProbe(self.config)
        while not self._stop.is_set():
            t0 = time.monotonic()
            try:
                result = probe.collect()
                self._save("fast", result)
                self.fast_count += 1

                # Only print when something is wrong
                anomaly = (
                    not result.get("connectivity_ok")
                    or not result.get("ping", {}).get("success")
                    or not result.get("wifi_up")
                    or any(not d.get("success") for d in result.get("dns") or [])
                )
                if anomaly:
                    self.fast_anomalies += 1
                    self._print(self._fast_anomaly_line(result))

            except Exception as e:
                self.fast_errors += 1
                self._print(f"[FAST ERROR] {e}")

            elapsed = time.monotonic() - t0
            self._stop.wait(max(0, self.fast_interval - elapsed))

    def _telemetry_worker(self):
        """30s full telemetry — runs in its own thread."""
        while not self._stop.is_set():
            t0 = time.monotonic()
            try:
                result = TelemetryProbe(self.config).collect()
                self._save("telemetry", result)
                self.tel_count += 1
                self._print(self._tel_line(result))

            except Exception as e:
                self.tel_errors += 1
                self._print(f"[TEL ERROR] {e}")

            elapsed = time.monotonic() - t0
            self._stop.wait(max(0, self.telemetry_interval - elapsed))

    def _throughput_worker(self):
        """Throughput probe — starts after one full interval to avoid startup congestion."""
        # Stagger first run so it doesn't overlap with telemetry startup
        self._stop.wait(self.throughput_interval)
        while not self._stop.is_set():
            t0 = time.monotonic()
            try:
                result = ThroughputProbe(self.config).collect()
                self._save("throughput", result)
                self.thr_count += 1
                self._print(self._thr_line(result))

            except Exception as e:
                self.thr_errors += 1
                self._print(f"[THR ERROR] {e}")

            elapsed = time.monotonic() - t0
            self._stop.wait(max(0, self.throughput_interval - elapsed))

    def _config_worker(self):
        """Polls server for configuration updates."""
        srv = self.config.get("server", {})
        poll_interval = srv.get("config_poll_interval_sec", 30)
        device_id = self.config.get("device", {}).get("device_id", "unknown")
        
        # Initial wait to stagger
        self._stop.wait(5.0)
        
        while not self._stop.is_set():
            t0 = time.monotonic()
            try:
                data = self.uploader.get_config(device_id)
                if data and data.get("config"):
                    new_cfg = data["config"]
                    # Apply simple live updates
                    if "scheduler" in new_cfg:
                        self.telemetry_interval = new_cfg["scheduler"].get("telemetry_interval_sec", self.telemetry_interval)
                    if "fast_probe" in new_cfg:
                        self.fast_enabled = new_cfg["fast_probe"].get("enabled", self.fast_enabled)
            except Exception as e:
                pass
                
            elapsed = time.monotonic() - t0
            self._stop.wait(max(0, poll_interval - elapsed))

    # ------------------------------------------------------------------
    # Single-shot runners (for --mode once-*)
    # ------------------------------------------------------------------

    def run_telemetry_once(self):
        try:
            result = TelemetryProbe(self.config).collect()
            self._save("telemetry", result)
            self.tel_count += 1
            if self.print_pretty:
                print(json.dumps(result, indent=2))
            else:
                self._print(self._tel_line(result))
            return result
        except Exception as e:
            self._print(f"[TEL ERROR] {e}")
            return {}

    def run_throughput_once(self):
        try:
            result = ThroughputProbe(self.config).collect()
            self._save("throughput", result)
            self.thr_count += 1
            if self.print_pretty:
                print(json.dumps(result, indent=2))
            else:
                self._print(self._thr_line(result))
            return result
        except Exception as e:
            self._print(f"[THR ERROR] {e}")
            return {}

    def run_fast_once(self):
        try:
            probe  = FastProbe(self.config)
            result = probe.collect()
            self._save("fast", result)
            self.fast_count += 1
            if self.print_pretty:
                print(json.dumps(result, indent=2))
            else:
                self._print(self._fast_anomaly_line(result))
            return result
        except Exception as e:
            self._print(f"[FAST ERROR] {e}")
            return {}

    # ------------------------------------------------------------------
    # Main loop — launches all three threads
    # ------------------------------------------------------------------

    def loop(self, duration_sec: float | None = None):
        start_time = time.monotonic()
        end_time   = (start_time + duration_sec) if duration_sec else None

        throughput_enabled = self.config.get("modules", {}).get("throughput", False)
        dur_label = (f"{duration_sec:.0f}s ({duration_sec / 60:.1f} min)"
                     if duration_sec else "indefinite  (Ctrl+C to stop)")

        print("=" * 66)
        print("  Micro-UXI Monitoring Controller  —  threaded multi-rate")
        print("=" * 66)
        print(f"  Device      : {self.config['device']['device_id']}"
              f"  @  {self.config['device'].get('site_name', '?')}")
        print(f"  Interface   : {self.config['device']['iface']}")
        if self.fast_enabled:
            print(f"  Fast probe  : every {self.fast_interval}s"
                  f"  (ping + DNS — catches S2/S3/S6 bursts)")
        print(f"  Telemetry   : every {self.telemetry_interval}s"
              f"  (full snapshot — S1/S4)")
        if throughput_enabled:
            print(f"  Throughput  : every {self.throughput_interval}s"
                  f"  (download — S5)")
        else:
            print(f"  Throughput  : disabled")
        print(f"  Duration    : {dur_label}")
        print(f"  Format      : {self.output_format.upper()}")
        print(f"  Output dir  : {os.path.abspath(self.output_dir)}")
        print(f"  Session ID  : {self.session_id}")
        print("=" * 66)
        print("  Fast probe prints only on anomaly. Telemetry every 30s.")
        print("=" * 66)

        # Build and start threads
        threads = []
        if self.fast_enabled:
            threads.append(threading.Thread(
                target=self._fast_worker, daemon=True, name="fast"))
        threads.append(threading.Thread(
            target=self._telemetry_worker, daemon=True, name="telemetry"))
        if throughput_enabled:
            threads.append(threading.Thread(
                target=self._throughput_worker, daemon=True, name="throughput"))
                
        if self.uploader.enabled:
            threads.append(threading.Thread(
                target=self._config_worker, daemon=True, name="config"))

        for t in threads:
            t.start()

        # Main thread just waits for duration or Ctrl+C
        try:
            if end_time:
                remaining = end_time - time.monotonic()
                while remaining > 0 and not self._stop.is_set():
                    self._stop.wait(timeout=min(remaining, 1.0))
                    remaining = end_time - time.monotonic()
                self._print(f"\n[i] Target duration reached.")
            else:
                self._stop.wait()  # waits until set or KeyboardInterrupt
        except KeyboardInterrupt:
            self._print("\n[!] Stopped by user (Ctrl+C).")

        self._stop.set()
        self.uploader.stop()
        for t in threads:
            t.join(timeout=10)

        elapsed = time.monotonic() - start_time
        print("=" * 66)
        print(f"  Session complete.")
        print(f"  Elapsed     : {elapsed:.1f}s  ({elapsed / 60:.1f} min)")
        if self.fast_enabled:
            print(f"  Fast probe  : {self.fast_count} samples"
                  + (f"  |  {self.fast_anomalies} anomalies" if self.fast_anomalies else "  |  no anomalies")
                  + (f"  |  {self.fast_errors} errors" if self.fast_errors else ""))
        print(f"  Telemetry   : {self.tel_count} samples"
              + (f"  |  {self.tel_errors} errors" if self.tel_errors else ""))
        if throughput_enabled:
            print(f"  Throughput  : {self.thr_count} samples"
                  + (f"  |  {self.thr_errors} errors" if self.thr_errors else ""))
        if self.save_output:
            print(f"  Output      : {os.path.abspath(self.output_dir)}")
        print("=" * 66)


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------

def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Micro-UXI monitoring controller",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Duration (--duration):
  0 / inf / indefinite   Run forever until Ctrl+C  (default)
  15m / 1h / 30s / 900   Parsed naturally

Output format (--format):
  jsonl   One growing file per probe type per session  (default)
  csv     Flat rows per sample — easy for pandas / Excel
  json    One file per sample — avoid for long runs

Modes (--mode):
  loop             Start all threads (default)
  once-telemetry   Single telemetry sample and exit
  once-throughput  Single throughput sample and exit
  once-fast        Single fast probe sample and exit
""",
    )
    parser.add_argument("--config",  default="config.json")
    parser.add_argument("--mode",
                        choices=["loop", "once-telemetry", "once-throughput", "once-fast"],
                        default="loop")
    parser.add_argument("--duration", default="0", metavar="DURATION")
    parser.add_argument("--format",   choices=["jsonl", "csv", "json"], default=None)
    parser.add_argument("--verbose",  action="store_true",
                        help="Print full JSON for every sample")
    parser.add_argument("--no-fast",  action="store_true",
                        help="Disable the fast probe thread")
    args = parser.parse_args()

    config = load_config(args.config)

    if args.verbose:
        config.setdefault("output", {})["print_pretty"] = True

    if args.no_fast:
        config.setdefault("fast_probe", {})["enabled"] = False

    out = config.get("output") or {}
    fmt = args.format or out.get("format", "jsonl")

    controller = MonitorController(config, output_format=fmt)

    if args.mode == "once-telemetry":
        controller.run_telemetry_once()
    elif args.mode == "once-throughput":
        controller.run_throughput_once()
    elif args.mode == "once-fast":
        controller.run_fast_once()
    else:
        controller.loop(duration_sec=parse_duration(args.duration))


if __name__ == "__main__":
    main()