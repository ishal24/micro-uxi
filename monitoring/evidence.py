from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from monitoring.utils import append_jsonl, json_text, parse_ts, safe_mkdir, utc_now_iso, write_json


@dataclass
class EventBundle:
    event: dict
    pre_window: list[dict] = field(default_factory=list)
    event_window: list[dict] = field(default_factory=list)
    post_window: list[dict] = field(default_factory=list)
    state: str = "open"
    post_until: object | None = None
    wifi_snapshot: dict | None = None
    network_snapshot: dict | None = None


class EvidenceManager:
    def __init__(self, config: dict, run_id: str):
        self.config = config
        self.run_id = run_id
        self.enabled = bool(config.get("output", {}).get("enabled", False)) and bool(
            config.get("evidence", {}).get("enabled", True)
        )
        self.pre_window_sec = int(config.get("evidence", {}).get("pre_window_sec", 30))
        self.post_window_sec = int(config.get("evidence", {}).get("post_window_sec", 30))
        self.alignment_delta_sec = int(config.get("evidence", {}).get("alignment_delta_sec", 5))
        self.root_dir = safe_mkdir(Path(config["output"]["output_dir"]) / "evidence" / run_id) if self.enabled else None
        self.recent_samples: list[tuple] = []
        self.bundles: dict[str, EventBundle] = {}

    def capture(self, sample: dict, notices: list[dict]) -> None:
        if not self.enabled:
            return

        ts = parse_ts(sample["ts"])
        sample_copy = copy.deepcopy(sample)
        self._remember_recent(ts, sample_copy)

        for bundle in self.bundles.values():
            if bundle.state == "open":
                bundle.event_window.append(sample_copy)
            elif bundle.state == "post":
                bundle.post_window.append(sample_copy)

        for notice in notices:
            if notice["kind"] == "started":
                self._start_bundle(notice["event"], sample_copy)
            elif notice["kind"] == "closed":
                self._close_bundle(notice["event"])

        self._finalize_ready(ts)

    def force_flush(self, notices: list[dict]) -> None:
        if not self.enabled:
            return

        now = parse_ts(utc_now_iso())
        for notice in notices:
            if notice["kind"] == "closed":
                self._close_bundle(notice["event"])
        self._finalize_ready(now, force=True)

    def _remember_recent(self, ts, sample: dict) -> None:
        self.recent_samples.append((ts, sample))
        self.recent_samples = [
            (row_ts, row)
            for row_ts, row in self.recent_samples
            if (ts - row_ts).total_seconds() <= self.pre_window_sec
        ]

    def _start_bundle(self, event: dict, sample: dict) -> None:
        event_id = event["event_id"]
        event_start_ts = parse_ts(event["ts_start"])
        pre_window = [
            copy.deepcopy(row)
            for row_ts, row in self.recent_samples
            if row_ts < event_start_ts and (event_start_ts - row_ts).total_seconds() <= self.pre_window_sec
        ]

        self.bundles[event_id] = EventBundle(
            event=copy.deepcopy(event),
            pre_window=pre_window,
            event_window=[copy.deepcopy(sample)],
            wifi_snapshot=self._latest_section("wifi"),
            network_snapshot=self._latest_section("network"),
        )

    def _close_bundle(self, event: dict) -> None:
        bundle = self.bundles.get(event["event_id"])
        if not bundle:
            return
        bundle.event = copy.deepcopy(event)
        bundle.state = "post"
        bundle.post_until = parse_ts(event["ts_end"]) + timedelta(seconds=self.post_window_sec)

    def _finalize_ready(self, ts, force: bool = False) -> None:
        ready_ids = []
        for event_id, bundle in self.bundles.items():
            if bundle.state == "open" and not force:
                continue
            if force or bundle.post_until is None or ts >= bundle.post_until:
                ready_ids.append(event_id)

        for event_id in ready_ids:
            bundle = self.bundles.pop(event_id)
            self._export_bundle(bundle)

    def _latest_section(self, key: str) -> dict | None:
        for _, sample in reversed(self.recent_samples):
            section = sample.get(key)
            if section:
                return copy.deepcopy(section)
        return None

    def _export_bundle(self, bundle: EventBundle) -> None:
        event = bundle.event
        event_dir = safe_mkdir(self.root_dir / event["event_id"])

        write_json(event_dir / "event_meta.json", event)
        write_json(
            event_dir / "ground_truth_ref.json",
            {
                "run_id": self.run_id,
                "scenario_id": event["scenario_id"],
                "event_type": event["event_type"],
                "fault_start_ts": None,
                "fault_end_ts": None,
                "alignment_delta_sec": self.alignment_delta_sec,
                "alignment_strategy": "first-match",
                "notes": "Populate from fi-scripts ground-truth timeline when available.",
            },
        )
        write_json(event_dir / "probe_config.json", self.config)

        self._write_jsonl_window(event_dir / "pre_window.jsonl", bundle.pre_window)
        self._write_jsonl_window(event_dir / "event_window.jsonl", bundle.event_window)
        self._write_jsonl_window(event_dir / "post_window.jsonl", bundle.post_window)

        (event_dir / "wifi_snapshot.txt").write_text(json_text(bundle.wifi_snapshot or {}), encoding="utf-8")
        (event_dir / "net_snapshot.txt").write_text(json_text(bundle.network_snapshot or {}), encoding="utf-8")

        event_type = event["event_type"]
        all_samples = bundle.pre_window + bundle.event_window + bundle.post_window
        if event_type in {"DNS_DEGRADED", "DNS_TIMEOUT_BURST"}:
            self._write_filtered_rows(event_dir / "dns_samples.jsonl", all_samples, "dns")
        if event_type == "HTTP_SLOW":
            self._write_filtered_rows(event_dir / "http_timing_samples.jsonl", all_samples, "http")
        if event_type == "BANDWIDTH_THROTTLE":
            self._write_filtered_rows(event_dir / "throughput_samples.jsonl", all_samples, "summary")

    @staticmethod
    def _write_jsonl_window(path: Path, rows: list[dict]) -> None:
        for row in rows:
            append_jsonl(path, row)

    @staticmethod
    def _write_filtered_rows(path: Path, rows: list[dict], key: str) -> None:
        for row in rows:
            if row.get(key):
                append_jsonl(path, row)
