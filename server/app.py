#!/usr/bin/env python3
"""
app.py — Micro-UXI Dashboard Server
=====================================
Flask REST API + static file server.

Endpoints:
  POST /api/ingest/sensor     Receive fast/telemetry/throughput data from Arduino
  POST /api/ingest/overhead   Receive overhead monitor data from Arduino
  GET  /api/config            Arduino polls this for remote config
  PUT  /api/config            Dashboard pushes new config for Arduino
  GET  /api/data/latest       Dashboard: latest snapshot per device
  GET  /api/data/history      Dashboard: historical series (probe + limit + device)
  GET  /api/data/events       Dashboard: anomaly event feed
  GET  /api/status            Dashboard: device online/offline status
  POST /api/demo/simulate     Inject synthetic data for demo / testing

Run:
  python app.py
  python app.py --host 0.0.0.0 --port 5000
"""

from __future__ import annotations

import argparse
import json
import random
import time
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from database import Database

# ── Load server config ────────────────────────────────────────────────────────

_CFG_PATH = Path(__file__).parent / "config.json"
with open(_CFG_PATH) as _f:
    _SCFG = json.load(_f)

API_KEY: str = _SCFG.get("api_key", "")
OFFLINE_THRESHOLD: int = _SCFG.get("device_offline_threshold_sec", 120)
DB_PATH = Path(__file__).parent / _SCFG.get("database", {}).get("path", "data/microuxi.db")

db = Database(DB_PATH)

# ── Flask app ─────────────────────────────────────────────────────────────────

STATIC_DIR = Path(__file__).parent / "static"
app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="/static")
CORS(app)

# ── Auth decorator ────────────────────────────────────────────────────────────

