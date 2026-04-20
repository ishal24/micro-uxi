#!/usr/bin/env python3
"""
event_detector.py — Micro-UXI Real-time Event Detector
========================================================

Script ini dijalankan di Uno Q, berjalan bersama (atau sebagai pengganti)
controller.py. Ia menggunakan FastProbe dan TelemetryProbe secara langsung
(tanpa perlu baca file JSONL) dan mencetak status event setelah setiap sample.

Event yang dideteksi:
  S1  RTT_INCREASE        — RTT rata-rata tinggi, loss rendah   (telemetry)
  S2  DNS_OUTAGE_BURST    — Semua DNS fail, ping OK, latensi DNS rendah (fast)
  S3  PACKET_LOSS_BURST   — Ping fail, wifi tetap nyala          (fast)
  S4  DNS_DELAY           — DNS berhasil tapi sangat lambat      (fast)
  S5  THROTTLE            — Throughput sangat rendah             (throughput)
  S6  CONNECTIVITY_FLAP   — Ping + DNS keduanya fail sekaligus   (fast)

Cara pakai:
  python event_detector.py
  python event_detector.py --config event_config.json
  python event_detector.py --duration 15m
  python event_detector.py --output out/events.jsonl
"""

import argparse
import json
import os
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone

from fast_probe import FastProbe
from telemetry_probe import TelemetryProbe

try:
    from throughput_probe import ThroughputProbe
    _HAS_THROUGHPUT = True
except ImportError:
    _HAS_THROUGHPUT = False


# ─── ANSI colours ────────────────────────────────────────────────────────────

_RST = "\033[0m"
_BLD = "\033[1m"
_RED = "\033[91m"
_GRN = "\033[92m"
_YLW = "\033[93m"
_CYN = "\033[96m"
_GRY = "\033[90m"
_MAG = "\033[95m"
_BLU = "\033[94m"


def _c(col, text):
    return f"{col}{text}{_RST}"


EVENT_COLORS = {
    "S1_RTT_INCREASE":      _YLW,
    "S2_DNS_OUTAGE_BURST":  _RED,
    "S3_PACKET_LOSS_BURST": _RED,
    "S4_DNS_DELAY":         _MAG,
    "S5_THROTTLE":          _CYN,
    "S6_CONNECTIVITY_FLAP": _RED,
}

# Evaluation priority: most-specific first to avoid mis-labelling
PRIORITY_ORDER = [
    "S2_DNS_OUTAGE_BURST",
    "S6_CONNECTIVITY_FLAP",
    "S3_PACKET_LOSS_BURST",
    "S4_DNS_DELAY",
    "S1_RTT_INCREASE",
    "S5_THROTTLE",
]


# ─── Sliding-window confirmer ─────────────────────────────────────────────────

class _Confirmer:
    """
    Requires `window` consecutive True evaluations before declaring an event.
    Prevents single-packet noise from triggering false positives.
    """
    def __init__(self):
        self._bufs: dict[str, deque] = {}

    def push(self, key: str, hit: bool, window: int) -> bool:
        if key not in self._bufs or self._bufs[key].maxlen != window:
            self._bufs[key] = deque(maxlen=window)
        self._bufs[key].append(hit)
        buf = self._bufs[key]
        return len(buf) == window and all(buf)


# ─── Per-event evaluators ─────────────────────────────────────────────────────

def _eval_S1(sample: dict, cond: dict):
    """High sustained RTT from telemetry."""
    ping = (sample.get("telemetry") or {}).get("ping") or {}
    rtt  = ping.get("rtt_avg_ms")
    loss = ping.get("loss_pct")
    if rtt is None:
        return False, "no rtt_avg"
    thresh_rtt  = cond.get("rtt_avg_ms_gt", 150.0)
    thresh_loss = cond.get("loss_pct_lt",   10.0)
    if rtt > thresh_rtt and (loss is None or loss < thresh_loss):
        return True, f"rtt_avg={rtt:.1f}ms > {thresh_rtt}ms  loss={loss}%"
    return False, f"rtt_avg={rtt:.1f}ms (ok)"


