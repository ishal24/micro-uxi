from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from pathlib import Path
from typing import Any


class ExporterRuntime:
    def __init__(self, runtime_config: dict[str, Any], exporter_config: dict[str, Any]):
        self.runtime_config = runtime_config
        self.config = exporter_config
        self.module_cfg = exporter_config["exporter"]
        self.transport_cfg = exporter_config.get("transport", {})
        self.streams_cfg = exporter_config.get("streams", {})
        self.queue_cfg = exporter_config.get("queue", {})
        self.retry_cfg = exporter_config.get("retry", {})

        self.base_url = str(self.transport_cfg.get("base_url", "")).rstrip("/")
        self.api_key = str(self.transport_cfg.get("api_key", ""))
        self.timeout_sec = float(self.transport_cfg.get("timeout_sec", 5))
        self.paths = self.transport_cfg.get("paths", {})
        self.verbose_terminal = bool(self.module_cfg.get("verbose_terminal", True))
        self.max_items = max(1, int(self.queue_cfg.get("max_items", 200)))
        self.drop_policy = str(self.queue_cfg.get("drop_policy", "drop_oldest"))
        self.retry_delay_sec = float(self.retry_cfg.get("delay_sec", 5))
        self.max_attempts = self.retry_cfg.get("max_attempts")
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.lock = threading.Lock()
        self.queue: deque[dict[str, Any]] = deque()

        self.queued_count = 0
        self.sent_count = 0
        self.failed_count = 0
        self.dropped_count = 0
        self.retry_count = 0

    @property
    def enabled(self) -> bool:
        return bool(self.base_url)

    def start(self) -> None:
        self.thread = threading.Thread(target=self._worker_loop, daemon=True, name="exporter")
        self.thread.start()

    def join(self) -> None:
        if self.thread is not None:
            self.thread.join(timeout=10)

    def _print(self, message: str) -> None:
        if self.verbose_terminal:
            print(message, flush=True)

    def _stream_enabled(self, stream: str) -> bool:
        stream_cfg = self.streams_cfg.get(stream, {})
        return bool(stream_cfg.get("enabled", True))

    def _endpoint_for(self, stream: str) -> str | None:
        path = self.paths.get(stream)
        if not path or not self.base_url:
            return None
        return f"{self.base_url}/{str(path).lstrip('/')}"

    def _enqueue(self, item: dict[str, Any]) -> None:
        with self.lock:
            if len(self.queue) >= self.max_items:
                if self.drop_policy == "drop_newest":
                    self.dropped_count += 1
                    return
                self.queue.popleft()
                self.dropped_count += 1
            self.queue.append(item)
            self.queued_count += 1

    def _build_envelope(self, stream: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            **payload,
            "exporter_meta": {
                "stream": stream,
                "queued_at": time.time(),
            },
        }

    def submit_monitoring(self, sample: dict[str, Any]) -> None:
        if not self._stream_enabled("monitoring"):
            return
        endpoint = self._endpoint_for("monitoring")
        if endpoint is None:
            return
        self._enqueue(
            {
                "stream": "monitoring",
                "endpoint": endpoint,
                "payload": self._build_envelope("monitoring", sample),
                "attempts": 0,
            }
        )

    def submit_overhead(self, sample: dict[str, Any]) -> None:
        if not self._stream_enabled("overhead"):
            return
        endpoint = self._endpoint_for("overhead")
        if endpoint is None:
            return
        self._enqueue(
            {
                "stream": "overhead",
                "endpoint": endpoint,
                "payload": self._build_envelope("overhead", sample),
                "attempts": 0,
            }
        )

    def submit_detection(self, event_record: dict[str, Any]) -> None:
        if not self._stream_enabled("detection"):
            return
        endpoint = self._endpoint_for("detection")
        if endpoint is None:
            return
        self._enqueue(
            {
                "stream": "detection",
                "endpoint": endpoint,
                "payload": self._build_envelope("detection", event_record),
                "attempts": 0,
            }
        )

    def _do_post(self, endpoint: str, payload: dict[str, Any]) -> bool:
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(endpoint, data=data, method="POST")
            req.add_header("Content-Type", "application/json")
            if self.api_key:
                req.add_header("X-API-Key", self.api_key)

            with urllib.request.urlopen(req, timeout=self.timeout_sec) as response:
                return response.status in (200, 201, 202)
        except Exception as exc:
            self._print(f"[EXPORTER ERROR] POST {endpoint} failed: {exc}")
            return False

    def _worker_loop(self) -> None:
        while not self.stop_event.is_set():
            item = None
            with self.lock:
                if self.queue:
                    item = self.queue.popleft()

            if item is None:
                self.stop_event.wait(0.5)
                continue

            item["attempts"] += 1
            payload = dict(item["payload"])
            exporter_meta = dict(payload.get("exporter_meta", {}))
            exporter_meta["export_attempt"] = item["attempts"]
            exporter_meta["sent_at"] = time.time()
            payload["exporter_meta"] = exporter_meta

            ok = self._do_post(item["endpoint"], payload)
            if ok:
                self.sent_count += 1
                self.stop_event.wait(0.05)
                continue

            self.failed_count += 1
            should_retry = self.max_attempts is None or item["attempts"] < int(self.max_attempts)
            if should_retry:
                self.retry_count += 1
                with self.lock:
                    if len(self.queue) >= self.max_items:
                        if self.drop_policy == "drop_newest":
                            self.dropped_count += 1
                        else:
                            self.queue.popleft()
                            self.dropped_count += 1
                    self.queue.appendleft(item)
                self.stop_event.wait(self.retry_delay_sec)
            else:
                self._print(f"[EXPORTER DROP] stream={item['stream']} attempts={item['attempts']}")


def load_exporter_config(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)
