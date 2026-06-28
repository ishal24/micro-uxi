from __future__ import annotations

import json
import math
import queue
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from probe.utils import append_jsonl


class EwmaThreshold:
    def __init__(
        self,
        static_threshold: float,
        warmup_samples: int,
        alpha: float,
        beta: float,
        k: float,
        enabled: bool = True,
    ) -> None:
        self.static_threshold = float(static_threshold)
        self.warmup_samples = max(1, int(warmup_samples))
        self.alpha = float(alpha)
        self.beta = float(beta)
        self.k = float(k)
        self.enabled = bool(enabled)
        self.sample_count = 0
        self.mu: float | None = None
        self.v = 0.0

    def threshold(self) -> dict[str, Any]:
        if not self.enabled:
            return self._state(self.static_threshold, "baseline")
        if self.mu is None or self.sample_count < self.warmup_samples:
            return self._state(float("inf"), "warmup")
        return self._state(self.mu + self.k * math.sqrt(max(self.v, 0.0)), "dynamic")

    def evaluate(self, value: float, update: bool = True) -> dict[str, Any]:
        observed = float(value)
        info = self.threshold()
        exceeded = observed >= info["value"]

        if update and (not self.enabled or not exceeded):
            self._update(observed)

        return {
            **info,
            "observed": observed,
            "exceeded": exceeded,
        }

    def _update(self, value: float) -> None:
        if self.mu is None:
            self.mu = value
            self.v = 0.0
            self.sample_count = 1
            return

        prev_mu = self.mu
        self.mu = self.alpha * value + (1 - self.alpha) * prev_mu
        self.v = self.beta * ((value - prev_mu) ** 2) + (1 - self.beta) * self.v
        self.sample_count += 1

    def _state(self, threshold_value: float, mode: str) -> dict[str, Any]:
        return {
            "value": float(threshold_value),
            "mode": mode,
            "mu": self.mu,
            "variance": self.v,
            "std": math.sqrt(max(self.v, 0.0)),
            "sample_count": self.sample_count,
        }


