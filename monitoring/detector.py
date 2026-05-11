from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from statistics import median
from typing import Any
from monitoring.utils import median_abs_deviation, parse_ts, utc_now_iso


EVENT_SPECS = {
    "DNS_DEGRADED": {"scenario_id": "S1_DNS_DEGRADED"},
    "DNS_TIMEOUT_BURST": {"scenario_id": "S2_DNS_TIMEOUT_BURST"},
    "LOSS_BURST": {"scenario_id": "S3_LOSS_BURST"},
    "HIGH_RTT": {"scenario_id": "S4_HIGH_RTT"},
    "HTTP_SLOW": {"scenario_id": "S5_HTTP_SLOW"},
    "CONNECTIVITY_FLAP": {"scenario_id": "S6_CONNECTIVITY_FLAP"},
    "BANDWIDTH_THROTTLE": {"scenario_id": "A1_BANDWIDTH_THROTTLE"},
}


@dataclass
class RollingBaseline:
    maxlen: int
    minimum_samples: int
    values: deque = field(init=False)

    def __post_init__(self) -> None:
        self.values = deque(maxlen=self.maxlen)

    def add(self, value: float | None) -> None:
        if value is None:
            return
        self.values.append(float(value))

    def stats(self) -> tuple[float, float] | None:
        if len(self.values) < self.minimum_samples:
            return None
        med = median(self.values)
        mad = median_abs_deviation(self.values)
        return med, mad if mad is not None else 0.0

    def trigger_threshold(self, static_threshold: float | None, k: float) -> float | None:
        stats = self.stats()
        if not stats:
            return static_threshold
        med, mad = stats
        dynamic = med + (k * mad)
        if static_threshold is None:
            return dynamic
        return max(static_threshold, dynamic)

    def recovery_threshold(self, static_threshold: float | None, k: float) -> float | None:
        stats = self.stats()
        if not stats:
            return static_threshold
        med, mad = stats
        dynamic = med + (k * mad)
        if static_threshold is None:
            return dynamic
        return min(static_threshold, dynamic)


@dataclass
class Evaluation:
    event_type: str
    hit: bool = False
    recovery_ok: bool = False
    affected_scope: str = "unknown"
    affected_targets: list[str] = field(default_factory=list)
    severity: str = "medium"
    trigger_reason: str = ""
    recovery_reason: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class EventContext:
    confirm_required: int
    recovery_required: int
    hit_streak: int = 0
    recovery_streak: int = 0
    active: dict[str, Any] | None = None
    pending_close_since: datetime | None = None
    pending_recovery_reason: str | None = None


