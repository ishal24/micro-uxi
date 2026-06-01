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


def build_base_url(cfg: dict) -> str:
    scheme = str(cfg.get("scheme") or "http").strip().lower()
    host = str(cfg.get("host") or cfg.get("ip") or "").strip()
    port = cfg.get("port")

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
        return f"{base}:{port_int}" if ":" not in base.rsplit("/", 1)[-1] else base

    return f"{scheme}://{host}:{port_int}"


def build_endpoint_url(cfg: dict, endpoint: str) -> str:
    return f"{build_base_url(cfg)}{_normalize_endpoint(endpoint)}"


def build_stream_url(cfg: dict) -> str:
    endpoint = str(cfg.get("sensor_endpoint") or cfg.get("endpoint") or "/api/ingest/sensor").strip()
    return build_endpoint_url(cfg, endpoint)


class SampleStreamer:
    def __init__(self, config: dict, printer=None):
        cfg = config.get("stream", {})
        self.enabled = bool(cfg.get("enabled", False))
        self.printer = printer
        self.timeout_sec = float(cfg.get("timeout_sec", 5))
        self.api_key = str(cfg.get("api_key") or "")
        self.max_queue = int(cfg.get("max_queue", 100))
        self.include_sensor = bool(cfg.get("include_sensor", True))
        self.include_overhead = bool(cfg.get("include_overhead", True))
        self.queue: queue.Queue[tuple[str, dict]] = queue.Queue(maxsize=max(self.max_queue, 1))
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.sensor_url = build_stream_url(cfg) if self.enabled else ""
        overhead_endpoint = str(cfg.get("overhead_endpoint") or "/api/ingest/overhead").strip()
        self.overhead_url = build_endpoint_url(cfg, overhead_endpoint) if self.enabled else ""
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
        self._print(f"[STREAM] sensor -> {self.sensor_url}")
        if self.include_overhead:
            self._print(f"[STREAM] overhead -> {self.overhead_url}")

    def stop(self, timeout_sec: float = 5.0) -> None:
        if not self.enabled:
            return
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=timeout_sec)

    def enqueue(self, sample: dict) -> None:
        if not self.enabled:
            return
        probe_type = sample.get("probe_type")
        if probe_type == "overhead":
            if not self.include_overhead:
                return
            url = self.overhead_url
        else:
            if not self.include_sensor:
                return
            url = self.sensor_url
        try:
            self.queue.put_nowait((url, sample))
        except queue.Full:
            self.dropped_count += 1
            self.last_error = "stream queue full"

    def stats(self) -> dict:
        return {
            "enabled": self.enabled,
            "url": self.sensor_url,
            "sensor_url": self.sensor_url,
            "overhead_url": self.overhead_url,
            "sent": self.sent_count,
            "failed": self.failed_count,
            "dropped": self.dropped_count,
            "pending": self.queue.qsize() if self.enabled else 0,
            "last_error": self.last_error,
        }

    def _loop(self) -> None:
        while not self.stop_event.is_set() or not self.queue.empty():
            try:
                url, sample = self.queue.get(timeout=0.2)
            except queue.Empty:
                continue

            try:
                self._post(url, sample)
                self.sent_count += 1
            except Exception as exc:  # pragma: no cover - network/runtime dependent
                self.failed_count += 1
                self.last_error = str(exc)
                self._print_error_throttled()
            finally:
                self.queue.task_done()

    def _post(self, url: str, sample: dict) -> None:
        body = json.dumps(sample, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        req = request.Request(url, data=body, headers=headers, method="POST")
        with request.urlopen(req, timeout=self.timeout_sec) as resp:
            if resp.status >= 400:
                raise error.HTTPError(url, resp.status, resp.reason, resp.headers, None)

    def _print(self, message: str) -> None:
        if self.printer:
            self.printer(message)

    def _print_error_throttled(self) -> None:
        now = time.monotonic()
        if now - self._last_error_print < 30:
            return
        self._last_error_print = now
        self._print(f"[STREAM ERROR] {self.last_error}")


class RemoteConfigClient:
    def __init__(self, config: dict, printer=None):
        stream_cfg = config.get("stream", {})
        remote_cfg = config.get("remote_control", {})
        self.enabled = bool(stream_cfg.get("enabled", False)) and bool(remote_cfg.get("enabled", True))
        self.printer = printer
        self.timeout_sec = float(remote_cfg.get("timeout_sec", stream_cfg.get("timeout_sec", 5)))
        self.api_key = str(stream_cfg.get("api_key") or "")
        endpoint = str(remote_cfg.get("endpoint") or "/api/config").strip()
        self.url = build_endpoint_url(stream_cfg, endpoint) if self.enabled else ""

    def fetch(self, device_id: str) -> dict | None:
        if not self.enabled:
            return None

        url = f"{self.url}?device_id={device_id}"
        headers = {}
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        try:
            req = request.Request(url, headers=headers, method="GET")
            with request.urlopen(req, timeout=self.timeout_sec) as resp:
                if resp.status != 200:
                    return None
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # pragma: no cover - network/runtime dependent
            if self.printer:
                self.printer(f"[REMOTE CONFIG ERROR] {exc}")
            return None
