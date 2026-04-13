#!/usr/bin/env python3

import argparse
import json
import math
import os
import re
import shutil
import statistics
import subprocess
import time
from datetime import datetime, timezone

os.environ["PATH"] += ":/usr/sbin"

CURL_EXIT_CODES = {
    0: "OK",
    6: "Could not resolve host",
    7: "Failed to connect to host",
    18: "Partial file",
    22: "HTTP page not retrieved",
    28: "Operation timeout",
    35: "TLS/SSL connect error",
    47: "Too many redirects",
    52: "Empty reply from server",
    56: "Failure receiving network data",
    -999: "Python subprocess timeout"
}


class ThroughputProbe:
    def __init__(self, config):
        self.config = config
        self.iface = config["device"]["iface"]

    @staticmethod
    def now_utc_iso():
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def run(cmd, timeout=60):
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return res.returncode, res.stdout.strip(), res.stderr.strip()
        except subprocess.TimeoutExpired:
            return -999, "", "PYTHON_SUBPROCESS_TIMEOUT"
        except Exception as e:
            return -1, "", str(e)

    @staticmethod
    def percentile(values, p):
        if not values:
            return None
        if len(values) == 1:
            return values[0]
        values = sorted(values)
        k = (len(values) - 1) * (p / 100.0)
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return values[int(k)]
        return values[f] * (c - k) + values[c] * (k - f)

    @staticmethod
    def curl_reason(code):
        return CURL_EXIT_CODES.get(code, f"Unknown curl exit code: {code}")

    def collect_context(self):
        context = {
            "wifi_connected": None,
            "wifi_ssid": None,
            "wifi_bssid": None,
            "wifi_rssi_dbm": None,
            "wifi_bitrate_mbps": None,
            "wifi_freq_mhz": None,
            "ip_address": None,
            "gateway_ip": None,
            "dns_resolvers": []
        }

        if shutil.which("iw") is not None:
            rc, out, err = self.run(["iw", "dev", self.iface, "link"], timeout=10)
            if rc == 0 and "Connected to" in out:
                context["wifi_connected"] = True
                m = re.search(r"SSID:\s*(.+)", out)
                if m:
                    context["wifi_ssid"] = m.group(1).strip()
                m = re.search(r"Connected to\s+([0-9a-f:]{17})", out, re.IGNORECASE)
                if m:
                    context["wifi_bssid"] = m.group(1)
                m = re.search(r"signal:\s*(-?\d+)", out)
                if m:
                    context["wifi_rssi_dbm"] = int(m.group(1))
                m = re.search(r"tx bitrate:\s*([\d.]+)", out)
                if m:
                    context["wifi_bitrate_mbps"] = float(m.group(1))
                m = re.search(r"freq:\s*(\d+)", out)
                if m:
                    context["wifi_freq_mhz"] = int(m.group(1))
            else:
                context["wifi_connected"] = False

        rc, out, err = self.run(["ip", "-4", "addr", "show", self.iface], timeout=10)
        m = re.search(r"inet\s+([\d.]+)", out)
        if m:
            context["ip_address"] = m.group(1)

        rc, out, err = self.run(["ip", "route", "show", "default"], timeout=10)
        m = re.search(r"default via ([\d.]+)", out)
        if m:
            context["gateway_ip"] = m.group(1)

        try:
            with open("/etc/resolv.conf", "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("nameserver"):
                        parts = line.split()
                        if len(parts) >= 2:
                            context["dns_resolvers"].append(parts[1])
        except Exception:
            pass

        return context

    def single_run(self, url, connect_timeout, max_time, expected_bytes=None):
        curl_format = (
            "%{http_code} "
            "%{time_namelookup} "
            "%{time_connect} "
            "%{time_appconnect} "
            "%{time_starttransfer} "
            "%{time_total} "
            "%{size_download}"
        )

        cmd = [
            "curl", "-L", "-o", "/dev/null", "-sS",
            "--connect-timeout", str(connect_timeout),
            "--max-time", str(max_time),
            "-w", curl_format,
            url
        ]

        started = self.now_utc_iso()
        rc, out, err = self.run(cmd, timeout=max_time + 10)
        ended = self.now_utc_iso()

        result = {
            "sample_started_at_utc": started,
            "sample_ended_at_utc": ended,
            "curl_rc": rc,
            "curl_reason": self.curl_reason(rc),
            "curl_stderr": err,
            "http_status": None,
            "http_dns_ms": None,
            "http_connect_ms": None,
            "http_tls_ms": None,
            "http_ttfb_ms": None,
            "http_total_ms": None,
            "http_download_bytes": None,
            "transfer_only_ms": None,
            "throughput_total_mbps": None,
            "throughput_transfer_mbps": None,
            "download_complete": None
        }

        parts = out.split()
        if rc != 0 or len(parts) < 7:
            return result

        try:
            http_status = int(parts[0])
            t_dns = float(parts[1])
            t_connect = float(parts[2])
            t_tls = float(parts[3])
            t_ttfb = float(parts[4])
            t_total = float(parts[5])
            size_download = int(parts[6])
        except Exception:
            return result

        result["http_status"] = http_status
        result["http_dns_ms"] = round(t_dns * 1000, 3)
        result["http_connect_ms"] = round(t_connect * 1000, 3)
        result["http_tls_ms"] = round(t_tls * 1000, 3)
        result["http_ttfb_ms"] = round(t_ttfb * 1000, 3)
        result["http_total_ms"] = round(t_total * 1000, 3)
        result["http_download_bytes"] = size_download

        if t_total > 0:
            result["throughput_total_mbps"] = round((size_download * 8) / t_total / 1_000_000, 6)

        if t_total > t_ttfb:
            transfer_only_sec = t_total - t_ttfb
            result["transfer_only_ms"] = round(transfer_only_sec * 1000, 3)
            result["throughput_transfer_mbps"] = round((size_download * 8) / transfer_only_sec / 1_000_000, 6)

        if expected_bytes is not None:
            result["download_complete"] = (size_download == expected_bytes)
        else:
            result["download_complete"] = (size_download > 0)

        return result

    def summarize(self, runs):
        summary = {}
        metrics = [
            "http_dns_ms",
            "http_connect_ms",
            "http_tls_ms",
            "http_ttfb_ms",
            "http_total_ms",
            "http_download_bytes",
            "transfer_only_ms",
            "throughput_total_mbps",
            "throughput_transfer_mbps"
        ]

        for metric in metrics:
            vals = [r[metric] for r in runs if isinstance(r.get(metric), (int, float))]
            if not vals:
                summary[metric] = None
                continue
            summary[metric] = {
                "count": len(vals),
                "min": round(min(vals), 6),
                "avg": round(statistics.mean(vals), 6),
                "median": round(statistics.median(vals), 6),
                "p95": round(self.percentile(vals, 95), 6),
                "max": round(max(vals), 6)
            }

        success = [r for r in runs if r.get("curl_rc") == 0 and r.get("http_status") and 200 <= r["http_status"] < 400]
        summary["run_health"] = {
            "total_runs": len(runs),
            "successful_http_runs": len(success),
            "failed_runs": len(runs) - len(success),
            "curl_reasons_seen": sorted(set(r.get("curl_reason") for r in runs if r.get("curl_reason"))),
            "download_complete_true": sum(1 for r in runs if r.get("download_complete") is True),
            "download_complete_false": sum(1 for r in runs if r.get("download_complete") is False)
        }

        return summary

    def collect(self):
        tp_cfg = self.config["throughput"]
        mode = tp_cfg.get("mode", "routine")
        mode_cfg = tp_cfg[mode]

        url = mode_cfg["url"]
        expected_bytes = mode_cfg.get("expected_bytes")
        runs = mode_cfg.get("runs", 1)
        warmup = mode_cfg.get("warmup", 0)
        pause_sec = mode_cfg.get("pause_sec", 1)
        connect_timeout = tp_cfg.get("connect_timeout_sec", 5)
        max_time = mode_cfg.get("max_time_sec", 20)

        result = {
            "probe_type": "throughput",
            "collected_at_utc": self.now_utc_iso(),
            "device_id": self.config["device"]["device_id"],
            "site_name": self.config["device"].get("site_name"),
            "iface": self.iface,
            "mode": mode,
            "config_used": {
                "url": url,
                "expected_bytes": expected_bytes,
                "runs": runs,
                "warmup": warmup,
                "pause_sec": pause_sec,
                "connect_timeout_sec": connect_timeout,
                "max_time_sec": max_time
            },
            "context": self.collect_context(),
            "warmup_runs": [],
            "measurement_runs": [],
            "summary": {}
        }

        for i in range(warmup):
            result["warmup_runs"].append(self.single_run(url, connect_timeout, max_time, expected_bytes))
            if i < warmup - 1:
                time.sleep(pause_sec)

        for i in range(runs):
            result["measurement_runs"].append(self.single_run(url, connect_timeout, max_time, expected_bytes))
            if i < runs - 1:
                time.sleep(pause_sec)

        result["summary"] = self.summarize(result["measurement_runs"])
        return result


def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description="Micro-UXI throughput probe")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--save-json", default=None)
    args = parser.parse_args()

    config = load_config(args.config)
    probe = ThroughputProbe(config)
    result = probe.collect()

    print(json.dumps(result, indent=2))

    if args.save_json:
        with open(args.save_json, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)


if __name__ == "__main__":
    main()