def require_key(f):
    """If API_KEY is set, require matching X-API-Key header."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if API_KEY and request.headers.get("X-API-Key") != API_KEY:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return wrapper

# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _seconds_ago(iso_ts: str) -> float:
    try:
        dt = datetime.fromisoformat(iso_ts)
        return (datetime.now(timezone.utc) - dt).total_seconds()
    except Exception:
        return 9999.0


def _device_online(last_seen: str) -> bool:
    return _seconds_ago(last_seen) < OFFLINE_THRESHOLD


def _detect_anomalies(device_id: str, probe_type: str, payload: dict):
    """Simple server-side anomaly detection — mirrors S1-S6 rules."""
    ts = payload.get("ts") or payload.get("collected_at_utc") or _now_iso()

    if probe_type == "fast":
        wifi_up = payload.get("wifi_up", True)
        ping_ok = (payload.get("ping") or {}).get("success", True)
        dns_list = payload.get("dns") or []
        all_dns_fail = bool(dns_list) and all(not d.get("success") for d in dns_list)
        any_dns_slow = any(
            (d.get("latency_ms") or 0) >= 300 for d in dns_list if d.get("success")
        )

        if wifi_up and all_dns_fail and not ping_ok:
            db.insert_event(device_id, "S6_CONNECTIVITY_FLAP", "critical", ts,
                            "Ping + DNS fail, Wi-Fi associated", payload)
        elif wifi_up and all_dns_fail and ping_ok:
            db.insert_event(device_id, "S2_DNS_OUTAGE", "critical", ts,
                            "All DNS domains fail, ping OK", payload)
        elif wifi_up and not ping_ok:
            db.insert_event(device_id, "S3_PACKET_LOSS", "warning", ts,
                            "Ping failed, Wi-Fi associated", payload)
        elif any_dns_slow:
            db.insert_event(device_id, "S1_DNS_DELAY", "warning", ts,
                            "DNS latency ≥ 300 ms detected", payload)

    elif probe_type == "telemetry":
        tel = payload.get("telemetry") or {}
        ping = tel.get("ping") or {}
        rtt = ping.get("rtt_avg_ms")
        loss = ping.get("loss_pct", 0)
        if rtt is not None and rtt > 150 and loss < 10:
            db.insert_event(device_id, "S4_RTT_INCREASE", "warning", ts,
                            f"Sustained high RTT: {rtt:.1f} ms", payload)

    elif probe_type == "throughput":
        summ = payload.get("summary") or {}
        tp = summ.get("throughput_total_mbps")
        avg = tp.get("avg") if isinstance(tp, dict) else None
        if avg is not None and avg < 3.0:
            db.insert_event(device_id, "S5_THROTTLE", "warning", ts,
                            f"Low throughput: {avg:.2f} Mbps", payload)

# ── Routes — Dashboard ────────────────────────────────────────────────────────

@app.get("/")
def index():
    return send_from_directory(str(STATIC_DIR), "index.html")


@app.get("/api/status")
def api_status():
    statuses = db.get_all_status()
    result = []
    for s in statuses:
        secs = _seconds_ago(s["last_seen"])
        result.append({
            **s,
            "online": _device_online(s["last_seen"]),
            "seconds_ago": round(secs, 1),
        })
    return jsonify({"devices": result, "server_time": _now_iso()})


@app.get("/api/data/latest")
def api_data_latest():
    device_id = request.args.get("device_id")
    statuses = db.get_all_status()
    out = {}
    for s in statuses:
        did = s["device_id"]
        if device_id and did != device_id:
            continue
        secs = _seconds_ago(s["last_seen"])
        out[did] = {
            "status": {**s, "online": _device_online(s["last_seen"]),
                       "seconds_ago": round(secs, 1)},
            "telemetry":  db.get_latest_sensor(did, "telemetry"),
            "fast":       db.get_latest_sensor(did, "fast"),
            "throughput": db.get_latest_sensor(did, "throughput"),
            "overhead":   (db.get_overhead_history(did, 1) or [None])[0],
        }
    return jsonify(out)


@app.get("/api/data/history")
def api_data_history():
    device_id = request.args.get("device_id", "uno-q-01")
    probe     = request.args.get("probe", "telemetry")
    limit     = min(int(request.args.get("limit", 100)), 500)

    if probe == "overhead":
        data = db.get_overhead_history(device_id, limit)
    else:
        data = db.get_sensor_history(device_id, probe, limit)

    return jsonify({"device_id": device_id, "probe": probe,
                    "count": len(data), "data": data})


@app.get("/api/data/events")
def api_data_events():
    device_id = request.args.get("device_id")
    limit     = min(int(request.args.get("limit", 50)), 200)
    return jsonify({"events": db.get_events(device_id, limit)})


# ── Routes — Arduino ingest ───────────────────────────────────────────────────

@app.post("/api/ingest/sensor")
@require_key
def api_ingest_sensor():
    """
    Body: single JSON object OR array of objects.
    Each must have: device_id, probe_type ('fast'|'telemetry'|'throughput'), ts
    """
    payload = request.get_json(force=True, silent=True)
    if payload is None:
        return jsonify({"error": "Invalid JSON"}), 400

    items = payload if isinstance(payload, list) else [payload]
    ip = request.remote_addr
    inserted = 0

    for item in items:
        device_id  = item.get("device_id", "unknown")
        probe_type = item.get("probe_type")
        ts         = item.get("ts") or item.get("collected_at_utc") or _now_iso()

        if not probe_type:
            # Auto-detect from keys
            if "telemetry" in item:
                probe_type = "telemetry"
            elif "summary" in item:
                probe_type = "throughput"
            else:
                probe_type = "fast"

        db.insert_sensor(device_id, probe_type, ts, item)
        db.touch_status(device_id, ip)
        _detect_anomalies(device_id, probe_type, item)
        inserted += 1

    return jsonify({"ok": True, "inserted": inserted}), 201


@app.post("/api/ingest/overhead")
@require_key
def api_ingest_overhead():
    payload = request.get_json(force=True, silent=True)
    if payload is None:
        return jsonify({"error": "Invalid JSON"}), 400

    items = payload if isinstance(payload, list) else [payload]
    ip = request.remote_addr
    inserted = 0

    for item in items:
        device_id = item.get("device_id", "unknown")
        db.insert_overhead(device_id, item)
        db.touch_status(device_id, ip)
        inserted += 1

    return jsonify({"ok": True, "inserted": inserted}), 201


# ── Routes — Config (bidirectional control) ───────────────────────────────────

@app.get("/api/config")
@require_key
def api_config_get():
    """Arduino polls this. Returns config + version for the device."""
    device_id = request.args.get("device_id", "uno-q-01")
    result = db.get_config(device_id)
    if result is None:
        return jsonify({"config": None, "version": 0,
                        "message": "No config set for this device."}), 200
    return jsonify(result)


@app.put("/api/config")
def api_config_put():
    """Dashboard pushes new config for a device. No key required (internal use)."""
    body = request.get_json(force=True, silent=True)
    if not body:
        return jsonify({"error": "Invalid JSON"}), 400
    device_id = body.get("device_id", "uno-q-01")
    config    = body.get("config", body)
    version   = db.set_config(device_id, config)
    return jsonify({"ok": True, "device_id": device_id, "version": version})


# ── Routes — Groups ───────────────────────────────────────────────────────────

@app.get("/api/groups")
def api_groups_get():
    return jsonify({"groups": db.get_groups()})

@app.post("/api/groups")
def api_groups_post():
    body = request.get_json(force=True, silent=True)
    name = body.get("name")
    if not name:
        return jsonify({"error": "Name required"}), 400
    try:
        group_id = db.create_group(name)
        return jsonify({"ok": True, "id": group_id, "name": name})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.put("/api/groups/<int:group_id>")
def api_groups_put(group_id):
    body = request.get_json(force=True, silent=True)
    name = body.get("name")
    if name:
        db.rename_group(group_id, name)
    return jsonify({"ok": True})

@app.delete("/api/groups/<int:group_id>")
def api_groups_delete(group_id):
    db.delete_group(group_id)
    return jsonify({"ok": True})

@app.put("/api/devices/<device_id>/group")
def api_device_group_put(device_id):
    body = request.get_json(force=True, silent=True)
    group_id = body.get("group_id")
    db.set_device_group(device_id, group_id)
    return jsonify({"ok": True})

# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Micro-UXI Dashboard Server")
    parser.add_argument("--host", default=_SCFG["server"].get("host", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=_SCFG["server"].get("port", 5000))
    parser.add_argument("--debug", action="store_true",
                        default=_SCFG["server"].get("debug", False))
    args = parser.parse_args()

    print("=" * 56)
    print("  Micro-UXI Dashboard Server")
    print(f"  Listening : http://{args.host}:{args.port}")
    print(f"  Dashboard : http://localhost:{args.port}/")
    print(f"  API key   : {'SET' if API_KEY else 'DISABLED'}")
    print(f"  Database  : {DB_PATH.resolve()}")
    print("=" * 56)

    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
