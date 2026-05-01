#!/usr/bin/env python3
"""
database.py — SQLite manager for Micro-UXI dashboard server.
"""

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

_DEFAULT_DB = Path(__file__).parent / "data" / "microuxi.db"


class Database:
    _local = threading.local()

    def __init__(self, db_path: Path = _DEFAULT_DB):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # ── Internal connection (per-thread) ──────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        if not getattr(self._local, "conn", None):
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return self._local.conn

    def _init_schema(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sensor_data (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id   TEXT    NOT NULL,
                probe_type  TEXT    NOT NULL,
                ts          TEXT    NOT NULL,
                received_at TEXT    NOT NULL,
                payload     TEXT    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sensor_dpt
                ON sensor_data(device_id, probe_type, ts DESC);

            CREATE TABLE IF NOT EXISTS overhead_data (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id    TEXT  NOT NULL,
                ts           TEXT  NOT NULL,
                received_at  TEXT  NOT NULL,
                cpu_pct      REAL, mem_pct     REAL,
                mem_used_mb  REAL, mem_avail_mb REAL,
                disk_pct     REAL,
                net_tx_kbs   REAL, net_rx_kbs  REAL,
                temp_c       REAL,
                proc_cpu_pct REAL, proc_rss_mb REAL,
                proc_threads INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_overhead_dt
                ON overhead_data(device_id, ts DESC);

            CREATE TABLE IF NOT EXISTS events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id   TEXT NOT NULL,
                event_type  TEXT NOT NULL,
                severity    TEXT NOT NULL DEFAULT 'warning',
                ts          TEXT NOT NULL,
                received_at TEXT NOT NULL,
                description TEXT,
                payload     TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_events_dt
                ON events(device_id, ts DESC);

            CREATE TABLE IF NOT EXISTS device_config (
                device_id   TEXT PRIMARY KEY,
                config_json TEXT NOT NULL,
                updated_at  TEXT NOT NULL,
                version     INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS device_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS device_status (
                device_id  TEXT PRIMARY KEY,
                last_seen  TEXT NOT NULL,
                ip_address TEXT,
                status     TEXT NOT NULL DEFAULT 'unknown',
                group_id   INTEGER,
                FOREIGN KEY (group_id) REFERENCES device_groups(id) ON DELETE SET NULL
            );
        """)
        
        # Add group_id column if it doesn't exist (for existing DBs)
        try:
            conn.execute("ALTER TABLE device_status ADD COLUMN group_id INTEGER REFERENCES device_groups(id) ON DELETE SET NULL")
        except sqlite3.OperationalError:
            pass # Column already exists
            
        conn.commit()
        conn.close()

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    # ── Sensor data ───────────────────────────────────────────────────────────

    def insert_sensor(self, device_id: str, probe_type: str,
                      ts: str, payload: dict) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO sensor_data (device_id,probe_type,ts,received_at,payload)"
                " VALUES (?,?,?,?,?)",
                (device_id, probe_type, ts, self._now(), json.dumps(payload)),
            )
            return cur.lastrowid

    def get_latest_sensor(self, device_id: str, probe_type: str) -> dict | None:
        row = self._conn().execute(
            "SELECT payload FROM sensor_data"
            " WHERE device_id=? AND probe_type=? ORDER BY ts DESC LIMIT 1",
            (device_id, probe_type),
        ).fetchone()
        return json.loads(row["payload"]) if row else None

    def get_sensor_history(self, device_id: str, probe_type: str,
                           limit: int = 100) -> list[dict]:
        rows = self._conn().execute(
            "SELECT ts, payload FROM sensor_data"
            " WHERE device_id=? AND probe_type=? ORDER BY ts DESC LIMIT ?",
            (device_id, probe_type, limit),
        ).fetchall()
        return [{"ts": r["ts"], **json.loads(r["payload"])} for r in reversed(rows)]

    # ── Overhead data ─────────────────────────────────────────────────────────

    def insert_overhead(self, device_id: str, s: dict) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO overhead_data"
                " (device_id,ts,received_at,cpu_pct,mem_pct,mem_used_mb,mem_avail_mb,"
                "  disk_pct,net_tx_kbs,net_rx_kbs,temp_c,proc_cpu_pct,proc_rss_mb,proc_threads)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (device_id, s.get("ts", self._now()), self._now(),
                 s.get("cpu_pct"), s.get("mem_pct"),
                 s.get("mem_used_mb"), s.get("mem_avail_mb"),
                 s.get("disk_pct"),
                 s.get("net_tx_kbs"), s.get("net_rx_kbs"),
                 s.get("temp_c"),
                 s.get("proc_cpu_pct"), s.get("proc_rss_mb"),
                 s.get("proc_threads")),
            )
            return cur.lastrowid

    def get_overhead_history(self, device_id: str, limit: int = 100) -> list[dict]:
        rows = self._conn().execute(
            "SELECT ts,cpu_pct,mem_pct,mem_used_mb,mem_avail_mb,disk_pct,"
            "       net_tx_kbs,net_rx_kbs,temp_c,proc_cpu_pct,proc_rss_mb,proc_threads"
            " FROM overhead_data WHERE device_id=? ORDER BY ts DESC LIMIT ?",
            (device_id, limit),
        ).fetchall()
        return [dict(r) for r in reversed(rows)]

    # ── Events ────────────────────────────────────────────────────────────────

    def insert_event(self, device_id: str, event_type: str, severity: str,
                     ts: str, description: str, payload: dict = None) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO events"
                " (device_id,event_type,severity,ts,received_at,description,payload)"
                " VALUES (?,?,?,?,?,?,?)",
                (device_id, event_type, severity, ts, self._now(),
                 description, json.dumps(payload) if payload else None),
            )
            return cur.lastrowid

    def get_events(self, device_id: str = None, limit: int = 50) -> list[dict]:
        if device_id:
            rows = self._conn().execute(
                "SELECT id,device_id,event_type,severity,ts,received_at,description"
                " FROM events WHERE device_id=? ORDER BY ts DESC LIMIT ?",
                (device_id, limit),
            ).fetchall()
        else:
            rows = self._conn().execute(
                "SELECT id,device_id,event_type,severity,ts,received_at,description"
                " FROM events ORDER BY ts DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Device config ─────────────────────────────────────────────────────────

    def get_config(self, device_id: str) -> dict | None:
        row = self._conn().execute(
            "SELECT config_json, version FROM device_config WHERE device_id=?",
            (device_id,),
        ).fetchone()
        return {"config": json.loads(row["config_json"]),
                "version": row["version"]} if row else None

    def set_config(self, device_id: str, config: dict) -> int:
        now = self._now()
        with self._conn() as c:
            existing = c.execute(
                "SELECT version FROM device_config WHERE device_id=?",
                (device_id,),
            ).fetchone()
            if existing:
                version = existing["version"] + 1
                c.execute(
                    "UPDATE device_config SET config_json=?,updated_at=?,version=?"
                    " WHERE device_id=?",
                    (json.dumps(config), now, version, device_id),
                )
            else:
                version = 1
                c.execute(
                    "INSERT INTO device_config (device_id,config_json,updated_at,version)"
                    " VALUES (?,?,?,?)",
                    (device_id, json.dumps(config), now, version),
                )
            return version

    # ── Device status ─────────────────────────────────────────────────────────

    def touch_status(self, device_id: str, ip_address: str = None):
        now = self._now()
        with self._conn() as c:
            c.execute(
                "INSERT INTO device_status (device_id,last_seen,ip_address,status)"
                " VALUES (?,?,?,'online')"
                " ON CONFLICT(device_id) DO UPDATE SET"
                "   last_seen=excluded.last_seen,"
                "   ip_address=COALESCE(excluded.ip_address, ip_address),"
                "   status='online'",
                (device_id, now, ip_address),
            )

    def get_all_status(self) -> list[dict]:
        rows = self._conn().execute(
            "SELECT device_id,last_seen,ip_address,status,group_id FROM device_status"
        ).fetchall()
        return [dict(r) for r in rows]

    def set_device_group(self, device_id: str, group_id: int | None):
        with self._conn() as c:
            c.execute(
                "UPDATE device_status SET group_id=? WHERE device_id=?",
                (group_id, device_id)
            )

    # ── Device Groups ─────────────────────────────────────────────────────────

    def create_group(self, name: str) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO device_groups (name, created_at) VALUES (?,?)",
                (name, self._now())
            )
            return cur.lastrowid

    def rename_group(self, group_id: int, name: str):
        with self._conn() as c:
            c.execute("UPDATE device_groups SET name=? WHERE id=?", (name, group_id))

    def delete_group(self, group_id: int):
        with self._conn() as c:
            # ON DELETE SET NULL will handle the devices if FK is enforced.
            # But just in case:
            c.execute("UPDATE device_status SET group_id=NULL WHERE group_id=?", (group_id,))
            c.execute("DELETE FROM device_groups WHERE id=?", (group_id,))

    def get_groups(self) -> list[dict]:
        rows = self._conn().execute("SELECT id, name FROM device_groups ORDER BY name").fetchall()
        return [dict(r) for r in rows]