def _eval_S2(sample: dict, cond: dict):
    """All DNS fail + ping OK + low DNS latency (fast local drop)."""
    dns_list = sample.get("dns") or []
    ping_ok  = (sample.get("ping") or {}).get("success", False)
    wifi_up  = sample.get("wifi_up", False)
    if not dns_list:
        return False, "no dns data"
    all_fail  = all(not d.get("success") for d in dns_list)
    max_lat   = max((d.get("latency_ms") or 0) for d in dns_list)
    lat_thresh = cond.get("dns_latency_ms_lt", 500)
    if not cond.get("wifi_up", True) or wifi_up:   pass
    if cond.get("wifi_up", True)  and not wifi_up:   return False, "wifi DOWN"
    if cond.get("ping_ok", True)  and not ping_ok:   return False, "ping FAIL → not S2"
    if cond.get("all_dns_fail", True) and not all_fail: return False, "some DNS ok"
    if max_lat >= lat_thresh:
        return False, f"dns_lat={max_lat:.0f}ms too slow for S2 (→ try S4)"
    return True, f"all_dns=FAIL  lat={max_lat:.0f}ms < {lat_thresh}ms  ping=OK"


def _eval_S3(sample: dict, cond: dict):
    """Ping fails while wifi is still up (packet loss or path issue)."""
    ping     = sample.get("ping") or {}
    ping_ok  = ping.get("success", False)
    rtt_ms   = ping.get("rtt_ms")
    wifi_up  = sample.get("wifi_up", False)
    if cond.get("wifi_up", True)   and not wifi_up: return False, "wifi DOWN"
    if cond.get("ping_fail", True) and ping_ok:     return False, f"ping={rtt_ms:.1f}ms OK"

    dns_list     = sample.get("dns") or []
    all_dns_fail = bool(dns_list) and all(not d.get("success") for d in dns_list)
    dns_ok_list  = [d.get("domain","?") for d in dns_list if d.get("success")]
    dns_fail_list= [d.get("domain","?") for d in dns_list if not d.get("success")]

    ping_detail = "ping=TIMEOUT"
    dns_detail  = (
        f"dns=OK({','.join(dns_ok_list)})" if dns_ok_list
        else f"dns=FAIL({','.join(dns_fail_list)})" if dns_fail_list
        else "dns=?"
    )
    return True, f"{ping_detail}  wifi=UP  {dns_detail}"


def _eval_S4(sample: dict, cond: dict):
    """DNS resolves but very slowly."""
    dns_list = sample.get("dns") or []
    ping_ok  = (sample.get("ping") or {}).get("success", False)
    wifi_up  = sample.get("wifi_up", False)
    if not dns_list:                                   return False, "no dns data"
    if cond.get("wifi_up", True) and not wifi_up:     return False, "wifi DOWN"
    if cond.get("ping_ok", True) and not ping_ok:     return False, "ping FAIL"
    all_ok = all(d.get("success") for d in dns_list)
    if not all_ok:                                     return False, "dns FAIL (not slow)"
    thresh = cond.get("any_dns_slow_ms_gte", 300)
    slow   = [d for d in dns_list if (d.get("latency_ms") or 0) >= thresh]
    if not slow:                                       return False, f"dns lat < {thresh}ms"
    detail = ", ".join(f"{d['domain']}={d.get('latency_ms',0):.0f}ms" for d in slow)
    return True, f"slow_dns=[{detail}] >= {thresh}ms  ping=OK"


def _eval_S5(sample: dict, cond: dict):
    """Throughput probe reports low bandwidth."""
    summary = sample.get("summary") or {}
    tp      = summary.get("throughput_total_mbps") or {}
    rh      = summary.get("run_health") or {}
    tp_avg  = tp.get("avg") if isinstance(tp, dict) else None
    total   = rh.get("total_runs", 1) or 1
    ok      = rh.get("successful_http_runs", 0)
    if tp_avg is None:                                 return False, "no throughput data"
    thresh_tp   = cond.get("throughput_avg_mbps_lt", 3.0)
    thresh_rate = cond.get("http_success_rate_lt",   1.0)
    if tp_avg < thresh_tp:
        return True, f"tp_avg={tp_avg:.2f}Mbps < {thresh_tp}Mbps  runs={ok}/{total}"
    if (ok / total) < thresh_rate:
        return True, f"success_rate={ok}/{total} < {thresh_rate}  tp={tp_avg:.2f}Mbps"
    return False, f"tp_avg={tp_avg:.2f}Mbps (ok)"


