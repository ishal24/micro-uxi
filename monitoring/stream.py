from __future__ import annotations

import json
import queue
import threading
import time
from urllib import error, request


def _normalize_endpoint(endpoint: str) -> str:
    if not endpoint:
        return "/api/ingest/sensor"
    return endpoint if endpoint.startswith("/") else f"/{endpoint}"


def build_stream_url(cfg: dict) -> str:
    scheme = str(cfg.get("scheme") or "http").strip().lower()
    host = str(cfg.get("host") or cfg.get("ip") or "").strip()
    port = cfg.get("port")
    endpoint = _normalize_endpoint(str(cfg.get("endpoint") or "/api/ingest/sensor").strip())

    if not host:
        raise ValueError("Stream enabled, tapi host/IP server belum diisi.")
    if port in (None, ""):
        raise ValueError("Stream enabled, tapi port server belum diisi.")

    try:
        port_int = int(port)
    except (TypeError, ValueError) as exc:
        raise ValueError("Port stream harus angka.") from exc

    if port_int < 1 or port_int > 65535:
        raise ValueError("Port stream harus di range 1-65535.")

    if host.startswith("http://") or host.startswith("https://"):
        base = host.rstrip("/")
        return f"{base}:{port_int}{endpoint}" if ":" not in base.rsplit("/", 1)[-1] else f"{base}{endpoint}"

    return f"{scheme}://{host}:{port_int}{endpoint}"


class SampleStreamer:
    def __init__(self, config: dict, printer=None):
        cfg = config.get("stream", {})
        self.enabled = bool(cfg.get("enabled", False))
        self.printer = printer
        self.timeout_sec = float(cfg.get("timeout_sec", 5))
        self.api_key = str(cfg.get("api_key") or "")
        self.max_queue = int(cfg.get("max_queue", 100))
        self.queue: queue.Queue[dict] = queue.Queue(maxsize=max(self.max_queue, 1))
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.url = build_stream_url(cfg) if self.enabled else ""
        self.sent_count = 0
        self.failed_count = 0
        self.dropped_count = 0
        self.last_error: str | None = None
        self._last_error_print = 0.0

    def start(self) -> None:
        if not self.enabled or self.thread:
            return
        self.thread = threading.Thread(target=self._loop, daemon=True, name="streamer")
        self.thread.start()
        self._print(f"[STREAM] enabled -> {self.url}")

    def stop(self, timeout_sec: float = 5.0) -> None:
        if not self.enabled:
            return
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=timeout_sec)

    def enqueue(self, sample: dict) -> None:
        if not self.enabled:
            return
        try:
            self.queue.put_nowait(sample)
        except queue.Full:
            self.dropped_count += 1
            self.last_error = "stream queue full"

    def stats(self) -> dict:
        return {
            "enabled": self.enabled,
            "url": self.url,
            "sent": self.sent_count,
            "failed": self.failed_count,
            "dropped": self.dropped_count,
            "pending": self.queue.qsize() if self.enabled else 0,
            "last_error": self.last_error,
        }

    def _loop(self) -> None:
        while not self.stop_event.is_set() or not self.queue.empty():
            try:
                sample = self.queue.get(timeout=0.2)
            except queue.Empty:
                continue

            try:
                self._post(sample)
                self.sent_count += 1
            except Exception as exc:  # pragma: no cover - network/runtime dependent
                self.failed_count += 1
                self.last_error = str(exc)
                self._print_error_throttled()
            finally:
                self.queue.task_done()

    def _post(self, sample: dict) -> None:
        body = json.dumps(sample, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        req = request.Request(self.url, data=body, headers=headers, method="POST")
        with request.urlopen(req, timeout=self.timeout_sec) as resp:
            if resp.status >= 400:
                raise error.HTTPError(self.url, resp.status, resp.reason, resp.headers, None)

    def _print(self, message: str) -> None:
        if self.printer:
            self.printer(message)

    def _print_error_throttled(self) -> None:
        now = time.monotonic()
        if now - self._last_error_print < 30:
            return
        self._last_error_print = now
        self._print(f"[STREAM ERROR] {self.last_error}")
