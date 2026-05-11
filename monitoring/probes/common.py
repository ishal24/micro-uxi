from __future__ import annotations

import os
import re
import time
from typing import Iterable
from urllib.parse import urlparse

from monitoring.utils import run_command, utc_now_iso

os.environ["PATH"] += ":/usr/sbin"

try:
    import dns.exception
    import dns.resolver

    HAS_DNSPYTHON = True
except ImportError:  # pragma: no cover - optional on target
    HAS_DNSPYTHON = False


def read_operstate(iface: str) -> bool | None:
    try:
        with open(f"/sys/class/net/{iface}/operstate", "r", encoding="utf-8") as fh:
            return fh.read().strip() == "up"
    except Exception:
        return None


def collect_wifi_details(iface: str) -> dict:
    data = {
        "wifi_up": read_operstate(iface),
        "wifi_connected": None,
        "wifi_ssid": None,
        "wifi_bssid": None,
        "wifi_rssi_dbm": None,
        "wifi_bitrate_mbps": None,
        "wifi_freq_mhz": None,
    }

    rc, out, _ = run_command(["iw", "dev", iface, "link"], timeout=10)
    if rc != 0 or "Connected to" not in out:
        data["wifi_connected"] = False
        return data

    data["wifi_connected"] = True

    match = re.search(r"SSID:\s*(.+)", out)
    if match:
        data["wifi_ssid"] = match.group(1).strip()

    match = re.search(r"Connected to\s+([0-9a-f:]{17})", out, re.IGNORECASE)
    if match:
        data["wifi_bssid"] = match.group(1)

    match = re.search(r"signal:\s*(-?\d+)", out)
    if match:
        data["wifi_rssi_dbm"] = int(match.group(1))

    match = re.search(r"tx bitrate:\s*([\d.]+)", out)
    if match:
        data["wifi_bitrate_mbps"] = float(match.group(1))

    match = re.search(r"freq:\s*(\d+)", out)
    if match:
        data["wifi_freq_mhz"] = int(match.group(1))

    return data


