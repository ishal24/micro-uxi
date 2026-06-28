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


def _payload_section(payload: dict, key: str) -> dict:
    nested = payload.get("telemetry")
    if isinstance(nested, dict) and isinstance(nested.get(key), dict):
        return nested[key]
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


def _payload_list(payload: dict, key: str) -> list:
    nested = payload.get("telemetry")
    if isinstance(nested, dict) and isinstance(nested.get(key), list):
        return nested[key]
    value = payload.get(key)
    return value if isinstance(value, list) else []


def _dns_success(row: dict) -> bool:
    if "success" in row:
        return bool(row.get("success"))
    return bool(row.get("dns_success"))


def _dns_latency_ms(row: dict) -> float | None:
    value = row.get("latency_ms")
    if value is None:
        value = row.get("dns_latency_ms")
    return value if isinstance(value, (int, float)) else None


def _detect_anomalies(device_id: str, probe_type: str, payload: dict):
    """Simple server-side anomaly detection — mirrors S1-S6 rules."""
    ts = payload.get("ts") or payload.get("collected_at_utc") or _now_iso()

    if probe_type == "fast":
        wifi = _payload_section(payload, "wifi")
        wifi_up = payload.get("wifi_up", wifi.get("wifi_up", True))
        ping_ok = _payload_section(payload, "ping").get("success", True)
        dns_list = _payload_list(payload, "dns")
        all_dns_fail = bool(dns_list) and all(not _dns_success(d) for d in dns_list)
        any_dns_slow = any(
            (_dns_latency_ms(d) or 0) >= 300 for d in dns_list if _dns_success(d)
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
        ping = _payload_section(payload, "ping")
        rtt = ping.get("rtt_avg_ms")
        loss = ping.get("loss_pct", 0)
        if rtt is not None and rtt > 150 and loss < 10:
            db.insert_event(device_id, "S4_RTT_INCREASE", "warning", ts,
                            f"Sustained high RTT: {rtt:.1f} ms", payload)
        for item in _payload_list(payload, "http"):
            total_ms = item.get("http_total_ms")
            ttfb_ms = item.get("http_ttfb_ms")
            if (
                (isinstance(total_ms, (int, float)) and total_ms >= 2000)
                or (isinstance(ttfb_ms, (int, float)) and ttfb_ms >= 1000)
            ):
                db.insert_event(device_id, "S5_HTTP_SLOW", "warning", ts,
                                f"Slow HTTP response: total={total_ms} ms ttfb={ttfb_ms} ms", payload)
                break

    elif probe_type == "throughput":
        summ   = payload.get("summary") or {}
        # New schema: summary.download; fall back to flat for old schema
        dl_sum = summ.get("download") or summ
        tp     = dl_sum.get("throughput_total_mbps")
        avg    = tp.get("avg") if isinstance(tp, dict) else None
        if avg is not None and avg < 3.0:
            db.insert_event(device_id, "S5_THROTTLE", "warning", ts,
                            f"Low download throughput: {avg:.2f} Mbps", payload)

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
    device_id   = request.args.get("device_id", "uno-q-01")
    probe       = request.args.get("probe", "telemetry")
    limit       = min(int(request.args.get("limit", 500)), 2000)
    since_hours = request.args.get("since_hours", None)

    since_iso = None
    if since_hours:
        try:
            hrs = float(since_hours)
            from datetime import timedelta
            since_dt  = datetime.now(timezone.utc) - timedelta(hours=hrs)
            since_iso = since_dt.isoformat(timespec="seconds")
        except ValueError:
            pass

    if probe == "overhead":
        data = db.get_overhead_history(device_id, limit, since=since_iso)
    else:
        data = db.get_sensor_history(device_id, probe, limit, since=since_iso)

    return jsonify({"device_id": device_id, "probe": probe,
                    "count": len(data), "data": data,
                    "since_iso": since_iso})


@app.get("/api/data/events")
def api_data_events():
    device_id = request.args.get("device_id")
    limit     = min(int(request.args.get("limit", 50)), 200)
    return jsonify({"events": db.get_events(device_id, limit)})


# ── Routes — Devices (dipakai React dashboard) ────────────────────────────────
# Format response sesuai kontrak useLiveMetrics.js → fetchLatest().
# MetricList = list[{label, unit, value, data:[{t,v,label}], static?, services?}]

RANGE_HOURS = {"1h": 1, "6h": 6, "12h": 12, "24h": 24}


def _time_label(dt: datetime) -> str:
    from datetime import timedelta
    start = dt - timedelta(minutes=10)
    hm = lambda d: f"{d.hour:02d}:{d.minute:02d}"
    day = dt.strftime("%a, %b ") + str(dt.day)
    return f"{hm(start)} - {hm(dt)} ({day})"


def _build_metric_list(rows: list[dict], label: str, unit: str,
                       key_fn, decimals: int = 1, static: bool = False) -> dict:
    """Bangun satu MetricList entry dari daftar rows DB."""
    pts = []
    latest = None
    for r in rows:
        try:
            ts_str = r.get("ts") or r.get("received_at")
            dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            v = key_fn(r)
            if v is None:
                continue
            v = float(v)
            pts.append({"t": int(dt.timestamp() * 1000), "v": round(v, decimals), "label": _time_label(dt)})
            latest = v
        except Exception:
            continue
    return {
        "label": label,
        "unit": unit,
        "type": "line",
        "value": f"{latest:.{decimals}f}" if latest is not None else "-",
        "data": [] if static else pts,
        "static": static,
    }


def _build_snapshot(device_id: str, range_hours: int) -> dict | None:
    """Bangun snapshot lengkap {info,wifi,external,overhead,status} dari DB."""
    from datetime import timedelta
    since_dt = datetime.now(timezone.utc) - timedelta(hours=range_hours)
    since_iso = since_dt.isoformat(timespec="seconds")
    limit = range_hours * 60  # asumsi max 1 sample/menit

    # ── Latest telemetry payload (untuk info & static wifi fields) ────────────
    latest_tel = db.get_latest_sensor(device_id, "telemetry")
    wifi_raw = (latest_tel or {}).get("wifi") or {}
    net_raw  = (latest_tel or {}).get("network") or {}

    info = {
        "ssid": wifi_raw.get("wifi_ssid", "-"),
        "ip":   net_raw.get("ip_address",  "-"),
        "mac":  "-",  # MAC tidak dikirim sensor — bisa diisi dari device registry nanti
    }

    # ── Wi-Fi time-series (dari telemetry history) ────────────────────────────
    tel_history = db.get_sensor_history(device_id, "telemetry", limit=limit, since=since_iso)

    wifi = [
        {
            "label": "SSID", "unit": "",
            "value": wifi_raw.get("wifi_ssid", "-"),
            "data": [], "static": True,
        },
        {
            "label": "BSSID", "unit": "",
            "value": wifi_raw.get("wifi_bssid", "-"),
            "data": [], "static": True,
        },
        {
            "label": "Frequency", "unit": "MHz",
            "value": str(wifi_raw.get("wifi_freq_mhz") or "-"),
            "data": [], "static": True,
        },
        _build_metric_list(
            tel_history, "Signal (RSSI)", "dBm",
            lambda r: (r.get("wifi") or {}).get("wifi_rssi_dbm"),
            decimals=0,
        ),
        _build_metric_list(
            tel_history, "Bitrate", "Mbps",
            lambda r: (r.get("wifi") or {}).get("wifi_bitrate_mbps"),
            decimals=1,
        ),
    ]

    # ── External time-series (ping + http dari telemetry) ─────────────────────
    external = [
        _build_metric_list(
            tel_history, "Latency (RTT)", "ms",
            lambda r: (r.get("ping") or {}).get("rtt_avg_ms"),
            decimals=0,
        ),
        _build_metric_list(
            tel_history, "Packet Loss", "%",
            lambda r: (r.get("ping") or {}).get("loss_pct"),
            decimals=2,
        ),
        _build_metric_list(
            tel_history, "Jitter", "ms",
            lambda r: (r.get("ping") or {}).get("rtt_mdev_ms"),
            decimals=0,
        ),
        _build_metric_list(
            tel_history, "HTTP Total", "ms",
            lambda r: (
                sum(x["http_total_ms"] for x in (r.get("http") or []) if x.get("http_total_ms") is not None)
                / max(len([x for x in (r.get("http") or []) if x.get("http_total_ms") is not None]), 1)
                if any(x.get("http_total_ms") is not None for x in (r.get("http") or []))
                else None
            ),
            decimals=0,
        ),
        _build_metric_list(
            tel_history, "HTTP TTFB", "ms",
            lambda r: (
                sum(x["http_ttfb_ms"] for x in (r.get("http") or []) if x.get("http_ttfb_ms") is not None)
                / max(len([x for x in (r.get("http") or []) if x.get("http_ttfb_ms") is not None]), 1)
                if any(x.get("http_ttfb_ms") is not None for x in (r.get("http") or []))
                else None
            ),
            decimals=0,
        ),
    ]

    # ── Overhead time-series ──────────────────────────────────────────────────
    overhead_history = db.get_overhead_history(device_id, limit=limit, since=since_iso)
    overhead = [
        _build_metric_list(overhead_history, "CPU Usage",   "%",  lambda r: r.get("cpu_pct"),  decimals=1),
        _build_metric_list(overhead_history, "Memory Used", "%",  lambda r: r.get("mem_pct"),  decimals=1),
        _build_metric_list(overhead_history, "Disk Used",   "%",  lambda r: r.get("disk_pct"), decimals=1),
        _build_metric_list(overhead_history, "Net RX",      "MB", lambda r: r.get("net_rx_kbs", 0) / 1024 if r.get("net_rx_kbs") is not None else None, decimals=1),
        _build_metric_list(overhead_history, "Net TX",      "MB", lambda r: r.get("net_tx_kbs", 0) / 1024 if r.get("net_tx_kbs") is not None else None, decimals=1),
    ]

    # ── Status + detection events ─────────────────────────────────────────────
    events_raw = db.get_events(device_id, limit=96)
    active_alarms = []
    resolved_list = []
    timeline = [{"h": 0.66 + 0.06 * (i % 3), "muted": i > 80, "marker": False} for i in range(96)]

    for i, ev in enumerate(reversed(events_raw[:96])):
        h = 1.0 if ev.get("severity") == "critical" else 0.75
        timeline[min(i, 95)] = {"h": h, "muted": False, "marker": i == 0}

    # Derive status from recent events (last 10 minutes)
    recent = [e for e in events_raw if _seconds_ago(e["ts"]) < 600]
    if recent:
        crit = [e for e in recent if e.get("severity") == "critical"]
        current_status = "Bad" if crit else "Fair"
        active_alarms = [{"id": e["id"], "label": e["event_type"]} for e in recent[:5]]
    else:
        current_status = "Good"

    # Recent resolved = events older than 10 min but within range
    older = [e for e in events_raw if _seconds_ago(e["ts"]) >= 600]
    resolved_list = [{"id": e["id"], "label": e["event_type"]} for e in older[:5]]

    status = {
        "status":   current_status,
        "events":   timeline,
        "ongoing":  active_alarms,
        "resolved": resolved_list,
    }

    return {"info": info, "wifi": wifi, "external": external,
            "overhead": overhead, "status": status}


@app.get("/api/devices")
def api_devices_list():
    """
    Mengembalikan device list dalam format deviceGroups yang dipakai React sidebar.
    Devices yang belum di-assign ke group muncul di grup default 'SENSORS'.
    """
    statuses = db.get_all_status()
    groups_raw = db.get_groups()  # [{id, name}]

    # Kelompokkan device per group
    group_map: dict[int | None, list] = {}
    for s in statuses:
        gid = s.get("group_id")
        elapsed = _seconds_ago(s["last_seen"])
        device = {
            "id":     s["device_id"],
            "name":   s["device_id"],
            "status": "online" if _device_online(s["last_seen"]) else "disconnected",
            "ip":     s.get("ip_address", "-"),
            "ssid":   "-",
            "mac":    "-",
        }
        group_map.setdefault(gid, []).append(device)

    result = []
    for g in groups_raw:
        result.append({
            "id":      str(g["id"]),
            "name":   g["name"].upper(),
            "devices": group_map.get(g["id"], []),
        })

    # Ungrouped
    ungrouped = group_map.get(None, [])
    if ungrouped:
        result.append({"id": "ungrouped", "name": "SENSORS", "devices": ungrouped})

    return jsonify(result)


@app.get("/api/devices/<device_id>")
def api_devices_get(device_id: str):
    """
    Snapshot metrik satu device: {info, wifi, external, overhead, status}.
    Query param: range = 1h | 6h | 12h | 24h (default: 1h)
    """
    range_param = request.args.get("range", "1h")
    hours = RANGE_HOURS.get(range_param, 1)
    snap = _build_snapshot(device_id, hours)
    if snap is None:
        return jsonify({"error": f"Device '{device_id}' not found"}), 404
    return jsonify(snap)


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
        # Normalisasi field dari OverheadRuntime.collect() ke skema DB
        cpu   = item.get("cpu") or {}
        mem   = item.get("memory") or {}
        disk  = item.get("disk") or {}
        net   = item.get("network") or {}
        normalized = {
            "ts":         item.get("ts"),
            "cpu_pct":    cpu.get("percent"),
            "mem_pct":    mem.get("used_pct"),
            "mem_used_mb":   mem.get("used_bytes",  0) / 1_048_576 if mem.get("used_bytes")  else None,
            "mem_avail_mb":  mem.get("available_bytes", 0) / 1_048_576 if mem.get("available_bytes") else None,
            "disk_pct":   disk.get("used_pct"),
            "net_tx_kbs": net.get("bytes_sent", 0) / 1024 if net.get("bytes_sent") else None,
            "net_rx_kbs": net.get("bytes_recv", 0) / 1024 if net.get("bytes_recv") else None,
        }
        db.insert_overhead(device_id, normalized)
        db.touch_status(device_id, ip)
        inserted += 1

    return jsonify({"ok": True, "inserted": inserted}), 201


@app.post("/api/ingest/monitoring")
@require_key
def api_ingest_monitoring():
    """
    Alias endpoint untuk sensor-side baru (exporter_config paths.monitoring).
    Menerima FastProbe + TelemetryProbe payload dan meneruskan ke handler sensor.
    """
    return api_ingest_sensor()


@app.post("/api/ingest/detection")
@require_key
def api_ingest_detection():
    """
    Terima detection event dari DetectionRuntime.  
    Body: { ts, module, device_id, status, event_key, mode, probe_type, sample_ts, sample_seq, detail }
    """
    payload = request.get_json(force=True, silent=True)
    if payload is None:
        return jsonify({"error": "Invalid JSON"}), 400

    items = payload if isinstance(payload, list) else [payload]
    inserted = 0

    for item in items:
        device_id  = item.get("device_id", "unknown")
        event_key  = item.get("event_key", "UNKNOWN")
        status     = item.get("status", "ALARM")  # ALARM | RECOVERY
        ts         = item.get("ts") or _now_iso()
        detail     = item.get("detail") or {}
        severity   = "critical" if status == "ALARM" else "info"
        description = f"{event_key} → {status}" + (f" | {detail}" if detail else "")
        db.insert_event(device_id, event_key, severity, ts, description, item)
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


# ── Routes — Debug / Inspection ──────────────────────────────────────────────

@app.get("/api/debug")
def api_debug():
    """
    Dev endpoint: returns latest raw payloads + recent events + config + status.
    GET /api/debug?device_id=uno-q-01
    """
    device_id = request.args.get("device_id", "uno-q-01")
    limit     = min(int(request.args.get("limit", 5)), 20)

    out = {
        "device_id":  device_id,
        "server_time": _now_iso(),
        "status":     next((s for s in db.get_all_status() if s["device_id"] == device_id), None),
        "config":     db.get_config(device_id),
        "latest": {
            "telemetry":  db.get_latest_sensor(device_id, "telemetry"),
            "fast":       db.get_latest_sensor(device_id, "fast"),
            "throughput": db.get_latest_sensor(device_id, "throughput"),
            "overhead":   (db.get_overhead_history(device_id, 1) or [None])[0],
        },
        "recent_events": db.get_events(device_id, limit),
        "history_counts": {
            probe: len(db.get_sensor_history(device_id, probe, 500))
            for probe in ("telemetry", "fast", "throughput")
        },
    }
    return jsonify(out)


# ── Routes — Database maintenance ────────────────────────────────────────────

@app.delete("/api/database")
def api_database_clear():
    """Wipe all data from all tables. Use with caution — irreversible."""
    try:
        deleted = db.clear_all()
        return jsonify({"ok": True, "deleted_rows": deleted})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


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

    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)


if __name__ == "__main__":
    main()