class EventDetector:
    def __init__(self, config: dict, run_id: str):
        self.config = config
        self.run_id = run_id
        self.thresholds = config["thresholds"]
        self.detector_cfg = config["detector"]
        baseline_cfg = self.detector_cfg["baseline"]
        self.detection_mode = str(self.detector_cfg.get("detection_mode", "static")).lower()

        self.merge_gap_sec = int(self.detector_cfg.get("merge_gap_sec", 10))
        self.recovery_hold_sec = int(self.detector_cfg.get("recovery_hold_sec", 10))
        self.startup_grace_sec = int(self.detector_cfg.get("startup_grace_sec", 10))
        self.mad_k = float(baseline_cfg.get("mad_k", 3.0))
        self.recovery_mad_k = float(baseline_cfg.get("recovery_mad_k", 1.5))

        self.contexts = {
            name: EventContext(
                confirm_required=cfg.get("confirm_consecutive", 1),
                recovery_required=cfg.get("recovery_consecutive", 1),
            )
            for name, cfg in self.detector_cfg["events"].items()
        }

        minimum_samples = int(baseline_cfg.get("minimum_samples", 5))
        self.dns_baselines = {
            "internal": RollingBaseline(int(baseline_cfg.get("dns_window_samples", 30)), minimum_samples),
            "external": RollingBaseline(int(baseline_cfg.get("dns_window_samples", 30)), minimum_samples),
        }
        self.rtt_baseline = RollingBaseline(int(baseline_cfg.get("rtt_window_samples", 20)), minimum_samples)
        self.http_total_baselines = {
            "internal": RollingBaseline(int(baseline_cfg.get("http_window_samples", 20)), minimum_samples),
            "external": RollingBaseline(int(baseline_cfg.get("http_window_samples", 20)), minimum_samples),
        }
        self.http_ttfb_baselines = {
            "internal": RollingBaseline(int(baseline_cfg.get("http_window_samples", 20)), minimum_samples),
            "external": RollingBaseline(int(baseline_cfg.get("http_window_samples", 20)), minimum_samples),
        }

        self.fast_history: deque[dict[str, Any]] = deque()
        self.http_history: deque[dict[str, Any]] = deque()
        self.first_sample_ts: datetime | None = None

    def _latency_trigger_threshold(self, baseline: RollingBaseline, static_threshold: float) -> float | None:
        if self.detection_mode == "dynamic":
            return baseline.trigger_threshold(None, self.mad_k)
        return static_threshold

    def _latency_recovery_threshold(self, baseline: RollingBaseline, static_threshold: float) -> float | None:
        if self.detection_mode == "dynamic":
            return baseline.recovery_threshold(None, self.recovery_mad_k)
        return static_threshold

    def handle_sample(self, sample: dict) -> list[dict]:
        ts = parse_ts(sample["ts"])
        if self.first_sample_ts is None:
            self.first_sample_ts = ts

        notices = self._finalize_pending(ts)
        probe_type = sample.get("probe_type")

        evaluations: list[Evaluation] = []
        if probe_type == "fast":
            self._remember_fast(sample, ts)
            evaluations = [
                self._eval_connectivity_flap(sample, ts),
                self._eval_dns_timeout_burst(sample),
                self._eval_loss_burst(sample, ts),
                self._eval_dns_degraded(sample),
            ]
        elif probe_type == "telemetry":
            self._remember_http(sample, ts)
            evaluations = [
                self._eval_high_rtt(sample),
                self._eval_http_slow(sample),
            ]
        elif probe_type == "throughput":
            evaluations = [self._eval_bandwidth_throttle(sample)]

        suppress_loss = (
            any(evt.event_type == "CONNECTIVITY_FLAP" and evt.hit for evt in evaluations)
            or self.contexts["CONNECTIVITY_FLAP"].active is not None
        )
        filtered_evaluations = []
        for evaluation in evaluations:
            if suppress_loss and evaluation.event_type == "LOSS_BURST":
                evaluation.hit = False
            filtered_evaluations.append(evaluation)

        for evaluation in filtered_evaluations:
            notices.extend(self._apply_evaluation(evaluation, ts))

        self._update_baselines(sample, filtered_evaluations)
        notices.extend(self._finalize_pending(ts))
        return notices

    def _in_startup_grace(self, ts: datetime) -> bool:
        if self.first_sample_ts is None:
            return True
        return ts < (self.first_sample_ts + timedelta(seconds=self.startup_grace_sec))

    def _finalize_pending(self, ts: datetime) -> list[dict]:
        notices: list[dict] = []
        for event_type, context in self.contexts.items():
            if not context.active or not context.pending_close_since:
                continue
            threshold = context.pending_close_since + timedelta(seconds=self.merge_gap_sec)
            if ts < threshold:
                continue

            event = dict(context.active)
            event["ts_end"] = ts.isoformat()
            event["recovery_reason"] = context.pending_recovery_reason or "recovered"
            notices.append({"kind": "closed", "event": event})
            context.active = None
            context.hit_streak = 0
            context.recovery_streak = 0
            context.pending_close_since = None
            context.pending_recovery_reason = None

        return notices

    def _apply_evaluation(self, evaluation: Evaluation, ts: datetime) -> list[dict]:
        notices: list[dict] = []
        context = self.contexts[evaluation.event_type]
        if context.active is None:
            if evaluation.hit:
                context.hit_streak += 1
            else:
                context.hit_streak = 0

            if context.hit_streak >= context.confirm_required and not self._in_startup_grace(ts):
                context.active = self._new_event_record(evaluation, ts)
                context.recovery_streak = 0
                context.pending_close_since = None
                context.pending_recovery_reason = None
                notices.append({"kind": "started", "event": dict(context.active)})
            return notices

        if evaluation.hit:
            context.hit_streak = min(context.hit_streak + 1, context.confirm_required)
            context.recovery_streak = 0
            context.pending_close_since = None
            context.pending_recovery_reason = None
            context.active["affected_scope"] = evaluation.affected_scope or context.active.get("affected_scope", "unknown")
            merged_targets = set(context.active.get("affected_targets", []))
            merged_targets.update(evaluation.affected_targets)
            context.active["affected_targets"] = sorted(merged_targets)
            context.active["severity"] = self._max_severity(context.active.get("severity", "low"), evaluation.severity)
            if evaluation.trigger_reason:
                context.active["trigger_reason"] = evaluation.trigger_reason
            if evaluation.extra:
                context.active.update(evaluation.extra)
            return notices

        if evaluation.recovery_ok:
            context.recovery_streak += 1
            if context.recovery_streak >= context.recovery_required and context.pending_close_since is None:
                context.pending_close_since = ts
                context.pending_recovery_reason = evaluation.recovery_reason
        else:
            context.recovery_streak = 0
            context.pending_close_since = None
            context.pending_recovery_reason = None

        return notices

    def _new_event_record(self, evaluation: Evaluation, ts: datetime) -> dict:
        spec = EVENT_SPECS[evaluation.event_type]
        stamp = ts.strftime("%Y%m%dT%H%M%S")
        event = {
            "event_id": f"evt-{stamp}-{evaluation.event_type.lower()}",
            "run_id": self.run_id,
            "scenario_id": spec["scenario_id"],
            "event_type": evaluation.event_type,
            "affected_scope": evaluation.affected_scope,
            "affected_targets": sorted(set(evaluation.affected_targets)),
            "severity": evaluation.severity,
            "ts_start": ts.isoformat(),
            "ts_end": None,
            "trigger_reason": evaluation.trigger_reason,
            "recovery_reason": None,
        }
        if evaluation.extra:
            event.update(evaluation.extra)
        return event

    def _remember_fast(self, sample: dict, ts: datetime) -> None:
        dns_entries = sample.get("dns", [])
        dns_all_ok = bool(dns_entries) and all(item.get("success") for item in dns_entries)
        ping_ok = bool(sample.get("ping", {}).get("success"))
        wifi_up = bool(sample.get("wifi", {}).get("wifi_up"))

        self.fast_history.append(
            {
                "ts": ts,
                "connectivity_ok": bool(sample.get("connectivity_ok")),
                "ping_ok": ping_ok,
                "dns_all_ok": dns_all_ok,
                "wifi_up": wifi_up,
            }
        )
        self._purge_history(self.fast_history, ts, max(self.thresholds["loss_window_sec"], self.thresholds["flap_window_sec"]) + 5)

    def _remember_http(self, sample: dict, ts: datetime) -> None:
        http_rows = sample.get("http", [])
        if not http_rows:
            return
        all_ok = all(row.get("http_ok") for row in http_rows)
        self.http_history.append({"ts": ts, "http_ok": all_ok})
        self._purge_history(self.http_history, ts, self.thresholds["flap_window_sec"] + 5)

    @staticmethod
    def _purge_history(history: deque, ts: datetime, window_sec: float) -> None:
        while history and (ts - history[0]["ts"]).total_seconds() > window_sec:
            history.popleft()

    @staticmethod
    def _group_by_scope(entries: list[dict], key_name: str) -> dict[str, dict]:
        grouped: dict[str, dict] = defaultdict(lambda: {"items": [], "targets": set()})
        for entry in entries:
            scope = entry.get("scope", "unknown")
            grouped[scope]["items"].append(entry)
            grouped[scope]["targets"].add(entry.get(key_name) or entry.get("target") or entry.get("url"))
        return grouped

    @staticmethod
    def _combine_scope(scopes: set[str]) -> str:
        normalized = {scope for scope in scopes if scope in {"internal", "external"}}
        if normalized == {"internal", "external"}:
            return "all"
        if len(normalized) == 1:
            return next(iter(normalized))
        return "unknown"

    @staticmethod
    def _max_severity(left: str, right: str) -> str:
        order = {"low": 1, "medium": 2, "high": 3}
        return left if order.get(left, 0) >= order.get(right, 0) else right

    @staticmethod
    def _scope_targets(grouped: dict[str, dict], scopes: set[str]) -> list[str]:
        targets: set[str] = set()
        for scope in scopes:
            targets.update(str(target) for target in grouped.get(scope, {}).get("targets", set()) if target)
        return sorted(targets)

    def _dns_scope_stats(self, dns_entries: list[dict]) -> dict[str, dict]:
        grouped = self._group_by_scope(dns_entries, "target")
        stats: dict[str, dict] = {}
        for scope, payload in grouped.items():
            items = payload["items"]
            success_items = [item for item in items if item.get("success")]
            success_count = len(success_items)
            total = len(items)
            success_ratio = success_count / total if total else 0.0
            fail_ratio = 1.0 - success_ratio if total else 0.0
            max_latency = max((item.get("latency_ms") or 0.0) for item in success_items) if success_items else None
            stats[scope] = {
                "items": items,
                "success_ratio": success_ratio,
                "fail_ratio": fail_ratio,
                "max_success_latency_ms": max_latency,
                "success_targets": [item["target"] for item in success_items],
                "fail_targets": [item["target"] for item in items if not item.get("success")],
            }
        return stats

    def _http_scope_stats(self, http_entries: list[dict]) -> dict[str, dict]:
        grouped = self._group_by_scope(http_entries, "url")
        stats: dict[str, dict] = {}
        for scope, payload in grouped.items():
            items = payload["items"]
            max_total = max((item.get("http_total_ms") or 0.0) for item in items) if items else None
            max_ttfb = max((item.get("http_ttfb_ms") or 0.0) for item in items) if items else None
            stats[scope] = {
                "items": items,
                "max_total_ms": max_total,
                "max_ttfb_ms": max_ttfb,
            }
        return stats

    def _eval_dns_degraded(self, sample: dict) -> Evaluation:
        evaln = Evaluation("DNS_DEGRADED", recovery_reason="dns latency kembali normal")
        wifi_up = bool(sample.get("wifi", {}).get("wifi_up"))
        ping_ok = bool(sample.get("ping", {}).get("success"))
        if not wifi_up or not ping_ok:
            return evaln

        minimum_success_ratio = float(self.detector_cfg["events"]["DNS_DEGRADED"].get("minimum_success_ratio", 1.0))
        grouped = self._dns_scope_stats(sample.get("dns", []))
        hit_scopes: set[str] = set()
        affected_targets: list[str] = []
        reasons: list[str] = []
        static_threshold = float(self.thresholds["dns_latency_threshold_ms"])

        for scope in ("internal", "external"):
            stats = grouped.get(scope)
            if not stats:
                continue
            max_latency = stats["max_success_latency_ms"]
            if stats["success_ratio"] < minimum_success_ratio or max_latency is None:
                continue

            threshold = self._latency_trigger_threshold(self.dns_baselines[scope], static_threshold)
            if threshold is None:
                continue
            if max_latency >= threshold:
                hit_scopes.add(scope)
                affected_targets.extend(stats["success_targets"])
                reasons.append(f"{scope}:max_dns_latency_ms={max_latency:.1f} >= threshold={threshold:.1f}")

        if hit_scopes:
            scope = self._combine_scope(hit_scopes)
            evaln.hit = True
            evaln.affected_scope = scope
            evaln.affected_targets = sorted(set(affected_targets))
            evaln.trigger_reason = "; ".join(reasons)
            worst_latency = max(
                (grouped[scope_name]["max_success_latency_ms"] or 0.0)
                for scope_name in hit_scopes
            )
            evaln.severity = "high" if worst_latency >= (static_threshold * 3) else "medium"
            return evaln

        active = self.contexts["DNS_DEGRADED"].active
        if active:
            scope_names = {"internal", "external"} if active.get("affected_scope") == "all" else {active.get("affected_scope")}
            recovery_ok = True
            for scope_name in scope_names:
                stats = grouped.get(scope_name)
                if not stats:
                    recovery_ok = False
                    break
                max_latency = stats["max_success_latency_ms"]
                threshold = self._latency_recovery_threshold(self.dns_baselines[scope_name], static_threshold)
                if threshold is None:
                    recovery_ok = False
                    break
                if stats["success_ratio"] < minimum_success_ratio or max_latency is None or max_latency >= threshold:
                    recovery_ok = False
                    break
            evaln.recovery_ok = recovery_ok
            if recovery_ok:
                evaln.recovery_reason = "dns_success_ratio normal dan latency kembali di bawah threshold"
        return evaln

    def _eval_dns_timeout_burst(self, sample: dict) -> Evaluation:
        evaln = Evaluation("DNS_TIMEOUT_BURST", recovery_reason="dns success stabil kembali")
        wifi_up = bool(sample.get("wifi", {}).get("wifi_up"))
        ping_ok = bool(sample.get("ping", {}).get("success"))
        if not wifi_up or not ping_ok:
            return evaln

        fail_threshold = float(self.thresholds["dns_fail_ratio_threshold"])
        grouped = self._dns_scope_stats(sample.get("dns", []))
        hit_scopes: set[str] = set()
        reasons: list[str] = []
        affected_targets: list[str] = []

        for scope in ("internal", "external"):
            stats = grouped.get(scope)
            if not stats:
                continue
            if stats["fail_ratio"] >= fail_threshold:
                hit_scopes.add(scope)
                affected_targets.extend(stats["fail_targets"])
                reasons.append(f"{scope}:dns_fail_ratio={stats['fail_ratio']:.2f} >= threshold={fail_threshold:.2f}")

        if hit_scopes:
            evaln.hit = True
            evaln.affected_scope = self._combine_scope(hit_scopes)
            evaln.affected_targets = sorted(set(affected_targets))
            evaln.trigger_reason = "; ".join(reasons)
            evaln.severity = "high" if evaln.affected_scope == "all" else "medium"
            return evaln

        active = self.contexts["DNS_TIMEOUT_BURST"].active
        if active:
            scope_names = {"internal", "external"} if active.get("affected_scope") == "all" else {active.get("affected_scope")}
            recovery_ratio = float(self.detector_cfg["events"]["DNS_TIMEOUT_BURST"].get("recovery_success_ratio", self.thresholds["dns_recovery_success_ratio"]))
            recovery_ok = True
            for scope_name in scope_names:
                stats = grouped.get(scope_name)
                if not stats or stats["success_ratio"] < recovery_ratio:
                    recovery_ok = False
                    break
            evaln.recovery_ok = recovery_ok
            if recovery_ok:
                evaln.recovery_reason = "dns_success_ratio kembali memenuhi recovery_success_ratio"
        return evaln

    def _eval_loss_burst(self, sample: dict, ts: datetime) -> Evaluation:
        evaln = Evaluation("LOSS_BURST", recovery_reason="packet loss window kembali normal")
        if not bool(sample.get("wifi", {}).get("wifi_up")):
            return evaln

        window_sec = float(self.thresholds["loss_window_sec"])
        loss_threshold = float(self.thresholds["loss_threshold_pct"])
        recovery_threshold = float(self.thresholds.get("recovery_loss_threshold_pct", 5))
        minimum_samples = int(self.detector_cfg["events"]["LOSS_BURST"].get("minimum_samples", 5))

        window = [
            row for row in self.fast_history
            if (ts - row["ts"]).total_seconds() <= window_sec
        ]
        total = len(window)
        if total == 0:
            return evaln

        failed = sum(1 for row in window if not row["ping_ok"])
        loss_pct = (failed / total) * 100.0

        if total >= minimum_samples and loss_pct >= loss_threshold:
            evaln.hit = True
            evaln.affected_scope = "all"
            evaln.severity = "high" if loss_pct >= 50 else "medium"
            evaln.trigger_reason = f"ping_loss_pct_window={loss_pct:.1f} >= threshold={loss_threshold:.1f} with sample_count={total}"
            evaln.extra = {"observed_loss_pct_window": round(loss_pct, 2)}
            return evaln

        if self.contexts["LOSS_BURST"].active:
            evaln.recovery_ok = total >= minimum_samples and loss_pct < recovery_threshold
            if evaln.recovery_ok:
                evaln.recovery_reason = f"ping_loss_pct_window={loss_pct:.1f} < recovery_threshold={recovery_threshold:.1f}"
        return evaln

    def _eval_high_rtt(self, sample: dict) -> Evaluation:
        evaln = Evaluation("HIGH_RTT", recovery_reason="rtt dan loss kembali normal")
        ping = sample.get("ping", {})
        rtt_avg = ping.get("rtt_avg_ms")
        loss_pct = ping.get("loss_pct")
        if rtt_avg is None:
            return evaln

        static_threshold = float(self.thresholds["rtt_threshold_ms"])
        loss_limit = float(self.thresholds["rtt_loss_upper_bound_pct"])
        if loss_pct is not None and loss_pct >= loss_limit:
            return evaln

        threshold = self._latency_trigger_threshold(self.rtt_baseline, static_threshold)
        if threshold is None:
            return evaln
        if rtt_avg >= threshold:
            evaln.hit = True
            evaln.affected_scope = "all"
            evaln.trigger_reason = f"rtt_avg_ms={rtt_avg:.1f} >= threshold={threshold:.1f}"
            evaln.severity = "high" if rtt_avg >= (static_threshold * 2) else "medium"
            return evaln

        if self.contexts["HIGH_RTT"].active:
            recovery_threshold = self._latency_recovery_threshold(
                self.rtt_baseline,
                float(self.thresholds.get("recovery_rtt_threshold_ms", static_threshold)),
            )
            if recovery_threshold is None:
                return evaln
            evaln.recovery_ok = rtt_avg < recovery_threshold and (loss_pct is None or loss_pct < loss_limit)
            if evaln.recovery_ok:
                evaln.recovery_reason = f"rtt_avg_ms={rtt_avg:.1f} < recovery_threshold={recovery_threshold:.1f}"
        return evaln

    def _eval_http_slow(self, sample: dict) -> Evaluation:
        evaln = Evaluation("HTTP_SLOW", recovery_reason="http timing dan status kembali normal")
        wifi_connected = bool(sample.get("wifi", {}).get("wifi_connected"))
        if not wifi_connected:
            return evaln

        dns_entries = sample.get("dns", [])
        if dns_entries and all(not row.get("success") for row in dns_entries):
            return evaln

        grouped = self._http_scope_stats(sample.get("http", []))
        static_total = float(self.thresholds["http_total_threshold_ms"])
        static_ttfb = float(self.thresholds["http_ttfb_threshold_ms"])

        hit_scopes: set[str] = set()
        affected_targets: list[str] = []
        reasons: list[str] = []

        for scope in ("internal", "external"):
            stats = grouped.get(scope)
            if not stats:
                continue
            for row in stats["items"]:
                total_threshold = self._latency_trigger_threshold(self.http_total_baselines[scope], static_total)
                ttfb_threshold = self._latency_trigger_threshold(self.http_ttfb_baselines[scope], static_ttfb)
                status_min = int(row.get("expected_status_min", self.thresholds["http_expected_status_min"]))
                status_max = int(row.get("expected_status_max", self.thresholds["http_expected_status_max"]))
                status = row.get("http_status")
                total_ms = row.get("http_total_ms")
                ttfb_ms = row.get("http_ttfb_ms")
                bad = False

                if row.get("curl_rc") not in (0, None):
                    reasons.append(f"{scope}:{row['host']} curl_rc={row['curl_rc']} != 0")
                    bad = True
                elif status is None or not (status_min <= status <= status_max):
                    reasons.append(f"{scope}:{row['host']} http_status={status} outside expected range")
                    bad = True
                elif total_threshold is not None and total_ms is not None and total_ms >= total_threshold:
                    reasons.append(f"{scope}:{row['host']} http_total_ms={total_ms:.1f} >= threshold={total_threshold:.1f}")
                    bad = True
                elif ttfb_threshold is not None and ttfb_ms is not None and ttfb_ms >= ttfb_threshold:
                    reasons.append(f"{scope}:{row['host']} http_ttfb_ms={ttfb_ms:.1f} >= threshold={ttfb_threshold:.1f}")
                    bad = True

                if bad:
                    hit_scopes.add(scope)
                    affected_targets.append(row["url"])

        if hit_scopes:
            evaln.hit = True
            evaln.affected_scope = self._combine_scope(hit_scopes)
            evaln.affected_targets = sorted(set(affected_targets))
            evaln.trigger_reason = "; ".join(reasons)
            evaln.severity = "high" if any("curl_rc" in reason or "http_status" in reason for reason in reasons) else "medium"
            return evaln

        active = self.contexts["HTTP_SLOW"].active
        if active:
            scope_names = {"internal", "external"} if active.get("affected_scope") == "all" else {active.get("affected_scope")}
            recovery_ok = True
            for scope_name in scope_names:
                stats = grouped.get(scope_name)
                if not stats:
                    recovery_ok = False
                    break
                total_threshold = self._latency_recovery_threshold(
                    self.http_total_baselines[scope_name],
                    float(self.thresholds.get("recovery_http_total_threshold_ms", static_total)),
                )
                ttfb_threshold = self._latency_recovery_threshold(
                    self.http_ttfb_baselines[scope_name],
                    float(self.thresholds.get("recovery_http_ttfb_threshold_ms", static_ttfb)),
                )
                if total_threshold is None or ttfb_threshold is None:
                    recovery_ok = False
                    break

                for row in stats["items"]:
                    status_min = int(row.get("expected_status_min", self.thresholds["http_expected_status_min"]))
                    status_max = int(row.get("expected_status_max", self.thresholds["http_expected_status_max"]))
                    status = row.get("http_status")
                    total_ms = row.get("http_total_ms")
                    ttfb_ms = row.get("http_ttfb_ms")
                    if row.get("curl_rc") not in (0, None):
                        recovery_ok = False
                        break
                    if status is None or not (status_min <= status <= status_max):
                        recovery_ok = False
                        break
                    if total_ms is None or total_ms >= total_threshold:
                        recovery_ok = False
                        break
                    if ttfb_ms is not None and ttfb_ms >= ttfb_threshold:
                        recovery_ok = False
                        break
                if not recovery_ok:
                    break
            evaln.recovery_ok = recovery_ok
            if recovery_ok:
                evaln.recovery_reason = "http status normal dan latency kembali di bawah recovery threshold"
        return evaln

    def _eval_connectivity_flap(self, sample: dict, ts: datetime) -> Evaluation:
        evaln = Evaluation("CONNECTIVITY_FLAP", recovery_reason="connectivity stabil kembali")
        window_sec = float(self.thresholds["flap_window_sec"])
        transition_threshold = int(self.thresholds["flap_transition_threshold"])

        recent = [row for row in self.fast_history if (ts - row["ts"]).total_seconds() <= window_sec]
        if len(recent) < 2:
            return evaln

        transitions = 0
        for left, right in zip(recent, recent[1:]):
            if left["connectivity_ok"] != right["connectivity_ok"]:
                transitions += 1

        if transitions >= transition_threshold:
            evaln.hit = True
            evaln.affected_scope = "all"
            evaln.severity = "high" if transitions >= (transition_threshold + 2) else "medium"
            evaln.trigger_reason = f"state_transition_count(connectivity_ok)={transitions} >= threshold={transition_threshold} within {int(window_sec)}s"
            evaln.extra = {"suspected_layer": self._suspected_layer(recent)}
            return evaln

        active = self.contexts["CONNECTIVITY_FLAP"].active
        if active:
            last_transition_ts = None
            for left, right in zip(recent, recent[1:]):
                if left["connectivity_ok"] != right["connectivity_ok"]:
                    last_transition_ts = right["ts"]
            stable = bool(sample.get("connectivity_ok"))
            quiet = True
            if last_transition_ts is not None:
                quiet = (ts - last_transition_ts).total_seconds() >= self.recovery_hold_sec
            evaln.recovery_ok = stable and quiet
            if evaln.recovery_ok:
                evaln.recovery_reason = "connectivity_ok stabil tanpa transition tambahan"
        return evaln

    def _suspected_layer(self, recent: list[dict]) -> str:
        wifi_values = {row["wifi_up"] for row in recent}
        ping_values = {row["ping_ok"] for row in recent}
        dns_values = {row["dns_all_ok"] for row in recent}

        if len(wifi_values) > 1:
            return "wifi_link"
        if len(ping_values) > 1 and len(dns_values) > 1:
            return "upstream"
        if len(ping_values) == 1 and True in ping_values and len(dns_values) > 1:
            return "dns"

        http_values = {row["http_ok"] for row in self.http_history}
        if len(http_values) > 1 and len(ping_values) == 1 and True in ping_values and len(dns_values) == 1 and True in dns_values:
            return "application"
        return "unknown"

    def _eval_bandwidth_throttle(self, sample: dict) -> Evaluation:
        evaln = Evaluation("BANDWIDTH_THROTTLE", recovery_reason="throughput kembali normal")
        summary = sample.get("summary", {})
        download = summary.get("download", {})
        upload = summary.get("upload", {})

        dl_avg = (((download.get("throughput_total_mbps") or {}) or {}).get("avg"))
        ul_avg = (((upload.get("upload_throughput_total_mbps") or {}) or {}).get("avg"))
        dl_health = download.get("run_health") or {}
        ul_health = upload.get("run_health") or {}

        dl_threshold = float(self.thresholds["throughput_download_threshold_mbps"])
        ul_threshold = float(self.thresholds["throughput_upload_threshold_mbps"])

        reasons = []
        if dl_avg is not None and dl_avg < dl_threshold:
            reasons.append(f"download_throughput_total_mbps={dl_avg:.2f} < threshold={dl_threshold:.2f}")
        if ul_avg is not None and ul_avg < ul_threshold:
            reasons.append(f"upload_throughput_total_mbps={ul_avg:.2f} < threshold={ul_threshold:.2f}")
        if (dl_health.get("total_runs", 0) > 0 and dl_health.get("successful_http_runs", 0) == 0):
            reasons.append("all download runs failed")
        if (ul_health.get("total_runs", 0) > 0 and ul_health.get("successful_http_runs", 0) == 0):
            reasons.append("all upload runs failed")

        if reasons:
            evaln.hit = True
            evaln.affected_scope = "unknown"
            evaln.severity = "high" if any("failed" in reason for reason in reasons) else "medium"
            evaln.trigger_reason = "; ".join(reasons)
            return evaln

        active = self.contexts["BANDWIDTH_THROTTLE"].active
        if active:
            dl_ok = dl_avg is None or dl_avg >= dl_threshold
            ul_ok = ul_avg is None or ul_avg >= ul_threshold
            evaln.recovery_ok = dl_ok and ul_ok
            if evaln.recovery_ok:
                evaln.recovery_reason = "download/upload throughput kembali memenuhi threshold"
        return evaln

    def _update_baselines(self, sample: dict, evaluations: list[Evaluation]) -> None:
        probe_type = sample.get("probe_type")
        if probe_type == "fast":
            dns_hit = any(evt.event_type in {"DNS_DEGRADED", "DNS_TIMEOUT_BURST"} and evt.hit for evt in evaluations)
            if dns_hit:
                return
            for scope, stats in self._dns_scope_stats(sample.get("dns", [])).items():
                if scope not in self.dns_baselines:
                    continue
                if stats["success_ratio"] >= 1.0 and stats["max_success_latency_ms"] is not None:
                    if self.detection_mode == "dynamic" or stats["max_success_latency_ms"] < float(self.thresholds["dns_latency_threshold_ms"]):
                        self.dns_baselines[scope].add(stats["max_success_latency_ms"])

        elif probe_type == "telemetry":
            ping = sample.get("ping", {})
            rtt_avg = ping.get("rtt_avg_ms")
            loss_pct = ping.get("loss_pct")
            if rtt_avg is not None and (loss_pct is None or loss_pct < float(self.thresholds["rtt_loss_upper_bound_pct"])):
                if self.detection_mode == "dynamic" or rtt_avg < float(self.thresholds["rtt_threshold_ms"]):
                    self.rtt_baseline.add(rtt_avg)

            http_hit = any(evt.event_type == "HTTP_SLOW" and evt.hit for evt in evaluations)
            if http_hit:
                return
            for scope, stats in self._http_scope_stats(sample.get("http", [])).items():
                if scope not in self.http_total_baselines:
                    continue
                successful = [row for row in stats["items"] if row.get("http_ok")]
                if not successful:
                    continue
                max_total = max((row.get("http_total_ms") or 0.0) for row in successful)
                max_ttfb = max((row.get("http_ttfb_ms") or 0.0) for row in successful)
                if self.detection_mode == "dynamic" or max_total < float(self.thresholds["http_total_threshold_ms"]):
                    self.http_total_baselines[scope].add(max_total)
                if self.detection_mode == "dynamic" or max_ttfb < float(self.thresholds["http_ttfb_threshold_ms"]):
                    self.http_ttfb_baselines[scope].add(max_ttfb)

    def force_close_all(self) -> list[dict]:
        notices: list[dict] = []
        closed_at = utc_now_iso()
        for event_type, context in self.contexts.items():
            if not context.active:
                continue
            event = dict(context.active)
            event["ts_end"] = closed_at
            event["recovery_reason"] = "forced shutdown"
            notices.append({"kind": "closed", "event": event})
            context.active = None
            context.hit_streak = 0
            context.recovery_streak = 0
            context.pending_close_since = None
            context.pending_recovery_reason = None
        return notices