def _eval_S6(sample: dict, cond: dict):
    """Upstream flap: ping + DNS both fail, wifi still associated."""
    ping_ok  = (sample.get("ping") or {}).get("success", False)
    wifi_up  = sample.get("wifi_up", False)
    dns_list = sample.get("dns") or []
    all_fail = bool(dns_list) and all(not d.get("success") for d in dns_list)
    if cond.get("wifi_up", True)     and not wifi_up:  return False, "wifi DOWN"
    if cond.get("ping_fail", True)   and ping_ok:      return False, "ping OK"
    if cond.get("all_dns_fail", True) and not all_fail: return False, "some DNS ok"
    return True, "ping=FAIL  all_dns=FAIL  wifi=UP  (upstream down)"


EVALUATORS = {
    "S1_RTT_INCREASE":      _eval_S1,
    "S2_DNS_OUTAGE_BURST":  _eval_S2,
    "S3_PACKET_LOSS_BURST": _eval_S3,
    "S4_DNS_DELAY":         _eval_S4,
    "S5_THROTTLE":          _eval_S5,
    "S6_CONNECTIVITY_FLAP": _eval_S6,
}


# ─── Main detector class ──────────────────────────────────────────────────────

class EventDetector:

    def __init__(self, sensor_cfg: dict, event_cfg: dict,
                 output_path: str | None = None,
                 print_normal: bool = False,
                 window_override: int | None = None):

        self._sensor_cfg      = sensor_cfg
        self._events_cfg      = event_cfg.get("events", {})
        self._print_normal    = print_normal
        self._window_override = window_override
        self._confirmer       = _Confirmer()
        self._lock            = threading.Lock()
        self._stop            = threading.Event()
        self._out_f           = open(output_path, "a", encoding="utf-8") if output_path else None

        det = event_cfg.get("detector", {})
        self._grace_sec       = det.get("startup_grace_sec", 10)
        self._heartbeat_sec   = det.get("heartbeat_interval_sec", 30)

        sched = sensor_cfg.get("scheduler", {})
        fp    = sensor_cfg.get("fast_probe", {})
        self._fast_interval       = fp.get("interval_sec", 2)
        self._fast_enabled        = fp.get("enabled", True)
        self._telemetry_interval  = sched.get("telemetry_interval_sec", 30)
        self._throughput_interval = sched.get("throughput_interval_sec", 300)
        self._throughput_enabled  = sensor_cfg.get("modules", {}).get("throughput", False)

        self._start_time  = None   # set in run()
        self._seq         = 0
        self._fast_count  = 0
        self._event_count = 0

    # ── grace period ─────────────────────────────────────────────────────────

    def _in_grace(self) -> bool:
        if self._start_time is None:
            return True
        return (time.monotonic() - self._start_time) < self._grace_sec

    # ── evaluation ───────────────────────────────────────────────────────────

    def _evaluate(self, sample: dict) -> list[tuple[str, str]]:
        probe_type = sample.get("probe_type", "")
        fired      = []

        # Still push to confirmer during grace (to warm up the window)
        # but collect results only after grace ends.
        in_grace = self._in_grace()

        for key in PRIORITY_ORDER:
            ecfg = self._events_cfg.get(key, {})
            if not ecfg.get("enabled", True):
                continue
            if ecfg.get("probe", "fast") != probe_type:
                continue
            evaluator = EVALUATORS.get(key)
            if not evaluator:
                continue
            cond      = ecfg.get("conditions", {})
            window    = self._window_override or ecfg.get("confirm_consecutive", 2)
            hit, info = evaluator(sample, cond)
            confirmed = self._confirmer.push(key, hit, window)
            if confirmed and not in_grace:
                fired.append((key, info))

        # Apply suppressed_by: remove events whose parent is also fired
        fired_keys = {k for k, _ in fired}
        filtered   = []
        for key, info in fired:
            suppressors = self._events_cfg.get(key, {}).get("suppressed_by", [])
            if any(s in fired_keys for s in suppressors):
                continue   # skip — a higher-priority event already covers this
            filtered.append((key, info))

        return filtered

    # ── output ───────────────────────────────────────────────────────────────

    @staticmethod
    def _now_short() -> str:
        return datetime.now(timezone.utc).strftime("%H:%M:%S")

    def _print(self, sample: dict, events: list[tuple[str, str]]):
        ts      = self._now_short()
        seq     = sample.get("seq", "")
        seq_str = f"#{seq:>5}" if seq != "" else ""
        probe   = (sample.get("probe_type") or "?").upper()

        with self._lock:
            if not events:
                if self._print_normal:
                    print(_c(_GRY, f"[{probe:>10} {seq_str}] {ts}  ✓ NORMAL"))
                return

            # Print each confirmed (non-suppressed) event
            for i, (key, info) in enumerate(events):
                col   = EVENT_COLORS.get(key, _BLD)
                label = _c(col, f"⚡ EVENT DETECTED: {key}")
                if i == 0:
                    print(f"{_c(_BLD, f'[{probe:>10} {seq_str}]')} {ts}  {label}")
                else:
                    print(f"{_c(_BLD, f'[{probe:>10}        ]')} {ts}  {label}")
                print(f"  ↳ {_c(col, info)}")
            print()
            sys.stdout.flush()

    def _write_jsonl(self, sample: dict, events: list[tuple[str, str]]):
        if not self._out_f:
            return
        rec = {
            "ts":         sample.get("ts") or sample.get("collected_at_utc"),
            "probe_type": sample.get("probe_type"),
            "seq":        sample.get("seq"),
            "event":      bool(events),
            "event_keys": [k for k, _ in events],
            "details":    {k: info for k, info in events},
        }
        with self._lock:
            self._out_f.write(json.dumps(rec) + "\n")
            self._out_f.flush()

    def _handle(self, sample: dict):
        self._seq += 1
        if sample.get("probe_type") == "fast":
            self._fast_count += 1
        events = self._evaluate(sample)
        if events:
            self._event_count += 1
        self._print(sample, events)
        self._write_jsonl(sample, events)

    # ── worker threads ────────────────────────────────────────────────────────

    def _fast_worker(self):
        probe = FastProbe(self._sensor_cfg)
        while not self._stop.is_set():
            t0 = time.monotonic()
            try:
                result = probe.collect()
                self._handle(result)
            except Exception as e:
                with self._lock:
                    print(_c(_RED, f"[FAST ERROR] {e}"))
            self._stop.wait(max(0, self._fast_interval - (time.monotonic() - t0)))

    def _telemetry_worker(self):
        while not self._stop.is_set():
            t0 = time.monotonic()
            try:
                result = TelemetryProbe(self._sensor_cfg).collect()
                self._handle(result)
            except Exception as e:
                with self._lock:
                    print(_c(_RED, f"[TEL ERROR] {e}"))
            self._stop.wait(max(0, self._telemetry_interval - (time.monotonic() - t0)))

    def _throughput_worker(self):
        # Run first measurement immediately (no stagger),
        # then repeat every throughput_interval thereafter.
        while not self._stop.is_set():
            t0 = time.monotonic()
            try:
                result = ThroughputProbe(self._sensor_cfg).collect()
                self._handle(result)
            except Exception as e:
                with self._lock:
                    print(_c(_RED, f"[THR ERROR] {e}"))
            self._stop.wait(max(0, self._throughput_interval - (time.monotonic() - t0)))

    def _heartbeat_worker(self):
        """Prints a status line every heartbeat_sec so user knows detector is alive."""
        while not self._stop.is_set():
            self._stop.wait(self._heartbeat_sec)
            if self._stop.is_set():
                break
            elapsed = time.monotonic() - self._start_time
            grace   = self._in_grace()
            ts      = self._now_short()
            tag     = _c(_YLW, "(grace)") if grace else _c(_GRN, "✓ NORMAL")
            with self._lock:
                print(_c(_GRY,
                    f"[  DETECTOR] {ts}  {tag}  "
                    f"fast={self._fast_count}  events={self._event_count}  "
                    f"uptime={elapsed:.0f}s"
                ))
                sys.stdout.flush()

    # ── main loop ─────────────────────────────────────────────────────────────

    def run(self, duration_sec: float | None = None):
        dur_label = (f"{duration_sec:.0f}s ({duration_sec/60:.1f} min)"
                     if duration_sec else "indefinite  (Ctrl+C to stop)")

        enabled = []
        if self._fast_enabled:
            enabled.append(f"fast every {self._fast_interval}s  → S2/S3/S4/S6")
        enabled.append(f"telemetry every {self._telemetry_interval}s  → S1")
        if self._throughput_enabled:
            enabled.append(f"throughput every {self._throughput_interval}s  → S5")

        print("=" * 66)
        print("  Micro-UXI Event Detector")
        print("=" * 66)
        for line in enabled:
            print(f"  {line}")
        print(f"  Duration    : {dur_label}")
        print(f"  Grace period: {self._grace_sec}s  (events suppressed at startup)")
        print(f"  Heartbeat   : every {self._heartbeat_sec}s")
        print(f"  Normal      : {'printed' if self._print_normal else 'silent (only events shown)'}")
        print("=" * 66)
        print()

        self._start_time = time.monotonic()

        threads = []
        if self._fast_enabled:
            threads.append(threading.Thread(target=self._fast_worker,      daemon=True, name="fast"))
        threads.append(threading.Thread(target=self._telemetry_worker,     daemon=True, name="telemetry"))
        if self._throughput_enabled and _HAS_THROUGHPUT:
            threads.append(threading.Thread(target=self._throughput_worker, daemon=True, name="throughput"))
        threads.append(threading.Thread(target=self._heartbeat_worker,     daemon=True, name="heartbeat"))

        for t in threads:
            t.start()

        end = (self._start_time + duration_sec) if duration_sec else None
        try:
            if end:
                remaining = end - time.monotonic()
                while remaining > 0 and not self._stop.is_set():
                    self._stop.wait(timeout=min(remaining, 1.0))
                    remaining = end - time.monotonic()
                print("\n[i] Duration reached.")
            else:
                self._stop.wait()
        except KeyboardInterrupt:
            print("\n[!] Stopped by user (Ctrl+C).")

        self._stop.set()
        for t in threads:
            t.join(timeout=10)

        if self._out_f:
            self._out_f.close()

        elapsed = time.monotonic() - self._start_time
        print("=" * 66)
        print(f"  Done. Elapsed: {elapsed:.1f}s  ({elapsed/60:.1f} min)")
        print(f"  Total fast samples : {self._fast_count}")
        print(f"  Total events fired : {self._event_count}")
        print("=" * 66)


