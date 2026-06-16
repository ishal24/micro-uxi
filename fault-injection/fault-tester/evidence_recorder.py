#!/usr/bin/env python3
"""
Evidence bundle writer for Micro-UXI fault-tester runs.

The recorder is intentionally passive: it observes monitor stdout, records
probe samples with the current lifecycle phase, and captures diagnostic command
output at run boundaries.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


PROBE_RE = re.compile(r"^\[(?P<probe_time>\d{2}:\d{2}:\d{2})\]\s+(?P<event_code>S\d+)\s+Probe\s+\|\s+(?P<body>.*)$")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return None


class EvidenceRecorder:
    def __init__(
        self,
        bundle_dir: Path,
        run_id: str,
        event_code: str,
        expected_event_type: str,
        tester_config: dict[str, Any],
        pre_event_sec: int = 30,
        post_event_sec: int = 30,
    ) -> None:
        self.bundle_dir = bundle_dir
        self.run_id = run_id
        self.event_code = event_code
        self.expected_event_type = expected_event_type
        self.tester_config = tester_config
        self.pre_event_sec = max(0, int(pre_event_sec))
        self.post_event_sec = max(0, int(post_event_sec))
        self.pre_buffer: deque[dict[str, Any]] = deque()
        self.event_index = 0
        self.current_event: dict[str, Any] | None = None
        self.post_event_until: datetime | None = None

        self.bundle_dir.mkdir(parents=True, exist_ok=True)

    def current_phase(self) -> str:
        if self.current_event and self.current_event["state"] == "event":
            return "event"
        if self.current_event and self.current_event["state"] == "post_event":
            return "post_event"
        return "pre_event"

    def record_monitor_line(self, line: str) -> None:
        match = PROBE_RE.match(line)
        if not match:
            return

        observed_at = datetime.now().astimezone()
        record = {
            "record_type": "probe_sample",
            "timestamp": observed_at.isoformat(timespec="seconds"),
            "run_id": self.run_id,
            "event_code": self.event_code,
            "expected_event_type": self.expected_event_type,
            "phase": self.current_phase(),
            "probe_event_code": match.group("event_code").upper(),
            "probe_time_local": match.group("probe_time"),
            "raw_sample": match.group("body"),
            "parsed_metrics": self._parse_probe_body(match.group("body")),
        }

        self._close_post_event_if_due(observed_at)
        self.pre_buffer.append(record)
        self._trim_pre_buffer(observed_at)

        if self.current_event:
            self._append_timeline(self.current_event["timeline_path"], record)
            self._close_post_event_if_due(observed_at)
            return

    def record_detection_event(self, status: str, detected_event_code: str, detected_event_type: str) -> None:
        status = status.upper()
        if status == "ALARM":
            self._start_event(detected_event_code, detected_event_type)
            phase = "event"
        elif status == "RECOVERY":
            if self.current_event is None:
                self._start_event(detected_event_code, detected_event_type)
            if self.current_event:
                self.current_event["state"] = "post_event"
                self.post_event_until = datetime.now().astimezone() + timedelta(seconds=self.post_event_sec)
            phase = "post_event"
        else:
            phase = self.current_phase()

        record = {
            "record_type": "detection_event",
            "timestamp": now_iso(),
            "run_id": self.run_id,
            "event_code": self.event_code,
            "expected_event_type": self.expected_event_type,
            "phase": phase,
            "status": status,
            "detected_event_code": detected_event_code,
            "detected_event_type": detected_event_type,
        }
        if self.current_event:
            self._append_timeline(self.current_event["timeline_path"], record)
            if status == "ALARM":
                self.capture_diagnostic_snapshot("alarm")
            elif status == "RECOVERY":
                self.capture_diagnostic_snapshot("recovery")

    def capture_diagnostic_snapshot(self, label: str) -> None:
        if self.current_event is None:
            return

        snapshot_path = self.current_event["snapshot_path"]
        snapshot = self._load_snapshot_document(snapshot_path)
        snapshot["snapshots"].append(
            {
                "label": label,
                "timestamp": now_iso(),
                "rcs_coverage": {
                    "M4_wifi_diagnostic": "wifi",
                    "M5_ip_configuration": "ip_configuration",
                    "M6_routing_diagnostic": "routing",
                    "M7_dns_resolver": "dns_resolver",
                },
                "wifi": self._wifi_snapshot(),
                "ip_configuration": self._ip_configuration_snapshot(),
                "routing": self._routing_snapshot(),
                "dns_resolver": self._dns_resolver_snapshot(),
                "commands": {
                    "ip_brief_addr": self._run_command(["ip", "-brief", "addr"]),
                    "ip_route": self._run_command(["ip", "route"]),
                    "ip_link": self._run_command(["ip", "link"]),
                },
            }
        )
        snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def close(self) -> None:
        if self.current_event:
            self._append_timeline(
                self.current_event["timeline_path"],
                {
                    "record_type": "evidence_closed",
                    "timestamp": now_iso(),
                    "run_id": self.run_id,
                    "event_code": self.event_code,
                    "expected_event_type": self.expected_event_type,
                    "phase": self.current_phase(),
                    "reason": "monitor_stop",
                },
            )
            self.capture_diagnostic_snapshot("monitor_stop")
            self.current_event = None
            self.post_event_until = None

    def _append_timeline(self, path: Path, record: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            fh.flush()

    def _load_snapshot_document(self, snapshot_path: Path) -> dict[str, Any]:
        if snapshot_path.exists():
            try:
                with snapshot_path.open("r", encoding="utf-8") as fh:
                    loaded = json.load(fh)
                if isinstance(loaded, dict) and isinstance(loaded.get("snapshots"), list):
                    return loaded
            except Exception:
                pass

        return {
            "run_id": self.run_id,
            "event_code": self.event_code,
            "expected_event_type": self.expected_event_type,
            "created_at": now_iso(),
            "bundle_dir": str(self.bundle_dir),
            "event_occurrence": self.current_event["event_occurrence"] if self.current_event else None,
            "snapshots": [],
        }

    def _start_event(self, detected_event_code: str, detected_event_type: str) -> None:
        if self.current_event:
            self.capture_diagnostic_snapshot("interrupted_by_next_alarm")
            self.current_event = None
            self.post_event_until = None

        self.event_index += 1
        ts = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")
        prefix = f"{self.event_code}_{detected_event_type}_{ts}_{self.event_index:02d}"
        timeline_path = self.bundle_dir / f"{prefix}_evidence_timeline.jsonl"
        snapshot_path = self.bundle_dir / f"{prefix}_diagnostic_snapshot.json"

        self.current_event = {
            "state": "event",
            "event_occurrence": self.event_index,
            "timeline_path": timeline_path,
            "snapshot_path": snapshot_path,
        }
        self.post_event_until = None
        timeline_path.write_text("", encoding="utf-8")

        metadata = {
            "record_type": "event_metadata",
            "timestamp": now_iso(),
            "run_id": self.run_id,
            "event_code": self.event_code,
            "expected_event_type": self.expected_event_type,
            "event_occurrence": self.event_index,
            "detected_event_code": detected_event_code,
            "detected_event_type": detected_event_type,
            "pre_event_sec": self.pre_event_sec,
            "post_event_sec": self.post_event_sec,
            "phase_policy": {
                "pre_event": f"last {self.pre_event_sec} seconds before ALARM",
                "event": "from ALARM until RECOVERY",
                "post_event": f"from RECOVERY until {self.post_event_sec} seconds after recovery or monitor stop",
            },
            "files": {
                "timeline": timeline_path.name,
                "snapshot": snapshot_path.name,
            },
        }
        self._append_timeline(timeline_path, metadata)

        for buffered in self.pre_buffer:
            replayed = dict(buffered)
            replayed["phase"] = "pre_event"
            replayed["record_type"] = "pre_event_sample"
            self._append_timeline(timeline_path, replayed)

    def _trim_pre_buffer(self, now: datetime) -> None:
        if self.pre_event_sec <= 0:
            self.pre_buffer.clear()
            return

        cutoff = now - timedelta(seconds=self.pre_event_sec)
        while self.pre_buffer:
            timestamp = self.pre_buffer[0].get("timestamp")
            try:
                sample_time = datetime.fromisoformat(timestamp)
            except (TypeError, ValueError):
                break
            if sample_time >= cutoff:
                break
            self.pre_buffer.popleft()

    def _close_post_event_if_due(self, observed_at: datetime) -> None:
        if not self.current_event or self.current_event["state"] != "post_event":
            return
        if self.post_event_until is None or observed_at < self.post_event_until:
            return

        self._append_timeline(
            self.current_event["timeline_path"],
            {
                "record_type": "evidence_closed",
                "timestamp": observed_at.isoformat(timespec="seconds"),
                "run_id": self.run_id,
                "event_code": self.event_code,
                "expected_event_type": self.expected_event_type,
                "phase": "post_event",
                "reason": "post_event_window_complete",
            },
        )
        self.capture_diagnostic_snapshot("post_event_complete")
        self.current_event = None
        self.post_event_until = None

    def _wifi_snapshot(self) -> dict[str, Any]:
        iface = ((self.tester_config.get("targets") or {}).get("iface") or "").strip()
        if not iface:
            return {"iface": None}

        sys_net = Path("/sys/class/net") / iface
        iw_link = self._run_command(["iw", "dev", iface, "link"])
        return {
            "iface": iface,
            "operstate": _read_text(sys_net / "operstate"),
            "carrier": _read_text(sys_net / "carrier"),
            "address": _read_text(sys_net / "address"),
            "mtu": _read_text(sys_net / "mtu"),
            "wireless_link": self._parse_iw_link(iw_link["stdout"]),
            "commands": {
                "iw_link": iw_link,
            },
        }

    def _ip_configuration_snapshot(self) -> dict[str, Any]:
        iface = ((self.tester_config.get("targets") or {}).get("iface") or "").strip()
        addr_cmd = ["ip", "-j", "addr"]
        if iface:
            addr_cmd.extend(["show", "dev", iface])

        ip_addr = self._run_json_command(addr_cmd)
        default_route = self._run_json_command(["ip", "-j", "route", "show", "default"])

        return {
            "iface": iface or None,
            "addresses": ip_addr,
            "default_route": default_route,
        }

    def _routing_snapshot(self) -> dict[str, Any]:
        return {
            "routes": self._run_json_command(["ip", "-j", "route"]),
            "rules": self._run_command(["ip", "rule"]),
        }

    def _dns_resolver_snapshot(self) -> dict[str, Any]:
        resolvectl = self._run_first_available(
            [
                ["resolvectl", "status"],
                ["systemd-resolve", "--status"],
            ]
        )
        resolv_conf = self._read_file("/etc/resolv.conf")
        nameservers: list[str] = []
        if resolv_conf.get("ok"):
            for line in resolv_conf.get("content", "").splitlines():
                stripped = line.strip()
                if stripped.startswith("nameserver "):
                    nameservers.append(stripped.split(None, 1)[1])

        return {
            "nameservers": nameservers,
            "resolv_conf": resolv_conf,
            "resolvectl_status": resolvectl,
        }

    def _run_first_available(self, commands: list[list[str]]) -> dict[str, Any]:
        for cmd in commands:
            result = self._run_command(cmd)
            if result["returncode"] != 127:
                return result
        return result

    def _run_command(self, cmd: list[str]) -> dict[str, Any]:
        try:
            completed = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            return {
                "command": cmd,
                "returncode": completed.returncode,
                "stdout": completed.stdout.strip(),
                "stderr": completed.stderr.strip(),
            }
        except FileNotFoundError as exc:
            return {
                "command": cmd,
                "returncode": 127,
                "stdout": "",
                "stderr": str(exc),
            }
        except subprocess.TimeoutExpired as exc:
            return {
                "command": cmd,
                "returncode": 124,
                "stdout": (exc.stdout or "").strip() if isinstance(exc.stdout, str) else "",
                "stderr": "command timed out",
            }
        except Exception as exc:
            return {
                "command": cmd,
                "returncode": -1,
                "stdout": "",
                "stderr": str(exc),
            }

    def _run_json_command(self, cmd: list[str]) -> dict[str, Any]:
        result = self._run_command(cmd)
        parsed = None
        if result["returncode"] == 0 and result["stdout"]:
            try:
                parsed = json.loads(result["stdout"])
            except json.JSONDecodeError:
                parsed = None
        return {
            "command": result["command"],
            "returncode": result["returncode"],
            "data": parsed,
            "stderr": result["stderr"],
        }

    def _read_file(self, path: str) -> dict[str, Any]:
        target = Path(path)
        try:
            return {
                "path": path,
                "ok": True,
                "content": target.read_text(encoding="utf-8").strip(),
            }
        except Exception as exc:
            return {
                "path": path,
                "ok": False,
                "error": str(exc),
            }

    def _parse_probe_body(self, body: str) -> dict[str, Any]:
        metrics: dict[str, Any] = {}

        wifi_match = re.search(r"\bwifi=(UP|DOWN)\b", body)
        if wifi_match:
            metrics["wifi"] = wifi_match.group(1)

        ping_match = re.search(r"\bping=(OK|FAIL)\b", body)
        if ping_match:
            metrics["ping"] = ping_match.group(1)

        rtt_match = re.search(r"\brtt=([0-9.]+)ms\b", body)
        if rtt_match:
            metrics["rtt_ms"] = float(rtt_match.group(1))

        loss_match = re.search(r"\bloss=([0-9.]+)%", body)
        if loss_match:
            metrics["loss_pct"] = float(loss_match.group(1))

        hits_match = re.search(r"\bhits=(\d+)/(\d+)\b", body)
        if hits_match:
            metrics["hits"] = int(hits_match.group(1))
            metrics["hits_required"] = int(hits_match.group(2))

        window_match = re.search(r"\bwindow=(\d+)\b", body)
        if window_match:
            metrics["window"] = int(window_match.group(1))

        fails_match = re.search(r"\bfails=(\d+)\b", body)
        if fails_match:
            metrics["fails"] = int(fails_match.group(1))

        transitions_match = re.search(r"\btransitions=(\d+)\b", body)
        if transitions_match:
            metrics["transitions"] = int(transitions_match.group(1))

        conn_ok_match = re.search(r"\bconn_ok=(True|False)\b", body)
        if conn_ok_match:
            metrics["connectivity_ok"] = conn_ok_match.group(1) == "True"

        window_loss_match = re.search(r"\((\d+(?:\.\d+)?)%\)", body)
        if window_loss_match and "loss_pct" not in metrics:
            metrics["loss_pct"] = float(window_loss_match.group(1))

        http_match = re.search(r"=(\d{3})/([0-9.]+)ms", body)
        if http_match:
            metrics["http_status"] = int(http_match.group(1))
            metrics["http_total_ms"] = float(http_match.group(2))

        http_ttfb_match = re.search(r"\bttfb=([0-9.]+)ms\b", body)
        if http_ttfb_match:
            metrics["http_ttfb_ms"] = float(http_ttfb_match.group(1))

        http_fail_match = re.search(r"=FAIL\(rc=([-0-9]+)\)", body)
        if http_fail_match:
            metrics["http_success"] = False
            metrics["curl_rc"] = int(http_fail_match.group(1))

        dynamic_thresholds: dict[str, Any] = {}
        for label, value in re.findall(r"\b([A-Za-z0-9_]*dyn_thr)=([0-9.]+)ms\b", body):
            dynamic_thresholds[label] = float(value)
        for label, value in re.findall(r"\b([A-Za-z0-9_]*base)=([0-9.]+)ms\b", body):
            dynamic_thresholds[label] = float(value)
        for label, value in re.findall(r"\b([A-Za-z0-9_]*mode)=(static|dynamic)\b", body):
            dynamic_thresholds[label] = value
        for label, count, required in re.findall(r"\b([A-Za-z0-9_]*n)=(\d+)/(\d+)\b", body):
            dynamic_thresholds[label] = {
                "sample_count": int(count),
                "min_samples": int(required),
            }
        if dynamic_thresholds:
            metrics["dynamic_thresholds"] = dynamic_thresholds

        dns_match = re.search(r"dns=\[(?P<dns>[^\]]*)\]", body)
        if dns_match:
            dns_body = dns_match.group("dns")
            dns_latencies = {
                name: float(value)
                for name, value in re.findall(r"([A-Za-z0-9_.-]+)=([0-9.]+)ms", dns_body)
            }
            if dns_latencies:
                metrics["dns_latency_ms"] = dns_latencies

            dns_statuses = {
                name: status
                for name, status in re.findall(r"([A-Za-z0-9_.-]+)=(OK|FAIL)", dns_body)
            }
            if dns_statuses:
                metrics["dns_status"] = dns_statuses

        return metrics

    def _parse_iw_link(self, stdout: str) -> dict[str, Any]:
        if not stdout:
            return {"connected": None}
        if "Not connected" in stdout:
            return {"connected": False}

        parsed: dict[str, Any] = {"connected": "Connected to" in stdout}

        bssid_match = re.search(r"Connected to\s+([0-9a-fA-F:]{17})", stdout)
        if bssid_match:
            parsed["bssid"] = bssid_match.group(1)

        ssid_match = re.search(r"^\s*SSID:\s*(.+)$", stdout, re.MULTILINE)
        if ssid_match:
            parsed["ssid"] = ssid_match.group(1).strip()

        freq_match = re.search(r"^\s*freq:\s*(\d+)$", stdout, re.MULTILINE)
        if freq_match:
            parsed["frequency_mhz"] = int(freq_match.group(1))

        signal_match = re.search(r"^\s*signal:\s*(-?\d+(?:\.\d+)?)\s*dBm", stdout, re.MULTILINE)
        if signal_match:
            parsed["rssi_dbm"] = float(signal_match.group(1))

        bitrate_match = re.search(r"^\s*tx bitrate:\s*(.+)$", stdout, re.MULTILINE)
        if bitrate_match:
            parsed["tx_bitrate"] = bitrate_match.group(1).strip()

        return parsed
