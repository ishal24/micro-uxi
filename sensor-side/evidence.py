from __future__ import annotations

import json
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from probe.utils import append_jsonl, safe_mkdir


def _parse_ts(raw: Any) -> datetime:
    if isinstance(raw, datetime):
        dt = raw
    elif isinstance(raw, str) and raw.strip():
        text = raw.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            dt = datetime.now(timezone.utc)
    else:
        dt = datetime.now(timezone.utc)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso_compact(dt: datetime) -> str:
    local_dt = dt.astimezone()
    return local_dt.strftime("%Y%m%dT%H%M%S%z")


def _json_dump(path: Path, payload: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


@dataclass
class BufferEntry:
    ts: datetime
    stream: str
    record: dict[str, Any]


@dataclass
class SnapshotEntry:
    label: str
    timestamp: str
    fast_sample: dict[str, Any] | None
    telemetry_sample: dict[str, Any] | None
    overhead_sample: dict[str, Any] | None
    detection_event: dict[str, Any] | None


@dataclass
class BundleState:
    bundle_id: str
    event_key: str
    alarm_event: dict[str, Any]
    alarm_ts: datetime
    bundle_dir: Path
    timeline_path: Path
    snapshot_path: Path
    created_at: str
    pre_window_sec: int
    post_window_sec: int
    state: str = "event"
    closed_reason: str | None = None
    recovery_ts: datetime | None = None
    last_detection_event: dict[str, Any] | None = None
    snapshots: list[SnapshotEntry] = field(default_factory=list)


class EvidenceRuntime:
    def __init__(self, runtime_config: dict[str, Any], evidence_config: dict[str, Any], output_dir: Path):
        self.runtime_config = runtime_config
        self.config = evidence_config
        self.module_cfg = evidence_config["evidence"]
        self.device_id = runtime_config["device"].get("device_id")
        self.output_root = safe_mkdir(output_dir / self.module_cfg.get("output_dirname", "evidence"))
        self.pre_window_sec = int(self.module_cfg.get("pre_window_sec", 30))
        self.post_window_sec = int(self.module_cfg.get("post_window_sec", 30))
        self.buffer_seconds = max(int(self.module_cfg.get("buffer_seconds", 60)), self.pre_window_sec + 5)
        self.write_timeline_jsonl = bool(self.module_cfg.get("write_timeline_jsonl", True))
        self.write_snapshot_json = bool(self.module_cfg.get("write_snapshot_json", True))
        self.verbose_terminal = bool(self.module_cfg.get("verbose_terminal", True))
        self.max_active_bundles = max(1, int(self.module_cfg.get("max_active_bundles", 16)))
        self.include_streams = self.module_cfg.get("include_streams", {})
        self.include_monitoring = bool(self.include_streams.get("monitoring", True))
        self.include_overhead = bool(self.include_streams.get("overhead", True))
        self.include_detection = bool(self.include_streams.get("detection", True))

        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.lock = threading.Lock()
        self.buffers = {
            "monitoring": deque(),
            "overhead": deque(),
            "detection": deque(),
        }
        self.pending: deque[tuple[str, dict[str, Any]]] = deque()
        self.active_bundles: list[BundleState] = []
        self.bundle_counter = 0
        self.bundle_count = 0
        self.closed_count = 0
        self.error_count = 0

    def start(self) -> None:
        self.thread = threading.Thread(target=self._worker_loop, daemon=True, name="evidence")
        self.thread.start()

    def join(self) -> None:
        if self.thread is not None:
            self.thread.join(timeout=10)

    def _print(self, message: str) -> None:
        if self.verbose_terminal:
            print(message, flush=True)

    def submit_monitoring(self, sample: dict[str, Any]) -> None:
        with self.lock:
            self.pending.append(("monitoring", sample))

    def submit_overhead(self, sample: dict[str, Any]) -> None:
        with self.lock:
            self.pending.append(("overhead", sample))

    def submit_detection_transition(self, event_record: dict[str, Any]) -> None:
        with self.lock:
            self.pending.append(("detection", event_record))

    def _trim_buffer(self, stream: str) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=self.buffer_seconds)
        entries = self.buffers[stream]
        while entries and entries[0].ts < cutoff:
            entries.popleft()

    def _buffer_record(self, stream: str, record: dict[str, Any]) -> None:
        entry = BufferEntry(ts=_parse_ts(record.get("ts")), stream=stream, record=record)
        self.buffers[stream].append(entry)
        self._trim_buffer(stream)

    def _phase_for_bundle(self, bundle: BundleState, record_ts: datetime) -> str:
        if record_ts < bundle.alarm_ts:
            return "pre_event"
        if bundle.recovery_ts is None or record_ts <= bundle.recovery_ts:
            return "event"
        return "post_event"

    def _write_timeline_record(self, bundle: BundleState, payload: dict[str, Any]) -> None:
        if self.write_timeline_jsonl:
            append_jsonl(bundle.timeline_path, payload)

    def _latest_sample_before(self, stream: str, cutoff: datetime, predicate=None) -> dict[str, Any] | None:
        entries = self.buffers[stream]
        for entry in reversed(entries):
            if entry.ts <= cutoff:
                if predicate is None or predicate(entry.record):
                    return entry.record
        return None

    def _capture_snapshot(self, bundle: BundleState, label: str, capture_ts: datetime, detection_event: dict[str, Any] | None) -> None:
        fast_sample = self._latest_sample_before("monitoring", capture_ts, lambda record: record.get("probe_type") == "fast")
        telemetry_sample = self._latest_sample_before("monitoring", capture_ts, lambda record: record.get("probe_type") == "telemetry")
        overhead_sample = self._latest_sample_before("overhead", capture_ts)
        bundle.snapshots.append(
            SnapshotEntry(
                label=label,
                timestamp=capture_ts.isoformat(),
                fast_sample=fast_sample,
                telemetry_sample=telemetry_sample,
                overhead_sample=overhead_sample,
                detection_event=detection_event,
            )
        )
        self._flush_snapshot(bundle)

    def _flush_snapshot(self, bundle: BundleState) -> None:
        if not self.write_snapshot_json:
            return
        payload = {
            "bundle_id": bundle.bundle_id,
            "device_id": self.device_id,
            "event_key": bundle.event_key,
            "created_at": bundle.created_at,
            "pre_window_sec": bundle.pre_window_sec,
            "post_window_sec": bundle.post_window_sec,
            "closed_reason": bundle.closed_reason,
            "snapshots": [
                {
                    "label": item.label,
                    "timestamp": item.timestamp,
                    "fast_sample": item.fast_sample,
                    "telemetry_sample": item.telemetry_sample,
                    "overhead_sample": item.overhead_sample,
                    "detection_event": item.detection_event,
                }
                for item in bundle.snapshots
            ],
        }
        _json_dump(bundle.snapshot_path, payload)

    def _bundle_filename_root(self, event_key: str, alarm_ts: datetime, occurrence: int) -> str:
        return f"{event_key}_{_iso_compact(alarm_ts)}_{occurrence:03d}"

    def _open_bundle(self, alarm_event: dict[str, Any]) -> None:
        if len(self.active_bundles) >= self.max_active_bundles and self.active_bundles:
            oldest = min(self.active_bundles, key=lambda item: item.alarm_ts)
            self._close_bundle(oldest, "max_active_bundles_exceeded", datetime.now(timezone.utc))

        alarm_ts = _parse_ts(alarm_event.get("ts"))
        self.bundle_counter += 1
        root_name = self._bundle_filename_root(str(alarm_event.get("event_key", "UNKNOWN")), alarm_ts, self.bundle_counter)
        bundle_dir = safe_mkdir(self.output_root / root_name)
        bundle = BundleState(
            bundle_id=root_name,
            event_key=str(alarm_event.get("event_key", "UNKNOWN")),
            alarm_event=alarm_event,
            alarm_ts=alarm_ts,
            bundle_dir=bundle_dir,
            timeline_path=bundle_dir / "evidence_timeline.jsonl",
            snapshot_path=bundle_dir / "diagnostic_snapshot.json",
            created_at=datetime.now(timezone.utc).isoformat(),
            pre_window_sec=self.pre_window_sec,
            post_window_sec=self.post_window_sec,
            last_detection_event=alarm_event,
        )
        self.active_bundles.append(bundle)
        self.bundle_count += 1

        self._write_timeline_record(
            bundle,
            {
                "record_type": "event_metadata",
                "timestamp": alarm_event.get("ts"),
                "bundle_id": bundle.bundle_id,
                "device_id": self.device_id,
                "event_key": bundle.event_key,
                "phase": "event",
                "pre_window_sec": self.pre_window_sec,
                "post_window_sec": self.post_window_sec,
                "files": {
                    "timeline": bundle.timeline_path.name,
                    "snapshot": bundle.snapshot_path.name,
                },
            },
        )

        pre_cutoff = alarm_ts - timedelta(seconds=self.pre_window_sec)
        for stream_name in ("monitoring", "overhead", "detection"):
            if stream_name == "monitoring" and not self.include_monitoring:
                continue
            if stream_name == "overhead" and not self.include_overhead:
                continue
            if stream_name == "detection" and not self.include_detection:
                continue
            for entry in self.buffers[stream_name]:
                if pre_cutoff <= entry.ts <= alarm_ts:
                    self._append_entry_to_bundle(bundle, stream_name, entry.record, entry.ts)

        self._capture_snapshot(bundle, "alarm", alarm_ts, alarm_event)
        self._print(f"[EVIDENCE OPEN] bundle={bundle.bundle_id} event={bundle.event_key}")

    def _append_entry_to_bundle(self, bundle: BundleState, stream_name: str, record: dict[str, Any], record_ts: datetime | None = None) -> None:
        ts = record_ts or _parse_ts(record.get("ts"))
        phase = self._phase_for_bundle(bundle, ts)
        if stream_name == "monitoring":
            payload = {
                "record_type": "monitoring_sample",
                "timestamp": record.get("ts"),
                "bundle_id": bundle.bundle_id,
                "device_id": self.device_id,
                "event_key": bundle.event_key,
                "phase": phase,
                "sample": record,
            }
        elif stream_name == "overhead":
            payload = {
                "record_type": "overhead_sample",
                "timestamp": record.get("ts"),
                "bundle_id": bundle.bundle_id,
                "device_id": self.device_id,
                "event_key": bundle.event_key,
                "phase": phase,
                "sample": record,
            }
        else:
            payload = {
                "record_type": "detection_event",
                "timestamp": record.get("ts"),
                "bundle_id": bundle.bundle_id,
                "device_id": self.device_id,
                "event_key": bundle.event_key,
                "phase": phase,
                "event": record,
            }
        self._write_timeline_record(bundle, payload)

    def _match_bundle_for_recovery(self, event_record: dict[str, Any]) -> BundleState | None:
        event_key = str(event_record.get("event_key", "UNKNOWN"))
        candidates = [bundle for bundle in self.active_bundles if bundle.event_key == event_key and bundle.state == "event"]
        if not candidates:
            return None
        return min(candidates, key=lambda bundle: bundle.alarm_ts)

    def _handle_detection_event(self, record: dict[str, Any]) -> None:
        self._buffer_record("detection", record)
        status = str(record.get("status", "")).upper()
        if status == "ALARM":
            self._open_bundle(record)
            return

        if status == "RECOVERY":
            bundle = self._match_bundle_for_recovery(record)
            if bundle is None:
                return
            bundle.state = "post_event"
            bundle.recovery_ts = _parse_ts(record.get("ts"))
            bundle.last_detection_event = record
            if self.include_detection:
                self._append_entry_to_bundle(bundle, "detection", record, bundle.recovery_ts)
            self._capture_snapshot(bundle, "recovery", bundle.recovery_ts, record)
            self._print(f"[EVIDENCE RECOVERY] bundle={bundle.bundle_id} event={bundle.event_key}")

    def _handle_monitoring_sample(self, record: dict[str, Any]) -> None:
        self._buffer_record("monitoring", record)
        if not self.include_monitoring:
            return
        ts = _parse_ts(record.get("ts"))
        for bundle in list(self.active_bundles):
            self._append_entry_to_bundle(bundle, "monitoring", record, ts)

    def _handle_overhead_sample(self, record: dict[str, Any]) -> None:
        self._buffer_record("overhead", record)
        if not self.include_overhead:
            return
        ts = _parse_ts(record.get("ts"))
        for bundle in list(self.active_bundles):
            self._append_entry_to_bundle(bundle, "overhead", record, ts)

    def _close_bundle(self, bundle: BundleState, reason: str, close_ts: datetime) -> None:
        if bundle not in self.active_bundles:
            return
        bundle.closed_reason = reason
        bundle.state = "closed"
        self._capture_snapshot(bundle, "post_event_complete", close_ts, bundle.last_detection_event)
        self._write_timeline_record(
            bundle,
            {
                "record_type": "evidence_closed",
                "timestamp": close_ts.isoformat(),
                "bundle_id": bundle.bundle_id,
                "device_id": self.device_id,
                "event_key": bundle.event_key,
                "phase": "post_event",
                "reason": reason,
            },
        )
        self.active_bundles.remove(bundle)
        self.closed_count += 1
        self._flush_snapshot(bundle)
        self._print(f"[EVIDENCE CLOSED] bundle={bundle.bundle_id} reason={reason}")

    def _check_timeouts(self) -> None:
        now = datetime.now(timezone.utc)
        for bundle in list(self.active_bundles):
            if bundle.state == "post_event" and bundle.recovery_ts is not None:
                if now >= bundle.recovery_ts + timedelta(seconds=self.post_window_sec):
                    self._close_bundle(bundle, "post_event_window_complete", now)

    def _drain_pending(self) -> None:
        items: list[tuple[str, dict[str, Any]]] = []
        with self.lock:
            while self.pending:
                items.append(self.pending.popleft())

        for stream_name, record in items:
            try:
                if stream_name == "monitoring":
                    self._handle_monitoring_sample(record)
                elif stream_name == "overhead":
                    self._handle_overhead_sample(record)
                elif stream_name == "detection":
                    self._handle_detection_event(record)
            except Exception as exc:  # pragma: no cover
                self.error_count += 1
                self._print(f"[EVIDENCE ERROR] {exc}")

    def _worker_loop(self) -> None:
        while not self.stop_event.is_set():
            self._drain_pending()
            self._check_timeouts()
            self.stop_event.wait(0.25)

        self._drain_pending()
        now = datetime.now(timezone.utc)
        for bundle in list(self.active_bundles):
            self._close_bundle(bundle, "monitor_stop", now)


def load_evidence_config(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)