class DetectionRuntime:
    def __init__(self, runtime_config: dict[str, Any], detection_config: dict[str, Any], output_dir: Path):
        self.runtime_config = runtime_config
        self.config = detection_config
        self.module_cfg = detection_config["detection"]
        self.output_path = output_dir / self.module_cfg.get("output_filename", "detection.jsonl")
        self.write_jsonl = bool(self.module_cfg.get("write_jsonl", False))
        self.verbose_terminal = bool(self.module_cfg.get("verbose_terminal", True))
        self.mode = str(self.module_cfg.get("mode", "baseline")).lower()
        self.stop_event = threading.Event()
        self.sample_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self.thread: threading.Thread | None = None
        self.print_lock = threading.Lock()
        self.histories = {
            "s2_dns": deque(maxlen=int(self.config["events"]["S2_DNS_TIMEOUT_BURST"]["rules"]["n_dns"])),
            "s3_ping": deque(maxlen=int(self.config["events"]["S3_LOSS_BURST"]["rules"]["n_ping"])),
            "s6_conn": deque(maxlen=int(self.config["events"]["S6_CONNECTIVITY_FLAP"]["rules"]["n_flap"])),
            "s6_wifi": deque(maxlen=int(self.config["events"]["S6_CONNECTIVITY_FLAP"]["rules"]["n_flap"])),
            "s6_ping": deque(maxlen=int(self.config["events"]["S6_CONNECTIVITY_FLAP"]["rules"]["n_flap"])),
        }
        self.state = {
            "S1_DNS_DEGRADED": {"active": False, "hits": 0, "oks": 0},
            "S2_DNS_TIMEOUT_BURST": {"active": False},
            "S3_LOSS_BURST": {"active": False},
            "S4_HIGH_RTT": {"active": False, "hits": 0, "oks": 0},
            "S5_HTTP_SLOW": {"active": False, "hits": 0, "oks": 0},
            "S6_CONNECTIVITY_FLAP": {"active": False, "disconnect_hits": 0, "recovery_hits": 0},
        }
        self.dynamic_thresholds = self._build_dynamic_thresholds()
        self.sample_count = 0
        self.event_count = 0
        self.error_count = 0

    def _build_dynamic_thresholds(self) -> dict[str, dict[str, EwmaThreshold]]:
        dyn_cfg = self.config.get("dynamic_thresholds", {})
        events_cfg = dyn_cfg.get("events", {})

        def build(event_key: str, metric_key: str, static_value: float) -> EwmaThreshold:
            metric_cfg = (events_cfg.get(event_key, {}) or {}).get(metric_key, {})
            if not metric_cfg:
                return EwmaThreshold(static_value, 1, 0.1, 0.1, 3, enabled=False)
            return EwmaThreshold(
                static_threshold=static_value,
                warmup_samples=metric_cfg.get("warmup_samples", 1),
                alpha=metric_cfg.get("alpha", 0.1),
                beta=metric_cfg.get("beta", 0.1),
                k=metric_cfg.get("k", 3),
                enabled=self.mode == "dynamic",
            )

        thresholds = self.config["thresholds"]
        return {
            "S1_DNS_DEGRADED": {
                "dns_latency_ms": build("S1_DNS_DEGRADED", "dns_latency_ms", thresholds["dns_latency_threshold_ms"]),
            },
            "S4_HIGH_RTT": {
                "rtt_ms": build("S4_HIGH_RTT", "rtt_ms", thresholds["rtt_threshold_ms"]),
            },
            "S5_HTTP_SLOW": {
                "http_total_ms": build("S5_HTTP_SLOW", "http_total_ms", thresholds["http_total_threshold_ms"]),
                "http_ttfb_ms": build("S5_HTTP_SLOW", "http_ttfb_ms", thresholds["http_ttfb_threshold_ms"]),
            },
        }

    def start(self) -> None:
        self.thread = threading.Thread(target=self.run_forever, daemon=True, name="detection")
        self.thread.start()

    def join(self) -> None:
        if self.thread is not None:
            self.thread.join(timeout=10)

    def submit_sample(self, sample: dict[str, Any]) -> None:
        self.sample_queue.put(sample)

    def _print(self, line: str) -> None:
        with self.print_lock:
            print(line, flush=True)

    def _emit_transition(self, event_key: str, status: str, sample: dict[str, Any], detail: dict[str, Any]) -> None:
        self.event_count += 1 if status == "ALARM" else 0
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "module": "detection",
            "status": status,
            "event_key": event_key,
            "mode": self.mode,
            "probe_type": sample.get("probe_type"),
            "sample_ts": sample.get("ts"),
            "sample_seq": sample.get("seq"),
            "detail": detail,
        }
        if self.write_jsonl:
            append_jsonl(self.output_path, record)
        if self.verbose_terminal:
            self._print(f"[DETECTION {status}] {event_key} probe={sample.get('probe_type')} seq={sample.get('seq')} detail={json.dumps(detail, ensure_ascii=False)}")

    def _transition_count(self, history: deque[bool]) -> int:
        transitions = 0
        prev: bool | None = None
        for current in history:
            if prev is not None and current != prev:
                transitions += 1
            prev = current
        return transitions

    def _handle_s1(self, sample: dict[str, Any]) -> None:
        if sample.get("probe_type") != "fast":
            return
        event_cfg = self.config["events"]["S1_DNS_DEGRADED"]
        rules = event_cfg["rules"]
        state = self.state["S1_DNS_DEGRADED"]
        wifi_up = bool((sample.get("wifi") or {}).get("wifi_up"))
        ping_ok = bool((sample.get("ping") or {}).get("success"))
        dns_rows = sample.get("dns") or []
        threshold = self.dynamic_thresholds["S1_DNS_DEGRADED"]["dns_latency_ms"]
        hit = False
        affected_scope: set[str] = set()
        worst_latency = None
        threshold_info = None

        if wifi_up and ping_ok:
            for row in dns_rows:
                if not row.get("success") or row.get("latency_ms") is None:
                    continue
                threshold_info = threshold.evaluate(float(row["latency_ms"]), update=not state["active"])
                if threshold_info["exceeded"]:
                    hit = True
                    affected_scope.add(row.get("scope", "unknown"))
                    worst_latency = max(worst_latency or 0.0, float(row["latency_ms"]))

        if hit:
            state["hits"] += 1
            state["oks"] = 0
        else:
            state["hits"] = 0
            state["oks"] += 1

        if not state["active"] and state["hits"] >= rules["confirm_consecutive"]:
            state["active"] = True
            self._emit_transition(
                "S1_DNS_DEGRADED",
                "ALARM",
                sample,
                {
                    "affected_scope": sorted(affected_scope),
                    "worst_latency_ms": worst_latency,
                    "threshold": threshold_info,
                },
            )
        elif state["active"] and state["oks"] >= rules["recovery_consecutive"]:
            state["active"] = False
            self._emit_transition("S1_DNS_DEGRADED", "RECOVERY", sample, {"recovery_consecutive": state["oks"]})

    def _handle_s2(self, sample: dict[str, Any]) -> None:
        if sample.get("probe_type") != "fast":
            return
        event_cfg = self.config["events"]["S2_DNS_TIMEOUT_BURST"]
        rules = event_cfg["rules"]
        state = self.state["S2_DNS_TIMEOUT_BURST"]
        wifi_up = bool((sample.get("wifi") or {}).get("wifi_up"))
        ping_ok = bool((sample.get("ping") or {}).get("success"))
        dns_rows = sample.get("dns") or []
        dns_all_ok = all(row.get("success") for row in dns_rows) if dns_rows else False

        if wifi_up and ping_ok and dns_rows:
            self.histories["s2_dns"].append(dns_all_ok)

        history = self.histories["s2_dns"]
        fail_count = sum(1 for ok in history if not ok)
        if len(history) == rules["n_dns"] and not state["active"] and fail_count >= rules["m_dns"]:
            state["active"] = True
            self._emit_transition("S2_DNS_TIMEOUT_BURST", "ALARM", sample, {"fail_count": fail_count, "window": len(history)})
        elif state["active"] and len(history) == rules["n_dns"] and fail_count == 0:
            state["active"] = False
            self._emit_transition("S2_DNS_TIMEOUT_BURST", "RECOVERY", sample, {"window": len(history)})

    def _handle_s3(self, sample: dict[str, Any]) -> None:
        if sample.get("probe_type") != "fast":
            return
        event_cfg = self.config["events"]["S3_LOSS_BURST"]
        rules = event_cfg["rules"]
        state = self.state["S3_LOSS_BURST"]
        wifi_up = bool((sample.get("wifi") or {}).get("wifi_up"))
        ping_ok = bool((sample.get("ping") or {}).get("success"))

        if wifi_up:
            self.histories["s3_ping"].append(ping_ok)

        history = self.histories["s3_ping"]
        fail_count = sum(1 for ok in history if not ok)
        if len(history) == rules["n_ping"] and not state["active"] and fail_count >= rules["m_ping"]:
            state["active"] = True
            self._emit_transition("S3_LOSS_BURST", "ALARM", sample, {"fail_count": fail_count, "window": len(history)})
        elif state["active"] and len(history) == rules["n_ping"] and fail_count < rules["recovery_max_failures"]:
            state["active"] = False
            self._emit_transition("S3_LOSS_BURST", "RECOVERY", sample, {"fail_count": fail_count, "window": len(history)})

    def _handle_s4(self, sample: dict[str, Any]) -> None:
        if sample.get("probe_type") != "telemetry":
            return
        event_cfg = self.config["events"]["S4_HIGH_RTT"]
        rules = event_cfg["rules"]
        thresholds = self.config["thresholds"]
        state = self.state["S4_HIGH_RTT"]
        ping = sample.get("ping") or {}
        wifi_connected = bool((sample.get("wifi") or {}).get("wifi_connected"))
        rtt = ping.get("rtt_avg_ms")
        loss = ping.get("loss_pct")
        threshold = self.dynamic_thresholds["S4_HIGH_RTT"]["rtt_ms"]
        threshold_info = None
        hit = False

        if wifi_connected and rtt is not None and (loss is None or loss < thresholds["loss_threshold_pct"]):
            threshold_info = threshold.evaluate(float(rtt), update=not state["active"])
            hit = threshold_info["exceeded"]

        if hit:
            state["hits"] += 1
            state["oks"] = 0
        else:
            state["hits"] = 0
            state["oks"] += 1

        if not state["active"] and state["hits"] >= rules["confirm_consecutive"]:
            state["active"] = True
            self._emit_transition("S4_HIGH_RTT", "ALARM", sample, {"rtt_avg_ms": rtt, "loss_pct": loss, "threshold": threshold_info})
        elif state["active"] and state["oks"] >= rules["recovery_consecutive"]:
            state["active"] = False
            self._emit_transition("S4_HIGH_RTT", "RECOVERY", sample, {"rtt_avg_ms": rtt, "loss_pct": loss})

    def _handle_s5(self, sample: dict[str, Any]) -> None:
        if sample.get("probe_type") != "telemetry":
            return
        event_cfg = self.config["events"]["S5_HTTP_SLOW"]
        rules = event_cfg["rules"]
        state = self.state["S5_HTTP_SLOW"]
        wifi_connected = bool((sample.get("wifi") or {}).get("wifi_connected"))
        ping = sample.get("ping") or {}
        dns_rows = sample.get("dns") or []
        http_rows = sample.get("http") or []
        total_threshold = self.dynamic_thresholds["S5_HTTP_SLOW"]["http_total_ms"]
        ttfb_threshold = self.dynamic_thresholds["S5_HTTP_SLOW"]["http_ttfb_ms"]
        hit = False
        matched: list[dict[str, Any]] = []

        if wifi_connected:
            ping_fail_count = sum(1 for ok in self.histories["s3_ping"] if not ok)
            rtt_ok = ping.get("rtt_avg_ms") is None or ping.get("rtt_avg_ms", 0) < self.config["thresholds"]["rtt_threshold_ms"]
            dns_fast_ok = all(
                (row.get("success") and (row.get("latency_ms") or 0) < self.config["thresholds"]["dns_latency_threshold_ms"])
                for row in dns_rows
            ) if dns_rows else True
            loss_ok = ping_fail_count < self.config["events"]["S3_LOSS_BURST"]["rules"]["m_ping"]

            if rtt_ok and dns_fast_ok and loss_ok:
                for row in http_rows:
                    detail: dict[str, Any] = {"host": row.get("host"), "scope": row.get("scope")}
                    if row.get("curl_rc") not in (None, 0, 6):
                        hit = True
                        detail["reason"] = "curl_rc"
                        detail["curl_rc"] = row.get("curl_rc")
                        matched.append(detail)
                        continue
                    if row.get("http_status") is not None:
                        status = int(row["http_status"])
                        if status < 200 or status >= 400:
                            hit = True
                            detail["reason"] = "http_status"
                            detail["http_status"] = status
                            matched.append(detail)
                            continue
                    total_info = None
                    ttfb_info = None
                    if row.get("http_total_ms") is not None:
                        total_info = total_threshold.evaluate(float(row["http_total_ms"]), update=not state["active"])
                    if row.get("http_ttfb_ms") is not None:
                        ttfb_info = ttfb_threshold.evaluate(float(row["http_ttfb_ms"]), update=not state["active"])
                    if (total_info and total_info["exceeded"]) or (ttfb_info and ttfb_info["exceeded"]):
                        hit = True
                        detail["reason"] = "threshold"
                        detail["http_total"] = total_info
                        detail["http_ttfb"] = ttfb_info
                        matched.append(detail)

        if hit:
            state["hits"] += 1
            state["oks"] = 0
        else:
            state["hits"] = 0
            state["oks"] += 1

        if not state["active"] and state["hits"] >= rules["confirm_consecutive"]:
            state["active"] = True
            self._emit_transition("S5_HTTP_SLOW", "ALARM", sample, {"matched": matched})
        elif state["active"] and state["oks"] >= rules["recovery_consecutive"]:
            state["active"] = False
            self._emit_transition("S5_HTTP_SLOW", "RECOVERY", sample, {"recovery_consecutive": state["oks"]})

    def _handle_s6(self, sample: dict[str, Any]) -> None:
        if sample.get("probe_type") != "fast":
            return
        event_cfg = self.config["events"]["S6_CONNECTIVITY_FLAP"]
        rules = event_cfg["rules"]
        state = self.state["S6_CONNECTIVITY_FLAP"]
        wifi_up = bool((sample.get("wifi") or {}).get("wifi_up"))
        ping_ok = bool((sample.get("ping") or {}).get("success"))
        conn_ok = bool(sample.get("connectivity_ok"))

        self.histories["s6_conn"].append(conn_ok)
        self.histories["s6_wifi"].append(wifi_up)
        self.histories["s6_ping"].append(ping_ok)

        if not conn_ok:
            state["disconnect_hits"] += 1
            state["recovery_hits"] = 0
        else:
            state["disconnect_hits"] = 0
            state["recovery_hits"] += 1

        conn_history = self.histories["s6_conn"]
        if len(conn_history) < rules["n_flap"]:
            if not state["active"] and state["disconnect_hits"] >= rules["disconnect_consecutive"]:
                state["active"] = True
                layer = "wifi_link" if not wifi_up else "upstream"
                self._emit_transition(
                    "S6_CONNECTIVITY_FLAP",
                    "ALARM",
                    sample,
                    {
                        "reason": "sustained_disconnect",
                        "disconnect_hits": state["disconnect_hits"],
                        "suspected_layer": layer,
                    },
                )
            elif state["active"] and state["recovery_hits"] >= rules["recovery_consecutive"]:
                state["active"] = False
                self._emit_transition(
                    "S6_CONNECTIVITY_FLAP",
                    "RECOVERY",
                    sample,
                    {
                        "reason": "sustained_disconnect_recovered",
                        "recovery_hits": state["recovery_hits"],
                    },
                )
            return

        transitions = self._transition_count(conn_history)
        wifi_transitions = self._transition_count(self.histories["s6_wifi"])
        ping_transitions = self._transition_count(self.histories["s6_ping"])
        if not state["active"] and transitions >= rules["m_transition"]:
            state["active"] = True
            layer = "wifi_link" if wifi_transitions >= rules["m_transition"] else "upstream" if ping_transitions >= rules["m_transition"] else "unknown"
            self._emit_transition(
                "S6_CONNECTIVITY_FLAP",
                "ALARM",
                sample,
                {"reason": "transition_flap", "transitions": transitions, "suspected_layer": layer, "window": len(conn_history)},
            )
        elif state["active"]:
            if transitions < rules["recovery_max_transitions"] and state["recovery_hits"] >= rules["recovery_consecutive"]:
                state["active"] = False
                self._emit_transition(
                    "S6_CONNECTIVITY_FLAP",
                    "RECOVERY",
                    sample,
                    {"reason": "transition_flap_recovered", "transitions": transitions, "window": len(conn_history)},
                )

    def process_sample(self, sample: dict[str, Any]) -> None:
        self.sample_count += 1
        self._handle_s1(sample)
        self._handle_s2(sample)
        self._handle_s3(sample)
        self._handle_s4(sample)
        self._handle_s5(sample)
        self._handle_s6(sample)

    def run_forever(self) -> None:
        while not self.stop_event.is_set():
            try:
                sample = self.sample_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            try:
                self.process_sample(sample)
            except Exception as exc:  # pragma: no cover
                self.error_count += 1
                self._print(f"[DETECTION ERROR] {exc}")


def load_detection_config(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)
