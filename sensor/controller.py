#!/usr/bin/env python3
"""
Micro-UXI Monitoring Controller
Runs telemetry and throughput probes on a configurable schedule.
Supports timed runs (e.g. 15m, 1h) and three output formats (json, jsonl, csv).
"""

import csv
import json
import os
import sys
import time
from datetime import datetime, timezone

from telemetry_probe import TelemetryProbe
from throughput_probe import ThroughputProbe


# ---------------------------------------------------------------------------
# Duration parser
# ---------------------------------------------------------------------------

def parse_duration(s: str):
    """
    Parse a human-readable duration string into seconds (float).
    Returns None for indefinite mode.

    Examples:
        "0"          -> None  (run forever)
        "inf"        -> None
        "indefinite" -> None
        "900"        -> 900.0
        "15m"        -> 900.0
        "1h"         -> 3600.0
        "30s"        -> 30.0
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
# Output helpers: flatten nested probe results into flat dicts for CSV
# ---------------------------------------------------------------------------

def flatten_telemetry(result: dict) -> dict:
    """Flatten a telemetry JSON result into a single-level dict for CSV rows."""
    row = {
        "collected_at_utc": result.get("collected_at_utc"),
        "device_id":        result.get("device_id"),
        "site_name":        result.get("site_name"),
        "iface":            result.get("iface"),
    }
    t = result.get("telemetry", {})

    # Wi-Fi
    wifi = t.get("wifi") or {}
    for k in ["wifi_connected", "wifi_ssid", "wifi_bssid",
              "wifi_rssi_dbm", "wifi_bitrate_mbps", "wifi_freq_mhz"]:
        row[k] = wifi.get(k)

    # Network
    net = t.get("network") or {}
    row["ip_address"]    = net.get("ip_address")
    row["gateway_ip"]    = net.get("gateway_ip")
    row["dns_resolvers"] = ",".join(net.get("dns_resolvers") or [])

    # Ping
    ping = t.get("ping") or {}
    for k in ["ping_target", "loss_pct",
              "rtt_min_ms", "rtt_avg_ms", "rtt_max_ms", "rtt_mdev_ms"]:
        row[k] = ping.get(k)

    # DNS — one column set per (domain, resolver) pair
    for entry in t.get("dns") or []:
        domain   = (entry.get("domain") or "unknown").replace(".", "_")
        resolver = (entry.get("resolver") or "system").replace(".", "_")
        pfx = f"dns_{domain}_{resolver}"
        row[f"{pfx}_latency_ms"] = entry.get("dns_latency_ms")
        row[f"{pfx}_success"]    = entry.get("dns_success")
        row[f"{pfx}_status"]     = entry.get("status_text")

    # HTTP — one column set per target URL
    for entry in t.get("http") or []:
        url  = entry.get("http_url") or "unknown"
        slug = (url.replace("https://", "")
                   .replace("http://", "")
                   .replace("/", "_")
                   .replace(".", "_"))[:30]
        pfx = f"http_{slug}"
        for k in ["http_status", "http_dns_ms", "http_connect_ms",
                  "http_tls_ms", "http_ttfb_ms", "http_total_ms",
                  "http_download_bytes", "curl_rc"]:
            row[f"{pfx}_{k.replace('http_', '')}"] = entry.get(k)

    return row


def flatten_throughput(result: dict) -> dict:
    """Flatten throughput summary into a single-level dict for CSV rows."""
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
    stat_metrics = [
        "throughput_total_mbps", "throughput_transfer_mbps",
        "http_total_ms", "http_ttfb_ms", "http_dns_ms",
        "http_download_bytes", "transfer_only_ms",
    ]
    for metric in stat_metrics:
        m = summary.get(metric)
        if isinstance(m, dict):
            for stat in ["avg", "median", "p95", "min", "max"]:
                row[f"{metric}_{stat}"] = m.get(stat)
        else:
            for stat in ["avg", "median", "p95", "min", "max"]:
                row[f"{metric}_{stat}"] = None

    rh = summary.get("run_health") or {}
    row["run_health_total"]         = rh.get("total_runs")
    row["run_health_successful"]    = rh.get("successful_http_runs")
    row["run_health_failed"]        = rh.get("failed_runs")
    row["download_complete_true"]   = rh.get("download_complete_true")
    row["download_complete_false"]  = rh.get("download_complete_false")
    return row


# ---------------------------------------------------------------------------
# CSV writer — append-friendly, writes header on first row only
# ---------------------------------------------------------------------------

class CsvWriter:
    def __init__(self, path: str):
        self.path = path
        # If the file already exists and is non-empty, assume header is present
        self._header_written = os.path.exists(path) and os.path.getsize(path) > 0

    def write(self, row: dict):
        write_header = not self._header_written
        with open(self.path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(row.keys()),
                                    extrasaction="ignore")
            if write_header:
                writer.writeheader()
                self._header_written = True
            writer.writerow(row)


# ---------------------------------------------------------------------------
# Main controller
# ---------------------------------------------------------------------------

class MonitorController:
    def __init__(self, config: dict, output_format: str = "jsonl"):
        self.config = config
        self.output_format = output_format.lower()

        output_cfg = config.get("output") or {}
        self.output_dir   = output_cfg.get("output_dir", "./out")
        self.save_output  = output_cfg.get("save_output", True)
        self.print_pretty = output_cfg.get("print_pretty", False)

        os.makedirs(self.output_dir, exist_ok=True)

        sched = config.get("scheduler") or {}
        self.telemetry_interval  = sched.get("telemetry_interval_sec", 30)
        self.throughput_interval = sched.get("throughput_interval_sec", 300)
        self.loop_sleep          = sched.get("loop_sleep_sec", 1)

        self.last_telemetry_ts  = 0
        self.last_throughput_ts = 0

        # Unique session ID stamps all output files from this run
        self.session_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        # Lazy-initialised file writers
        self._tel_jsonl_path = None
        self._thr_jsonl_path = None
        self._tel_csv: CsvWriter | None = None
        self._thr_csv: CsvWriter | None = None

        # Run counters (for display and final summary)
        self.tel_count = 0
        self.thr_count = 0
        self.tel_errors = 0
        self.thr_errors = 0

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _now_utc_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _tel_jsonl(self) -> str:
        if self._tel_jsonl_path is None:
            self._tel_jsonl_path = os.path.join(
                self.output_dir, f"telemetry_{self.session_id}.jsonl")
        return self._tel_jsonl_path

    def _thr_jsonl(self) -> str:
        if self._thr_jsonl_path is None:
            self._thr_jsonl_path = os.path.join(
                self.output_dir, f"throughput_{self.session_id}.jsonl")
        return self._thr_jsonl_path

    def _tel_csv_writer(self) -> CsvWriter:
        if self._tel_csv is None:
            path = os.path.join(
                self.output_dir, f"telemetry_{self.session_id}.csv")
            self._tel_csv = CsvWriter(path)
        return self._tel_csv

    def _thr_csv_writer(self) -> CsvWriter:
        if self._thr_csv is None:
            path = os.path.join(
                self.output_dir, f"throughput_{self.session_id}.csv")
            self._thr_csv = CsvWriter(path)
        return self._thr_csv

    # ------------------------------------------------------------------
    # Save result in the configured format
    # ------------------------------------------------------------------

    def _save(self, prefix: str, result: dict) -> str | None:
        """Persist a probe result. Returns the file path written, or None."""
        if not self.save_output:
            return None

        fmt = self.output_format

        if fmt == "json":
            ts   = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            path = os.path.join(self.output_dir, f"{prefix}_{ts}.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2)
            return path

        if fmt == "jsonl":
            path = self._tel_jsonl() if prefix == "telemetry" else self._thr_jsonl()
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(result, separators=(",", ":")) + "\n")
            return path

        if fmt == "csv":
            if prefix == "telemetry":
                row = flatten_telemetry(result)
                w   = self._tel_csv_writer()
            else:
                row = flatten_throughput(result)
                w   = self._thr_csv_writer()
            w.write(row)
            return w.path

        return None

    # ------------------------------------------------------------------
    # Compact one-liner status line (used when print_pretty is False)
    # ------------------------------------------------------------------

    def _tel_status_line(self, result: dict, n: int) -> str:
        t    = result.get("telemetry") or {}
        wifi = t.get("wifi") or {}
        ping = t.get("ping") or {}

        ts        = result.get("collected_at_utc", "?")
        connected = wifi.get("wifi_connected")
        rssi      = wifi.get("wifi_rssi_dbm")
        rtt_avg   = ping.get("rtt_avg_ms")
        loss      = ping.get("loss_pct")

        wifi_str = "UP  " if connected else ("DOWN" if connected is False else "??? ")
        rssi_str = f"{rssi:>4} dBm" if rssi is not None else "  -- dBm"
        rtt_str  = f"{rtt_avg:>7.2f} ms" if rtt_avg is not None else "    --   ms"
        loss_str = f"{loss:>5.1f}%" if loss is not None else "   --% "

        return (f"[TEL #{n:>4}] {ts}  "
                f"wifi={wifi_str}  rssi={rssi_str}  "
                f"rtt={rtt_str}  loss={loss_str}")

    def _thr_status_line(self, result: dict, n: int) -> str:
        ts   = result.get("collected_at_utc", "?")
        summ = result.get("summary") or {}
        tp   = summ.get("throughput_total_mbps")
        rh   = summ.get("run_health") or {}

        tp_avg = tp.get("avg") if isinstance(tp, dict) else None
        tp_p95 = tp.get("p95") if isinstance(tp, dict) else None
        ok     = rh.get("successful_http_runs")
        total  = rh.get("total_runs")

        tp_avg_str = f"{tp_avg:>7.3f} Mbps" if tp_avg is not None else "    --    Mbps"
        tp_p95_str = f"{tp_p95:>7.3f} Mbps" if tp_p95 is not None else "    --    Mbps"

        return (f"[THR #{n:>4}] {ts}  "
                f"avg={tp_avg_str}  p95={tp_p95_str}  "
                f"success={ok}/{total}")

    # ------------------------------------------------------------------
    # Single probe runs
    # ------------------------------------------------------------------

    def run_telemetry_once(self) -> dict:
        try:
            probe  = TelemetryProbe(self.config)
            result = probe.collect()
        except Exception as e:
            self.tel_errors += 1
            print(f"[TEL ERROR] {e}", file=sys.stderr)
            return {}

        path = self._save("telemetry", result)
        self.tel_count += 1

        if self.print_pretty:
            print(f"\n=== TELEMETRY #{self.tel_count} ===")
            print(json.dumps(result, indent=2))
            if path:
                print(f"Saved: {path}")
        else:
            print(self._tel_status_line(result, self.tel_count))

        return result

    def run_throughput_once(self) -> dict:
        try:
            probe  = ThroughputProbe(self.config)
            result = probe.collect()
        except Exception as e:
            self.thr_errors += 1
            print(f"[THR ERROR] {e}", file=sys.stderr)
            return {}

        path = self._save("throughput", result)
        self.thr_count += 1

        if self.print_pretty:
            print(f"\n=== THROUGHPUT #{self.thr_count} ===")
            print(json.dumps(result, indent=2))
            if path:
                print(f"Saved: {path}")
        else:
            print(self._thr_status_line(result, self.thr_count))

        return result

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def loop(self, duration_sec: float | None = None):
        """
        Run the monitoring loop.

        :param duration_sec: Stop after this many seconds. None = run forever.
                             Ctrl+C also stops the loop cleanly.
        """
        start_time = time.time()
        end_time   = (start_time + duration_sec) if duration_sec else None

        if duration_sec:
            duration_label = (f"{duration_sec:.0f}s  "
                              f"({duration_sec / 60:.1f} min)")
        else:
            duration_label = "indefinite  (Ctrl+C to stop)"

        throughput_enabled = self.config.get("modules", {}).get("throughput", False)

        print("=" * 62)
        print("  Micro-UXI Monitoring Controller")
        print("=" * 62)
        print(f"  Device      : {self.config['device']['device_id']}"
              f"  @  {self.config['device'].get('site_name', '?')}")
        print(f"  Interface   : {self.config['device']['iface']}")
        print(f"  Telemetry   : every {self.telemetry_interval}s")
        if throughput_enabled:
            print(f"  Throughput  : every {self.throughput_interval}s")
        else:
            print(f"  Throughput  : disabled")
        print(f"  Duration    : {duration_label}")
        print(f"  Format      : {self.output_format.upper()}")
        print(f"  Output dir  : {os.path.abspath(self.output_dir)}")
        print(f"  Session ID  : {self.session_id}")
        print("=" * 62)

        try:
            while True:
                now = time.time()

                # Stop when duration has elapsed
                if end_time and now >= end_time:
                    print(f"\n[i] Target duration reached.")
                    break

                if now - self.last_telemetry_ts >= self.telemetry_interval:
                    self.run_telemetry_once()
                    self.last_telemetry_ts = now

                if throughput_enabled and \
                        (now - self.last_throughput_ts >= self.throughput_interval):
                    self.run_throughput_once()
                    self.last_throughput_ts = now

                time.sleep(self.loop_sleep)

        except KeyboardInterrupt:
            print("\n[!] Stopped by user (Ctrl+C).")

        elapsed = time.time() - start_time
        print("=" * 62)
        print(f"  Session complete.")
        print(f"  Elapsed     : {elapsed:.1f}s  ({elapsed / 60:.1f} min)")
        print(f"  Telemetry   : {self.tel_count} collected"
              + (f"  |  {self.tel_errors} errors" if self.tel_errors else ""))
        if throughput_enabled:
            print(f"  Throughput  : {self.thr_count} collected"
                  + (f"  |  {self.thr_errors} errors" if self.thr_errors else ""))
        if self.save_output:
            print(f"  Output      : {os.path.abspath(self.output_dir)}")
        print("=" * 62)


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
Duration examples (--duration):
  0 / inf / indefinite   Run forever until Ctrl+C  (default)
  900                    900 seconds
  15m                    15 minutes
  1h                     1 hour
  30s                    30 seconds

Output format (--format):
  jsonl   Append each sample as a JSON line to one session file  (default)
  csv     Flat CSV rows, one per sample — easy for pandas / Excel
  json    One JSON file per sample — many small files, avoid for long runs
""",
    )
    parser.add_argument(
        "--config", default="config.json",
        help="Path to config JSON file  (default: config.json)")
    parser.add_argument(
        "--mode",
        choices=["loop", "once-telemetry", "once-throughput"],
        default="loop",
        help="Execution mode  (default: loop)")
    parser.add_argument(
        "--duration", default="0", metavar="DURATION",
        help="How long to run in loop mode  (default: 0 = indefinite)")
    parser.add_argument(
        "--format", choices=["jsonl", "csv", "json"], default=None,
        help="Output format — overrides config.output.format")
    parser.add_argument(
        "--verbose", action="store_true",
        help="Print full JSON for every sample (overrides config.output.print_pretty)")

    args = parser.parse_args()

    config = load_config(args.config)

    # --verbose flag overrides config
    if args.verbose:
        config.setdefault("output", {})["print_pretty"] = True

    # Resolve output format: CLI flag > config file > built-in default
    output_cfg = config.get("output") or {}
    fmt = args.format or output_cfg.get("format", "jsonl")

    controller = MonitorController(config, output_format=fmt)

    if args.mode == "once-telemetry":
        controller.run_telemetry_once()
    elif args.mode == "once-throughput":
        controller.run_throughput_once()
    else:
        duration_sec = parse_duration(args.duration)
        controller.loop(duration_sec=duration_sec)


if __name__ == "__main__":
    main()