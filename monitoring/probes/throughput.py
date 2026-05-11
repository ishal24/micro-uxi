from __future__ import annotations

import os
import statistics
import subprocess
import time
from typing import Iterable

from monitoring.probes.common import collect_network_details, collect_wifi_details, sample_header
from monitoring.utils import percentile


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
    -999: "Python subprocess timeout",
}


class ThroughputProbe:
    def __init__(self, config: dict):
        self.config = config
        self.device_cfg = config["device"]
        self.probe_cfg = config["throughput_probe"]
        self._seq = 0

    @staticmethod
    def run(cmd: list[str], timeout: int = 60) -> tuple[int, str, str]:
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
            return (
                proc.returncode,
                proc.stdout.decode("utf-8", errors="replace").strip(),
                proc.stderr.decode("utf-8", errors="replace").strip(),
            )
        except subprocess.TimeoutExpired:
            return -999, "", "PYTHON_SUBPROCESS_TIMEOUT"
        except Exception as exc:  # pragma: no cover - device/runtime dependent
            return -1, "", str(exc)

    @staticmethod
    def curl_reason(code: int) -> str:
        return CURL_EXIT_CODES.get(code, f"Unknown curl exit code: {code}")

    @staticmethod
    def ensure_upload_payload(path: str, size_bytes: int, source: str = "zero") -> dict:
        if not path:
            raise ValueError("Upload probe requires payload_path")

        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)

        if os.path.exists(path) and os.path.getsize(path) == size_bytes:
            return {
                "path": path,
                "created": False,
                "reused": True,
                "size_bytes": size_bytes,
                "source": source,
            }

        tmp_path = f"{path}.tmp"
        chunk_size = 1024 * 1024
        with open(tmp_path, "wb") as fh:
            remaining = size_bytes
            if source == "random":
                while remaining > 0:
                    nbytes = min(chunk_size, remaining)
                    fh.write(os.urandom(nbytes))
                    remaining -= nbytes
            else:
                chunk = b"\0" * chunk_size
                while remaining > 0:
                    nbytes = min(chunk_size, remaining)
                    fh.write(chunk[:nbytes])
                    remaining -= nbytes
            fh.flush()
            os.fsync(fh.fileno())

        os.replace(tmp_path, path)
        return {
            "path": path,
            "created": True,
            "reused": False,
            "size_bytes": size_bytes,
            "source": source,
        }

    @staticmethod
    def phase_breakdown_ms(t_dns: float, t_connect: float, t_tls: float, t_ttfb: float, t_total: float) -> dict:
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

    def empty_run_result(self, direction: str, rc: int, err: str) -> dict:
        return {
            "direction": direction,
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
            "throughput_total_mbps": None,
            "throughput_transfer_mbps": None,
            "upload_throughput_total_mbps": None,
            "upload_throughput_transfer_mbps": None,
            "download_complete": None,
            "upload_complete": None,
            "upload_payload": None,
        }

    def fill_http_metrics(self, result: dict, http_status: int, t_dns: float, t_connect: float, t_tls: float, t_ttfb: float, t_total: float) -> None:
        result["http_status"] = http_status
        result["http_dns_ms"] = round(t_dns * 1000, 3)
        result["http_connect_ms"] = round(t_connect * 1000, 3)
        result["http_tls_ms"] = round(t_tls * 1000, 3)
        result["http_ttfb_ms"] = round(t_ttfb * 1000, 3)
        result["http_total_ms"] = round(t_total * 1000, 3)
        result.update(self.phase_breakdown_ms(t_dns, t_connect, t_tls, t_ttfb, t_total))

    def single_download_run(self, cfg: dict, connect_timeout: int) -> dict:
        url = cfg["url"]
        expected_bytes = cfg.get("expected_bytes")
        max_time = int(cfg.get("max_time_sec", 60))
        cmd = [
            "curl",
            "-L",
            "-o",
            "/dev/null",
            "-sS",
            "--connect-timeout",
            str(connect_timeout),
            "--max-time",
            str(max_time),
            "-w",
            "%{http_code} %{time_namelookup} %{time_connect} %{time_appconnect} %{time_starttransfer} %{time_total} %{size_download}",
            url,
        ]

        rc, out, err = self.run(cmd, timeout=max_time + 10)
        result = self.empty_run_result("download", rc, err)
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

        self.fill_http_metrics(result, http_status, t_dns, t_connect, t_tls, t_ttfb, t_total)
        result["http_download_bytes"] = size_download
        if t_total > 0:
            result["throughput_total_mbps"] = round((size_download * 8) / t_total / 1_000_000, 6)
        transfer_only_sec = max(t_total - t_ttfb, 0.0)
        if transfer_only_sec > 0:
            result["throughput_transfer_mbps"] = round((size_download * 8) / transfer_only_sec / 1_000_000, 6)
        result["download_complete"] = size_download == expected_bytes if expected_bytes is not None else size_download > 0
        return result

    def single_upload_run(self, cfg: dict, connect_timeout: int) -> dict:
        expected_bytes = int(cfg["expected_bytes"])
        payload = self.ensure_upload_payload(
            cfg["payload_path"],
            expected_bytes,
            cfg.get("payload_source", "zero"),
        )
        max_time = int(cfg.get("max_time_sec", 60))
        cmd = [
            "curl",
            "-L",
            "-o",
            "/dev/null",
            "-sS",
            "-X",
            "POST",
            "-H",
            "Content-Type: application/octet-stream",
            "--data-binary",
            f"@{payload['path']}",
            "--connect-timeout",
            str(connect_timeout),
            "--max-time",
            str(max_time),
            "-w",
            "%{http_code} %{time_namelookup} %{time_connect} %{time_appconnect} %{time_starttransfer} %{time_total} %{size_upload}",
            cfg["url"],
        ]

        rc, out, err = self.run(cmd, timeout=max_time + 10)
        result = self.empty_run_result("upload", rc, err)
        result["upload_payload"] = payload
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

        self.fill_http_metrics(result, http_status, t_dns, t_connect, t_tls, t_ttfb, t_total)
        result["http_upload_bytes"] = size_upload
        if t_total > 0:
            result["upload_throughput_total_mbps"] = round((size_upload * 8) / t_total / 1_000_000, 6)
        transfer_only_sec = max(t_total - t_ttfb, 0.0)
        if transfer_only_sec > 0:
            result["upload_throughput_transfer_mbps"] = round((size_upload * 8) / transfer_only_sec / 1_000_000, 6)
        result["upload_complete"] = size_upload == expected_bytes
        return result

    @staticmethod
    def _metric_stats(values: Iterable[float]) -> dict | None:
        values = list(values)
        if not values:
            return None
        return {
            "count": len(values),
            "min": round(min(values), 6),
            "avg": round(statistics.mean(values), 6),
            "median": round(statistics.median(values), 6),
            "p95": round(percentile(values, 95) or values[-1], 6),
            "max": round(max(values), 6),
        }

    def summarize(self, runs: list[dict], direction: str) -> dict:
        summary: dict = {}
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
            metrics.extend(
                [
                    "http_upload_bytes",
                    "upload_throughput_total_mbps",
                    "upload_throughput_transfer_mbps",
                ]
            )
        else:
            metrics.extend(
                [
                    "http_download_bytes",
                    "throughput_total_mbps",
                    "throughput_transfer_mbps",
                ]
            )

        for metric in metrics:
            numeric_values = [row[metric] for row in runs if isinstance(row.get(metric), (int, float))]
            summary[metric] = self._metric_stats(numeric_values)

        successful_runs = [
            row for row in runs
            if row.get("curl_rc") == 0 and row.get("http_status") and 200 <= row["http_status"] < 400
        ]
        health = {
            "total_runs": len(runs),
            "successful_http_runs": len(successful_runs),
            "failed_runs": len(runs) - len(successful_runs),
            "curl_reasons_seen": sorted({row.get("curl_reason") for row in runs if row.get("curl_reason")}),
        }
        if direction == "upload":
            health["upload_complete_true"] = sum(1 for row in runs if row.get("upload_complete") is True)
            health["upload_complete_false"] = sum(1 for row in runs if row.get("upload_complete") is False)
        else:
            health["download_complete_true"] = sum(1 for row in runs if row.get("download_complete") is True)
            health["download_complete_false"] = sum(1 for row in runs if row.get("download_complete") is False)
        summary["run_health"] = health
        return summary

    def run_direction(self, direction: str, cfg: dict, connect_timeout: int) -> tuple[list[dict], list[dict], dict]:
        if not cfg.get("enabled", False):
            return [], [], {}

        warmup_runs: list[dict] = []
        measurement_runs: list[dict] = []
        warmup = int(cfg.get("warmup", 0))
        runs = int(cfg.get("runs", 1))
        pause_sec = float(cfg.get("pause_sec", 1))

        runner = self.single_upload_run if direction == "upload" else self.single_download_run

        for idx in range(warmup):
            warmup_runs.append(runner(cfg, connect_timeout))
            if idx < warmup - 1:
                time.sleep(pause_sec)

        for idx in range(runs):
            measurement_runs.append(runner(cfg, connect_timeout))
            if idx < runs - 1:
                time.sleep(pause_sec)

        return warmup_runs, measurement_runs, self.summarize(measurement_runs, direction)

    def collect(self) -> dict:
        self._seq += 1

        connect_timeout = int(self.probe_cfg.get("connect_timeout_sec", 5))
        routine_cfg = self.probe_cfg["routine"]
        download_cfg = dict(routine_cfg.get("download", {}))
        upload_cfg = dict(routine_cfg.get("upload", {}))

        sample = sample_header(self.device_cfg, "throughput", self._seq)
        sample["wifi"] = collect_wifi_details(self.device_cfg["iface"])
        sample["network"] = collect_network_details(self.device_cfg["iface"])
        sample["config_used"] = {
            "connect_timeout_sec": connect_timeout,
            "download": download_cfg,
            "upload": upload_cfg,
        }
        (
            sample["download_warmup_runs"],
            sample["download_measurement_runs"],
            download_summary,
        ) = self.run_direction("download", download_cfg, connect_timeout)
        (
            sample["upload_warmup_runs"],
            sample["upload_measurement_runs"],
            upload_summary,
        ) = self.run_direction("upload", upload_cfg, connect_timeout)
        sample["summary"] = {
            "download": download_summary,
            "upload": upload_summary,
        }
        return sample