# ─── Duration parser ──────────────────────────────────────────────────────────

def _parse_duration(s: str):
    s = s.strip().lower()
    if s in ("0", "inf", "indefinite", "forever"):
        return None
    if s.endswith("h"):   return float(s[:-1]) * 3600
    if s.endswith("m"):   return float(s[:-1]) * 60
    if s.endswith("s"):   return float(s[:-1])
    return float(s)


# ─── Entry point ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Micro-UXI Event Detector — runs on Uno Q, detects fault events in real-time.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Default (reads config.json + event_config.json):
  python event_detector.py

  # Run for 20 minutes, save events to file:
  python event_detector.py --duration 20m --output out/events.jsonl

  # Also print NORMAL samples (verbose):
  python event_detector.py --print-normal

  # Lower confirmation window → faster but noisier detection:
  python event_detector.py --window 1
""",
    )
    parser.add_argument("--config",        default="config.json",
                        help="Sensor config file (default: config.json)")
    parser.add_argument("--event-config",  default="event_config.json",
                        help="Event threshold config (default: event_config.json)")
    parser.add_argument("--duration",      default="0",
                        help="Run duration: 15m / 1h / 0=indefinite (default: 0)")
    parser.add_argument("--output",        default=None, metavar="PATH",
                        help="Append event records to a JSONL file")
    parser.add_argument("--print-normal",  action="store_true",
                        help="Also print lines when no event is detected")
    parser.add_argument("--window",        type=int, default=None, metavar="N",
                        help="Override confirm_consecutive for all events")
    args = parser.parse_args()

    # Load configs
    for path in (args.config, args.event_config):
        if not os.path.isfile(path):
            print(f"[ERROR] File not found: {path}", file=sys.stderr)
            sys.exit(1)

    with open(args.config, encoding="utf-8") as f:
        sensor_cfg = json.load(f)
    with open(args.event_config, encoding="utf-8") as f:
        event_cfg = json.load(f)

    # Output directory
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)

    detector = EventDetector(
        sensor_cfg     = sensor_cfg,
        event_cfg      = event_cfg,
        output_path    = args.output,
        print_normal   = args.print_normal,
        window_override= args.window,
    )
    detector.run(duration_sec=_parse_duration(args.duration))


if __name__ == "__main__":
    main()