def collect_network_details(iface: str) -> dict:
    data = {
        "ip_address": None,
        "gateway_ip": None,
        "dns_resolvers": [],
    }

    _, out, _ = run_command(["ip", "-4", "addr", "show", iface], timeout=10)
    match = re.search(r"inet\s+([\d.]+)", out)
    if match:
        data["ip_address"] = match.group(1)

    _, out, _ = run_command(["ip", "route", "show", "default"], timeout=10)
    match = re.search(r"default via ([\d.]+)", out)
    if match:
        data["gateway_ip"] = match.group(1)

    try:
        with open("/etc/resolv.conf", "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("nameserver"):
                    parts = line.split()
                    if len(parts) >= 2:
                        data["dns_resolvers"].append(parts[1])
    except Exception:
        pass

    return data


def ping_once(target: str, timeout_sec: int) -> dict:
    rc, out, err = run_command(
        ["ping", "-c", "1", "-W", str(timeout_sec), target],
        timeout=timeout_sec + 2,
    )
    success = rc == 0
    rtt_ms = None
    if success:
        match = re.search(r"time=([0-9.]+)", out)
        if match:
            rtt_ms = float(match.group(1))

    return {
        "target": target,
        "success": success,
        "rtt_ms": rtt_ms,
        "error": None if success else (err or "PING_FAILED"),
    }


def ping_batch(target: str, count: int, interval_sec: float, timeout_sec: int) -> dict:
    rc, out, err = run_command(
        ["ping", "-c", str(count), "-i", str(interval_sec), target],
        timeout=timeout_sec,
    )
    result = {
        "target": target,
        "success": rc == 0,
        "loss_pct": None,
        "rtt_min_ms": None,
        "rtt_avg_ms": None,
        "rtt_max_ms": None,
        "rtt_mdev_ms": None,
        "error": None if rc == 0 else (err or "PING_FAILED"),
    }

    match = re.search(r"(\d+(?:\.\d+)?)% packet loss", out)
    if match:
        result["loss_pct"] = float(match.group(1))

    match = re.search(r"rtt min/avg/max/mdev = ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)", out)
    if match:
        result["rtt_min_ms"] = float(match.group(1))
        result["rtt_avg_ms"] = float(match.group(2))
        result["rtt_max_ms"] = float(match.group(3))
        result["rtt_mdev_ms"] = float(match.group(4))

    return result


def _dig_status(stdout: str, stderr: str, rc: int) -> tuple[str, bool]:
    match = re.search(r"status:\s*([A-Z]+)", stdout)
    if match:
        status = match.group(1)
        return status, status == "NOERROR"
    if rc == -999:
        return "TIMEOUT", False
    return (stderr or "ERROR"), False


def resolve_dns(name: str, scope: str, timeout_sec: float, resolver: str | None = None) -> dict:
    entry = {
        "target": name,
        "scope": scope,
        "resolver": resolver or "system",
        "success": False,
        "latency_ms": None,
        "status": None,
        "timeout": False,
        "answers": [],
    }

    if HAS_DNSPYTHON:
        res = dns.resolver.Resolver()
        res.cache = None
        res.timeout = timeout_sec
        res.lifetime = timeout_sec
        if resolver and resolver != "system":
            res.nameservers = [resolver]

        start = time.monotonic()
        try:
            answers = res.resolve(name, "A")
            entry["latency_ms"] = round((time.monotonic() - start) * 1000, 2)
            entry["success"] = True
            entry["status"] = "NOERROR"
            entry["answers"] = [r.to_text() for r in answers]
        except dns.resolver.NXDOMAIN:
            entry["latency_ms"] = round((time.monotonic() - start) * 1000, 2)
            entry["status"] = "NXDOMAIN"
        except dns.exception.Timeout:
            entry["latency_ms"] = round((time.monotonic() - start) * 1000, 2)
            entry["status"] = "TIMEOUT"
            entry["timeout"] = True
        except Exception as exc:  # pragma: no cover - device/runtime dependent
            entry["latency_ms"] = round((time.monotonic() - start) * 1000, 2)
            entry["status"] = exc.__class__.__name__.upper()
    else:
        cmd = ["dig", name, "+stats", "+tries=1", f"+time={max(int(timeout_sec), 1)}"]
        if resolver and resolver != "system":
            cmd.insert(1, f"@{resolver}")
        start = time.monotonic()
        rc, out, err = run_command(cmd, timeout=timeout_sec + 2)
        entry["latency_ms"] = round((time.monotonic() - start) * 1000, 2)
        status, success = _dig_status(out, err, rc)
        entry["status"] = status
        entry["success"] = success
        entry["timeout"] = status == "TIMEOUT"
        if success:
            entry["answers"] = [line for line in out.splitlines() if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", line.strip())]

    return entry


def resolve_dns_matrix(
    targets: Iterable[dict],
    timeout_sec: float,
    resolvers: Iterable[str],
) -> list[dict]:
    results: list[dict] = []
    for target in targets:
        name = target["name"]
        scope = target.get("scope", "unknown")
        for resolver in resolvers:
            results.append(resolve_dns(name, scope, timeout_sec, resolver))
    return results


def measure_http(
    url: str,
    scope: str,
    connect_timeout_sec: int,
    max_time_sec: int,
    expected_status_min: int = 200,
    expected_status_max: int = 399,
) -> dict:
    entry = {
        "url": url,
        "host": urlparse(url).hostname or url,
        "scope": scope,
        "http_status": None,
        "http_dns_ms": None,
        "http_connect_ms": None,
        "http_tls_ms": None,
        "http_ttfb_ms": None,
        "http_total_ms": None,
        "http_download_bytes": None,
        "curl_rc": None,
        "curl_stderr": None,
        "http_ok": False,
        "expected_status_min": expected_status_min,
        "expected_status_max": expected_status_max,
    }

    cmd = [
        "curl",
        "-L",
        "-o",
        "/dev/null",
        "-sS",
        "--connect-timeout",
        str(connect_timeout_sec),
        "--max-time",
        str(max_time_sec),
        "-w",
        "%{http_code} %{time_namelookup} %{time_connect} %{time_appconnect} %{time_starttransfer} %{time_total} %{size_download}",
        url,
    ]

    rc, out, err = run_command(cmd, timeout=max_time_sec + 10)
    entry["curl_rc"] = rc
    entry["curl_stderr"] = err

    parts = out.split()
    if rc == 0 and len(parts) >= 7:
        try:
            entry["http_status"] = int(parts[0])
            entry["http_dns_ms"] = float(parts[1]) * 1000
            entry["http_connect_ms"] = float(parts[2]) * 1000
            entry["http_tls_ms"] = float(parts[3]) * 1000
            entry["http_ttfb_ms"] = float(parts[4]) * 1000
            entry["http_total_ms"] = float(parts[5]) * 1000
            entry["http_download_bytes"] = int(float(parts[6]))
        except Exception:
            pass

    status = entry["http_status"]
    entry["http_ok"] = (
        rc == 0
        and status is not None
        and expected_status_min <= status <= expected_status_max
    )
    return entry


def sample_header(device_cfg: dict, probe_type: str, seq: int) -> dict:
    return {
        "probe_type": probe_type,
        "ts": utc_now_iso(),
        "seq": seq,
        "device_id": device_cfg.get("device_id", "unknown"),
        "site_name": device_cfg.get("site_name"),
        "iface": device_cfg.get("iface", "wlan0"),
    }

