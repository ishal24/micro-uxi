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
    def run(cmd, timeout=60, input_bytes=None):
        try:
            res = subprocess.run(
                cmd,
                input=input_bytes,
                capture_output=True,
                timeout=timeout,
            )
            stdout = res.stdout.decode("utf-8", errors="replace").strip()
            stderr = res.stderr.decode("utf-8", errors="replace").strip()
            return res.returncode, stdout, stderr
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

    @staticmethod
    def ensure_upload_payload(path, size_bytes, source="zero"):
        """
        Ensure a reusable static upload payload exists.

        - If the file exists and its size matches, reuse it.
        - If missing or size mismatch, create it once.
        - Uses atomic replace so the final file is not left half-written.
        """
        if not path:
            raise ValueError("Upload probe requires payload_path")

        size_bytes = int(size_bytes)
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)

        if os.path.exists(path) and os.path.getsize(path) == size_bytes:
            return {
                "path": path,
                "created": False,
                "reused": True,
                "size_bytes": size_bytes,
                "source": source
            }

        tmp_path = f"{path}.tmp"
        chunk_size = 1024 * 1024

        with open(tmp_path, "wb") as f:
            remaining = size_bytes

            if source == "random":
                while remaining > 0:
                    n = min(chunk_size, remaining)
                    f.write(os.urandom(n))
                    remaining -= n
            else:
                chunk = b"\0" * chunk_size
                while remaining > 0:
                    n = min(chunk_size, remaining)
                    f.write(chunk[:n])
                    remaining -= n

            f.flush()
            os.fsync(f.fileno())

        os.replace(tmp_path, path)

        return {
            "path": path,
            "created": True,
            "reused": False,
            "size_bytes": size_bytes,
            "source": source
        }

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

    @staticmethod
    def get_phase_timings_ms(t_dns, t_connect, t_tls, t_ttfb, t_total):
        tcp = max(t_connect - t_dns, 0.0)
        tls = max(t_tls - t_connect, 0.0)
        server_wait = max(t_ttfb - t_tls, 0.0)
        transfer = max(t_total - t_ttfb, 0.0)
        return {
            "dns_duration_ms": round(t_dns * 1000, 3),
            "tcp_duration_ms": round(tcp * 1000, 3),
            "tls_duration_ms": round(tls * 1000, 3),
            "server_wait_ms": round(server_wait * 1000, 3),
            "transfer_only_ms": round(transfer * 1000, 3),
        }

    def single_download_run(self, url, connect_timeout, max_time, expected_bytes=None):
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

        result = self.empty_run_result(started, ended, rc, err, "download")
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
            size_download = int(float(parts[6]))
        except Exception:
            return result

        self.fill_common_http_metrics(result, http_status, t_dns, t_connect, t_tls, t_ttfb, t_total)
        result["http_download_bytes"] = size_download

        if t_total > 0:
            result["throughput_total_mbps"] = round((size_download * 8) / t_total / 1_000_000, 6)

        transfer_only_sec = max(t_total - t_ttfb, 0.0)
        if transfer_only_sec > 0:
            result["throughput_transfer_mbps"] = round((size_download * 8) / transfer_only_sec / 1_000_000, 6)

        if expected_bytes is not None:
            result["download_complete"] = (size_download == expected_bytes)
        else:
            result["download_complete"] = (size_download > 0)

        return result

    def single_upload_run(self, url, connect_timeout, max_time, expected_bytes, payload_path=None, payload_source="zero"):
        if expected_bytes is None:
            raise ValueError("Upload probe requires expected_bytes / upload_bytes")

        payload_info = self.ensure_upload_payload(
            payload_path,
            int(expected_bytes),
            payload_source
        )

        curl_format = (
            "%{http_code} "
            "%{time_namelookup} "
            "%{time_connect} "
            "%{time_appconnect} "
            "%{time_starttransfer} "
            "%{time_total} "
            "%{size_upload}"
        )

        cmd = [
            "curl", "-L", "-o", "/dev/null", "-sS",
            "-X", "POST",
            "-H", "Content-Type: application/octet-stream",
            "--data-binary", f"@{payload_info['path']}",
            "--connect-timeout", str(connect_timeout),
            "--max-time", str(max_time),
            "-w", curl_format,
            url
        ]

        started = self.now_utc_iso()
        rc, out, err = self.run(cmd, timeout=max_time + 10)
        ended = self.now_utc_iso()

        result = self.empty_run_result(started, ended, rc, err, "upload")
        result["upload_payload"] = payload_info
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
            size_upload = int(float(parts[6]))
        except Exception:
            return result

        self.fill_common_http_metrics(result, http_status, t_dns, t_connect, t_tls, t_ttfb, t_total)
        result["http_upload_bytes"] = size_upload

        if t_total > 0:
            result["upload_throughput_total_mbps"] = round((size_upload * 8) / t_total / 1_000_000, 6)

        transfer_only_sec = max(t_total - t_ttfb, 0.0)
        if transfer_only_sec > 0:
            result["upload_throughput_transfer_mbps"] = round((size_upload * 8) / transfer_only_sec / 1_000_000, 6)

        result["upload_complete"] = (size_upload == expected_bytes)
        return result

    def empty_run_result(self, started, ended, rc, err, direction):
        return {
            "direction": direction,
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
            "dns_duration_ms": None,
            "tcp_duration_ms": None,
            "tls_duration_ms": None,
            "server_wait_ms": None,
            "transfer_only_ms": None,
            "http_download_bytes": None,
            "http_upload_bytes": None,
            "upload_payload": None,
            "throughput_total_mbps": None,
            "throughput_transfer_mbps": None,
            "upload_throughput_total_mbps": None,
            "upload_throughput_transfer_mbps": None,
            "download_complete": None,
            "upload_complete": None
        }

    def fill_common_http_metrics(self, result, http_status, t_dns, t_connect, t_tls, t_ttfb, t_total):
        result["http_status"] = http_status
        result["http_dns_ms"] = round(t_dns * 1000, 3)
        result["http_connect_ms"] = round(t_connect * 1000, 3)
        result["http_tls_ms"] = round(t_tls * 1000, 3)
        result["http_ttfb_ms"] = round(t_ttfb * 1000, 3)
        result["http_total_ms"] = round(t_total * 1000, 3)
        result.update(self.get_phase_timings_ms(t_dns, t_connect, t_tls, t_ttfb, t_total))

    def summarize(self, runs, direction="download"):
        summary = {}
        metrics = [
            "http_dns_ms",
            "http_connect_ms",
            "http_tls_ms",
            "http_ttfb_ms",
            "http_total_ms",
            "dns_duration_ms",
            "tcp_duration_ms",
            "tls_duration_ms",
            "server_wait_ms",
            "transfer_only_ms",
        ]

        if direction == "upload":
            metrics += [
                "http_upload_bytes",
                "upload_throughput_total_mbps",
                "upload_throughput_transfer_mbps",
            ]
        else:
            metrics += [
                "http_download_bytes",
                "throughput_total_mbps",
                "throughput_transfer_mbps",
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

        success = [
            r for r in runs
            if r.get("curl_rc") == 0 and r.get("http_status") and 200 <= r["http_status"] < 400
        ]
        health = {
            "total_runs": len(runs),
            "successful_http_runs": len(success),
            "failed_runs": len(runs) - len(success),
            "curl_reasons_seen": sorted(set(r.get("curl_reason") for r in runs if r.get("curl_reason"))),
        }
        if direction == "upload":
            health["upload_complete_true"] = sum(1 for r in runs if r.get("upload_complete") is True)
            health["upload_complete_false"] = sum(1 for r in runs if r.get("upload_complete") is False)
        else:
            health["download_complete_true"] = sum(1 for r in runs if r.get("download_complete") is True)
            health["download_complete_false"] = sum(1 for r in runs if r.get("download_complete") is False)

        summary["run_health"] = health
        return summary

    @staticmethod
    def normalize_mode_config(mode_cfg):
        """
        Backward compatible config support.

        Old style:
          routine: { url, expected_bytes, runs, warmup, pause_sec, max_time_sec }

        New style:
          routine: {
            download: { enabled, url, expected_bytes, runs, warmup, pause_sec, max_time_sec },
            upload:   { enabled, url, expected_bytes, runs, warmup, pause_sec, max_time_sec }
          }
        """
        common_keys = ["runs", "warmup", "pause_sec", "max_time_sec"]

        if "download" in mode_cfg or "upload" in mode_cfg:
            download_cfg = dict(mode_cfg.get("download", {}))
            upload_cfg = dict(mode_cfg.get("upload", {}))
            for key in common_keys:
                if key in mode_cfg:
                    download_cfg.setdefault(key, mode_cfg[key])
                    upload_cfg.setdefault(key, mode_cfg[key])
            download_cfg.setdefault("enabled", bool(download_cfg.get("url")))
            upload_cfg.setdefault("enabled", bool(upload_cfg.get("url")))
            return download_cfg, upload_cfg

        # Old config is treated as download-only.
        download_cfg = dict(mode_cfg)
        download_cfg.setdefault("enabled", True)
        upload_cfg = {"enabled": False}
        return download_cfg, upload_cfg

    def run_direction(self, direction, cfg, connect_timeout):
        enabled = cfg.get("enabled", False)
        warmup_runs = []
        measurement_runs = []

        if not enabled:
            return warmup_runs, measurement_runs, {}

        url = cfg["url"]
        expected_bytes = cfg.get("expected_bytes", cfg.get("upload_bytes"))
        runs = cfg.get("runs", 1)
        warmup = cfg.get("warmup", 0)
        pause_sec = cfg.get("pause_sec", 1)
        max_time = cfg.get("max_time_sec", 20)

        def run_once():
            if direction == "upload":
                return self.single_upload_run(
                    url,
                    connect_timeout,
                    max_time,
                    expected_bytes,
                    payload_path=cfg.get("payload_path"),
                    payload_source=cfg.get("payload_source", "zero")
                )
            return self.single_download_run(url, connect_timeout, max_time, expected_bytes)

        for i in range(warmup):
            warmup_runs.append(run_once())
            if i < warmup - 1:
                time.sleep(pause_sec)

        for i in range(runs):
            measurement_runs.append(run_once())
            if i < runs - 1:
                time.sleep(pause_sec)

        summary = self.summarize(measurement_runs, direction=direction)
        return warmup_runs, measurement_runs, summary

    def collect(self):
        tp_cfg = self.config["throughput"]
        mode = tp_cfg.get("mode", "routine")
        mode_cfg = tp_cfg[mode]
        connect_timeout = tp_cfg.get("connect_timeout_sec", 5)

        download_cfg, upload_cfg = self.normalize_mode_config(mode_cfg)

        result = {
            "probe_type": "throughput",
            "collected_at_utc": self.now_utc_iso(),
            "device_id": self.config["device"]["device_id"],
            "site_name": self.config["device"].get("site_name"),
            "iface": self.iface,
            "mode": mode,
            "config_used": {
                "connect_timeout_sec": connect_timeout,
                "download": download_cfg,
                "upload": upload_cfg,
            },
            "context": self.collect_context(),
            "download_warmup_runs": [],
            "download_measurement_runs": [],
            "upload_warmup_runs": [],
            "upload_measurement_runs": [],
            "summary": {
                "download": {},
                "upload": {}
            }
        }

        result["download_warmup_runs"], result["download_measurement_runs"], result["summary"]["download"] = self.run_direction(
            "download", download_cfg, connect_timeout
        )
        result["upload_warmup_runs"], result["upload_measurement_runs"], result["summary"]["upload"] = self.run_direction(
            "upload", upload_cfg, connect_timeout
        )

        # Backward-compatible aliases for older readers that expect download-only keys.
        result["warmup_runs"] = result["download_warmup_runs"]
        result["measurement_runs"] = result["download_measurement_runs"]

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
