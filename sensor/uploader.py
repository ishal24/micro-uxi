#!/usr/bin/env python3
"""
uploader.py — HTTP Uploader Module for Micro-UXI
=================================================
Handles non-blocking, reliable JSON uploads to the server.
"""

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Dict


class Uploader:
    def __init__(self, config: dict):
        self.config = config
        srv = config.get("server", {})
        self.url = srv.get("url", "").rstrip("/")
        self.enabled = srv.get("upload_enabled", False)
        self.api_key = srv.get("api_key", "")
        
        # Simple queue for background uploads
        self._queue = []
        self._lock = threading.Lock()
        
        self._stop = threading.Event()
        self._thread = None
        
        if self.enabled and self.url:
            self._thread = threading.Thread(target=self._worker, daemon=True, name="uploader")
            self._thread.start()
            logging.info(f"Uploader initialized (target: {self.url})")
        else:
            logging.info("Uploader is disabled or URL not set.")

    def push_sensor(self, payload: Dict[str, Any]):
        if not self.enabled or not self.url:
            return
        self._enqueue(f"{self.url}/api/ingest/sensor", payload)

    def push_overhead(self, payload: Dict[str, Any]):
        if not self.enabled or not self.url:
            return
        self._enqueue(f"{self.url}/api/ingest/overhead", payload)

    def _enqueue(self, endpoint: str, payload: Dict[str, Any]):
        with self._lock:
            # Prevent unbounded growth
            if len(self._queue) < 100:
                self._queue.append((endpoint, payload))
            else:
                # Drop oldest
                self._queue.pop(0)
                self._queue.append((endpoint, payload))

    def _worker(self):
        while not self._stop.is_set():
            item = None
            with self._lock:
                if self._queue:
                    item = self._queue.pop(0)
            
            if item:
                endpoint, payload = item
                success = self._do_post(endpoint, payload)
                if not success:
                    # Basic retry: put it back at the front and sleep longer
                    with self._lock:
                        self._queue.insert(0, item)
                    self._stop.wait(5.0)
                else:
                    # Slight delay between uploads
                    self._stop.wait(0.1)
            else:
                self._stop.wait(1.0)

    def _do_post(self, endpoint: str, payload: dict) -> bool:
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(endpoint, data=data, method="POST")
            req.add_header("Content-Type", "application/json")
            if self.api_key:
                req.add_header("X-API-Key", self.api_key)
            
            with urllib.request.urlopen(req, timeout=5.0) as response:
                return response.status in (200, 201)
        except Exception as e:
            # Silently fail or log debug
            return False

    def get_config(self, device_id: str) -> dict | None:
        """Synchronously pull configuration from the server."""
        if not self.enabled or not self.url:
            return None
            
        try:
            endpoint = f"{self.url}/api/config?device_id={device_id}"
            req = urllib.request.Request(endpoint)
            if self.api_key:
                req.add_header("X-API-Key", self.api_key)
                
            with urllib.request.urlopen(req, timeout=5.0) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode("utf-8"))
                    return data
        except Exception as e:
            pass
        return None

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
