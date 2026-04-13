#!/usr/bin/env python3

import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone

os.environ["PATH"] += ":/usr/sbin"


class TelemetryProbe:
    def __init__(self, config):
        self.config = config
        self.results = {
            "probe_type": "telemetry",
            "collected_at_utc": self.now_utc_iso(),
            "device_id": config["device"]["device_id"],
            "site_name": config["device"].get("site_name"),
            "iface": config["device"]["iface"],
            "telemetry": {}
        }

    @staticmethod
    def now_utc_iso():
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def run(cmd, timeout=15):
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return res.returncode, res.stdout.strip(), res.stderr.strip()
        except subprocess.TimeoutExpired:
            return -999, "", "TIMEOUT"
        except Exception as e:
            return -1, "", str(e)

    def collect_wifi(self):
        iface = self.config["device"]["iface"]
        data = {
            "wifi_connected": None,
            "wifi_ssid": None,
            "wifi_bssid": None,
            "wifi_rssi_dbm": None,
            "wifi_bitrate_mbps": None,
            "wifi_freq_mhz": None
        }

        if shutil.which("iw") is None:
            self.results["telemetry"]["wifi"] = data
            return

        rc, out, err = self.run(["iw", "dev", iface, "link"], timeout=10)
        if rc != 0 or "Connected to" not in out:
            data["wifi_connected"] = False
            self.results["telemetry"]["wifi"] = data
            return

        data["wifi_connected"] = True

        m = re.search(r"SSID:\s*(.+)", out)
        if m:
            data["wifi_ssid"] = m.group(1).strip()

        m = re.search(r"Connected to\s+([0-9a-f:]{17})", out, re.IGNORECASE)
        if m:
            data["wifi_bssid"] = m.group(1)

        m = re.search(r"signal:\s*(-?\d+)", out)
        if m:
            data["wifi_rssi_dbm"] = int(m.group(1))

        m = re.search(r"tx bitrate:\s*([\d.]+)", out)
        if m:
            data["wifi_bitrate_mbps"] = float(m.group(1))

        m = re.search(r"freq:\s*(\d+)", out)
        if m:
            data["wifi_freq_mhz"] = int(m.group(1))

        self.results["telemetry"]["wifi"] = data

    def collect_network(self):
        iface = self.config["device"]["iface"]
        data = {
            "ip_address": None,
            "gateway_ip": None,
            "dns_resolvers": []
        }

        rc, out, err = self.run(["ip", "-4", "addr", "show", iface], timeout=10)
        m = re.search(r"inet\s+([\d.]+)", out)
        if m:
            data["ip_address"] = m.group(1)

        rc, out, err = self.run(["ip", "route", "show", "default"], timeout=10)
        m = re.search(r"default via ([\d.]+)", out)
        if m:
            data["gateway_ip"] = m.group(1)

        try:
            with open("/etc/resolv.conf", "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("nameserver"):
                        parts = line.split()
                        if len(parts) >= 2:
                            data["dns_resolvers"].append(parts[1])
        except Exception:
            pass

        self.results["telemetry"]["network"] = data

    def collect_ping(self):
        ping_cfg = self.config["ping"]
        target = ping_cfg["target"]
        count = ping_cfg.get("count", 5)
        interval = ping_cfg.get("interval_sec", 0.2)
        timeout = ping_cfg.get("timeout_sec", 10)

        data = {
            "ping_target": target,
            "loss_pct": None,
            "rtt_min_ms": None,
            "rtt_avg_ms": None,
            "rtt_max_ms": None,
            "rtt_mdev_ms": None
        }

        if shutil.which("ping") is None:
            self.results["telemetry"]["ping"] = data
            return

        rc, out, err = self.run(
            ["ping", "-c", str(count), "-i", str(interval), target],
            timeout=timeout
        )

        m = re.search(r"(\d+(?:\.\d+)?)% packet loss", out)
        if m:
            data["loss_pct"] = float(m.group(1))

        m = re.search(r"rtt min/avg/max/mdev = ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)", out)
        if m:
            data["rtt_min_ms"] = float(m.group(1))
            data["rtt_avg_ms"] = float(m.group(2))
            data["rtt_max_ms"] = float(m.group(3))
            data["rtt_mdev_ms"] = float(m.group(4))

        self.results["telemetry"]["ping"] = data

    def collect_dns(self):
        dns_cfg = self.config["dns"]
        domains = dns_cfg.get("domains_routine", [])
        resolvers = dns_cfg.get("resolvers", ["system"])
        timeout_sec = dns_cfg.get("timeout_sec", 5)

        all_results = []

        for domain in domains:
            for resolver in resolvers:
                entry = {
                    "domain": domain,
                    "resolver": resolver,
                    "dns_latency_ms": None,
                    "dns_success": None,
                    "status_text": None
                }

                if resolver == "system":
                    cmd = ["dig", domain, "+stats", "+time=2", "+tries=1"]
                else:
                    cmd = ["dig", f"@{resolver}", domain, "+stats", "+time=2", "+tries=1"]

                start = time.time()
                rc, out, err = self.run(cmd, timeout=timeout_sec)
                elapsed = (time.time() - start) * 1000

                entry["dns_latency_ms"] = round(elapsed, 2)
                entry["dns_success"] = ("status: NOERROR" in out)

                m = re.search(r"status:\s*([A-Z]+)", out)
                if m:
                    entry["status_text"] = m.group(1)
                elif err:
                    entry["status_text"] = err

                all_results.append(entry)

        self.results["telemetry"]["dns"] = all_results

    def collect_http(self):
        http_cfg = self.config["http"]
        targets = http_cfg.get("targets", [])
        connect_timeout = http_cfg.get("connect_timeout_sec", 5)
        max_time = http_cfg.get("max_time_sec", 15)

        all_results = []
        for url in targets:
            entry = {
                "http_url": url,
                "http_status": None,
                "http_dns_ms": None,
                "http_connect_ms": None,
                "http_tls_ms": None,
                "http_ttfb_ms": None,
                "http_total_ms": None,
                "http_download_bytes": None,
                "curl_rc": None,
                "curl_stderr": None
            }

            cmd = [
                "curl", "-L", "-o", "/dev/null", "-sS",
                "--connect-timeout", str(connect_timeout),
                "--max-time", str(max_time),
                "-w",
                "%{http_code} %{time_namelookup} %{time_connect} %{time_appconnect} %{time_starttransfer} %{time_total} %{size_download}",
                url,
            ]

            rc, out, err = self.run(cmd, timeout=max_time + 10)
            entry["curl_rc"] = rc
            entry["curl_stderr"] = err

            parts = out.strip().split()
            if rc == 0 and len(parts) >= 7:
                try:
                    entry["http_status"] = int(parts[0])
                    entry["http_dns_ms"] = float(parts[1]) * 1000
                    entry["http_connect_ms"] = float(parts[2]) * 1000
                    entry["http_tls_ms"] = float(parts[3]) * 1000
                    entry["http_ttfb_ms"] = float(parts[4]) * 1000
                    entry["http_total_ms"] = float(parts[5]) * 1000
                    entry["http_download_bytes"] = int(parts[6])
                except Exception:
                    pass

            all_results.append(entry)

        self.results["telemetry"]["http"] = all_results

    def collect(self):
        modules = self.config["modules"]

        if modules.get("wifi"):
            self.collect_wifi()
        if modules.get("network"):
            self.collect_network()
        if modules.get("ping"):
            self.collect_ping()
        if modules.get("dns"):
            self.collect_dns()
        if modules.get("http"):
            self.collect_http()

        return self.results


def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Micro-UXI telemetry probe")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--save-json", default=None)
    args = parser.parse_args()

    config = load_config(args.config)
    probe = TelemetryProbe(config)
    result = probe.collect()

    print(json.dumps(result, indent=2))

    if args.save_json:
        with open(args.save_json, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)


if __name__ == "__main__":
    main()