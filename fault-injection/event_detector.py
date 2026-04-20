#!/usr/bin/env python3
"""
event_detector.py — Micro-UXI Fault Event Detector
====================================================

Tails the sensor's JSONL output files (fast, telemetry, throughput) and
classifies each sample against configurable thresholds to decide whether a
network-fault *event* is currently active — and which type it is.

Event types matched:
  S1  RTT_INCREASE        — Sustained high ping latency (telemetry)
  S2  DNS_OUTAGE_BURST    — All DNS fail, ping OK, low latency (fast, iptables drop)
  S3  PACKET_LOSS_BURST   — Ping fails, DNS may still work (fast)
  S4  DNS_DELAY           — DNS succeeds but abnormally slow (fast)
  S5  THROTTLE            — Low throughput detected (throughput)
  S6  CONNECTIVITY_FLAP   — Ping + DNS both fail, wifi stays up (fast)

Usage:
  python event_detector.py --fast    sensor/out/fast_<session>.jsonl
  python event_detector.py --fast    sensor/out/fast_<session>.jsonl \\
                           --tel     sensor/out/telemetry_<session>.jsonl \\
                           --thr     sensor/out/throughput_<session>.jsonl \\
                           --config  fault-injection/event_config.json

Options:
  --fast    PATH          Path to fast probe JSONL (required for S2/S3/S4/S6)
  --tel     PATH          Path to telemetry JSONL (required for S1)
  --thr     PATH          Path to throughput JSONL (required for S5)
  --config  PATH          Event threshold config (default: event_config.json)
  --no-follow             Read existing lines and exit (default: tail/follow)
  --print-normal          Also print lines when no event is detected
  --output  PATH          Append event decisions to a JSONL file
  --window  N             Override confirm_consecutive window from config
"""

import argparse
import json
import os
import sys
import time
from collections import deque
from datetime import datetime, timezone


# ── ANSI colours ────────────────────────────────────────────────────────────

_RESET  = "\033[0m"
_BOLD   = "\033[1m"
_RED    = "\033[91m"
_GRN    = "\033[92m"
_YLW    = "\033[93m"
_CYN    = "\033[96m"
_GRY    = "\033[90m"
_MAG    = "\033[95m"


def _c(color: str, text: str) -> str:
    return f"{color}{text}{_RESET}"


# ── Event labels ─────────────────────────────────────────────────────────────

EVENT_COLORS = {
    "S1_RTT_INCREASE":     _YLW,
    "S2_DNS_OUTAGE_BURST": _RED,
    "S3_PACKET_LOSS_BURST":_RED,
    "S4_DNS_DELAY":        _MAG,
    "S5_THROTTLE":         _CYN,
    "S6_CONNECTIVITY_FLAP":_RED,
}

NORMAL_LABEL = _c(_GRN, "NORMAL")


# ── Config loader ─────────────────────────────────────────────────────────────

def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ── Individual event evaluators ───────────────────────────────────────────────

def _eval_S1(sample: dict, cond: dict) -> tuple[bool, str]:
    """S1: High RTT from telemetry ping data."""
    tel = sample.get("telemetry", {})
    ping = tel.get("ping", {})
    rtt_avg = ping.get("rtt_avg_ms")
    loss    = ping.get("loss_pct")

    if rtt_avg is None:
        return False, "no rtt_avg"

    rtt_thresh  = cond.get("rtt_avg_ms_gt", 150.0)
    loss_thresh = cond.get("loss_pct_lt", 10.0)

    if rtt_avg > rtt_thresh and (loss is None or loss < loss_thresh):
        return True, f"rtt_avg={rtt_avg:.1f}ms > {rtt_thresh}ms, loss={loss}%"
    return False, f"rtt_avg={rtt_avg:.1f}ms (ok)"


def _eval_S2(sample: dict, cond: dict) -> tuple[bool, str]:
    """S2: All DNS fail, ping OK, DNS latency is fast (local drop)."""
    dns_list   = sample.get("dns") or []
    ping       = sample.get("ping", {})
    wifi_up    = sample.get("wifi_up", False)
    ping_ok    = ping.get("success", False)

    all_dns_fail  = bool(dns_list) and all(not d.get("success") for d in dns_list)
    max_dns_lat   = max((d.get("latency_ms") or 0) for d in dns_list) if dns_list else 0
    lat_thresh    = cond.get("dns_latency_ms_lt", 500)

    need_wifi  = cond.get("wifi_up", True)
    need_ping  = cond.get("ping_ok", True)
    need_allfail = cond.get("all_dns_fail", True)

    checks = []
    if need_allfail and not all_dns_fail:
        return False, f"some DNS ok"
    if need_ping and not ping_ok:
        return False, f"ping FAIL (not S2)"
    if need_wifi and not wifi_up:
        return False, f"wifi DOWN"
    if max_dns_lat >= lat_thresh:
        return False, f"dns_lat={max_dns_lat:.0f}ms (too slow for S2, looks like S4)"

    checks.append(f"all_dns=FAIL, lat={max_dns_lat:.0f}ms<{lat_thresh}ms, ping=OK")
    return True, " ".join(checks)


def _eval_S3(sample: dict, cond: dict) -> tuple[bool, str]:
    """S3: Ping fails, wifi still up (packet loss burst)."""
    ping     = sample.get("ping", {})
    wifi_up  = sample.get("wifi_up", False)
    ping_ok  = ping.get("success", False)
    dns_list = sample.get("dns") or []

    need_wifi    = cond.get("wifi_up", True)
    need_pingfail= cond.get("ping_fail", True)
    dns_lat_thresh = cond.get("dns_latency_ms_gte", 300)

    if need_wifi and not wifi_up:
        return False, "wifi DOWN"
    if need_pingfail and ping_ok:
        return False, "ping OK (not loss)"

    # S3 is distinguishable from S6 because DNS may still succeed sometimes.
    # But both can fail — the difference is confirmed by the all_dns_fail check
    # in S6.  Here we just need ping to fail.
    all_dns_fail = bool(dns_list) and all(not d.get("success") for d in dns_list)
    # If ALL dns also fail → that looks more like S6 (handled elsewhere),
    # so we let the multi-event logic sort priorities.
    return True, f"ping=FAIL, wifi=UP, all_dns_fail={all_dns_fail}"


def _eval_S4(sample: dict, cond: dict) -> tuple[bool, str]:
    """S4: DNS succeeds but very slow (DNS delay injected)."""
    dns_list = sample.get("dns") or []
    ping     = sample.get("ping", {})
    wifi_up  = sample.get("wifi_up", False)
    ping_ok  = ping.get("success", False)

    slow_thresh  = cond.get("any_dns_slow_ms_gte", 300)
    need_wifi    = cond.get("wifi_up", True)
    need_ping    = cond.get("ping_ok", True)
    need_notfail = not cond.get("all_dns_fail", False)

    if not dns_list:
        return False, "no dns data"
    if need_wifi and not wifi_up:
        return False, "wifi DOWN"
    if need_ping and not ping_ok:
        return False, "ping FAIL"

    # All DNS must succeed
    all_ok = all(d.get("success") for d in dns_list)
    if need_notfail and not all_ok:
        return False, "dns FAIL (not slow success)"

    # At least one DNS must be slow
    slow_entries = [d for d in dns_list if (d.get("latency_ms") or 0) >= slow_thresh]
    if slow_entries:
        details = ", ".join(
            f"{d['domain']}={d.get('latency_ms', '?'):.0f}ms" for d in slow_entries
        )
        return True, f"slow_dns=[{details}] >= {slow_thresh}ms, ping=OK"
    return False, f"max_dns_lat < {slow_thresh}ms"


def _eval_S5(sample: dict, cond: dict) -> tuple[bool, str]:
    """S5: Low throughput from throughput probe."""
    summary = sample.get("summary", {})
    tp      = summary.get("throughput_total_mbps", {})
    rh      = summary.get("run_health", {})

    tp_avg = tp.get("avg") if isinstance(tp, dict) else None
    total  = rh.get("total_runs", 1) or 1
    ok     = rh.get("successful_http_runs", 0)
    success_rate = ok / total

    tp_thresh   = cond.get("throughput_avg_mbps_lt", 3.0)
    rate_thresh = cond.get("http_success_rate_lt", 1.0)

    if tp_avg is None:
        return False, "no throughput data"
    if tp_avg < tp_thresh:
        return True, f"tp_avg={tp_avg:.2f}Mbps < {tp_thresh}Mbps, success={ok}/{total}"
    if success_rate < rate_thresh:
        return True, f"success_rate={success_rate:.2f} < {rate_thresh}, tp={tp_avg:.2f}Mbps"
    return False, f"tp_avg={tp_avg:.2f}Mbps (ok)"


def _eval_S6(sample: dict, cond: dict) -> tuple[bool, str]:
    """S6: Connectivity flap — ping + dns both fail, wifi still up."""
    ping     = sample.get("ping", {})
    wifi_up  = sample.get("wifi_up", False)
    dns_list = sample.get("dns") or []
    ping_ok  = ping.get("success", False)

    need_wifi     = cond.get("wifi_up", True)
    need_pingfail = cond.get("ping_fail", True)
    need_allfail  = cond.get("all_dns_fail", True)

    all_dns_fail = bool(dns_list) and all(not d.get("success") for d in dns_list)

    if need_wifi and not wifi_up:
        return False, "wifi DOWN"
    if need_pingfail and ping_ok:
        return False, "ping OK"
    if need_allfail and not all_dns_fail:
        return False, "some dns ok"

    return True, f"ping=FAIL, all_dns=FAIL, wifi=UP (upstream down)"


EVALUATORS = {
    "S1_RTT_INCREASE":      _eval_S1,
    "S2_DNS_OUTAGE_BURST":  _eval_S2,
    "S3_PACKET_LOSS_BURST": _eval_S3,
    "S4_DNS_DELAY":         _eval_S4,
    "S5_THROTTLE":          _eval_S5,
    "S6_CONNECTIVITY_FLAP": _eval_S6,
}

# Priority order: more-specific events first so the label is unambiguous.
PRIORITY_ORDER = [
    "S2_DNS_OUTAGE_BURST",  # DNS fail + ping ok  → most specific
    "S6_CONNECTIVITY_FLAP", # ping + dns fail      → second
    "S3_PACKET_LOSS_BURST", # ping fail only
    "S4_DNS_DELAY",         # dns slow but success
    "S1_RTT_INCREASE",      # telemetry high rtt
    "S5_THROTTLE",          # throughput low
]


# ── Sliding-window confirmation ───────────────────────────────────────────────

class EventConfirmer:
    """
    Tracks a rolling window of boolean hits per event key.
    An event is *confirmed* when the last `window` consecutive
    evaluations all return True.
    """

    def __init__(self, window: int):
        self._window   = window
        self._buffers: dict[str, deque] = {}

    def push(self, key: str, hit: bool, window_override: int | None = None) -> bool:
        w = window_override or self._window
        if key not in self._buffers:
            self._buffers[key] = deque(maxlen=w)
        buf = self._buffers[key]
        buf.maxlen  # ensure correct size
        if len(buf) == 0 or buf.maxlen != w:
            self._buffers[key] = deque(maxlen=w)
            buf = self._buffers[key]
        buf.append(hit)
        return len(buf) == w and all(buf)

    def clear(self, key: str):
        if key in self._buffers:
            self._buffers[key].clear()


# ── JSONL tail reader ─────────────────────────────────────────────────────────

def tail_jsonl(path: str, follow: bool = True):
    """
    Generator: yields parsed JSON dicts from a JSONL file.
    In follow mode it keeps polling for new lines indefinitely.
    """
    with open(path, encoding="utf-8") as f:
        # seek to 0 — read all existing lines first
        while True:
            line = f.readline()
            if line:
                line = line.strip()
                if line:
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        pass
            else:
                if not follow:
                    return
                time.sleep(0.25)


# ── Detector ──────────────────────────────────────────────────────────────────

class EventDetector:

    def __init__(self, cfg: dict, args):
        self.events_cfg   = cfg.get("events", {})
        det               = cfg.get("detector", {})

        self.follow       = args.follow if hasattr(args, "follow") else det.get("follow_mode", True)
        self.print_normal = args.print_normal if hasattr(args, "print_normal") else det.get("print_normal", False)
        self.output_path  = args.output if hasattr(args, "output") else det.get("output_jsonl")
        self.window_override = getattr(args, "window", None)

        self.fast_path  = getattr(args, "fast", None)
        self.tel_path   = getattr(args, "tel", None)
        self.thr_path   = getattr(args, "thr", None)

        self._confirmer = EventConfirmer(window=det.get("window_size", 3))
        self._out_f     = None

        if self.output_path:
            self._out_f = open(self.output_path, "a", encoding="utf-8")

    # ── evaluation ────────────────────────────────────────────────────────────

    def _evaluate_sample(self, sample: dict) -> list[tuple[str, str]]:
        """
        Return list of (event_key, detail_str) for all events that are
        currently confirmed true in priority order.
        """
        probe_type = sample.get("probe_type", "")
        fired      = []

        for key in PRIORITY_ORDER:
            ecfg = self.events_cfg.get(key, {})
            if not ecfg.get("enabled", True):
                continue

            required_probe = ecfg.get("probe", "fast")
            if required_probe != probe_type:
                continue

            evaluator = EVALUATORS.get(key)
            if evaluator is None:
                continue

            cond      = ecfg.get("conditions", {})
            w         = self.window_override or ecfg.get("confirm_consecutive", 2)
            hit, info = evaluator(sample, cond)
            confirmed = self._confirmer.push(key, hit, w)

            if confirmed:
                fired.append((key, info))

        return fired

    # ── display ───────────────────────────────────────────────────────────────

    @staticmethod
    def _ts_short(sample: dict) -> str:
        ts = sample.get("ts") or sample.get("collected_at_utc") or ""
        if "T" in ts:
            return ts.split("T")[1][:8]
        return ts[:8] if ts else "??"

    def _print_event(self, sample: dict, events: list[tuple[str, str]]):
        ts  = self._ts_short(sample)
        seq = sample.get("seq", "")
        seq_str = f"#{seq:>5}" if seq != "" else ""

        if not events:
            if self.print_normal:
                print(_c(_GRY, f"[{sample.get('probe_type','?').upper():>10} {seq_str}] {ts}  ✓ NORMAL"))
            return

        # Take highest-priority event for the banner label
        primary_key, primary_info = events[0]
        color = EVENT_COLORS.get(primary_key, _BOLD)
        label = _c(color, f"⚡ EVENT: {primary_key}")

        probe = sample.get("probe_type", "?").upper()
        print(f"{_c(_BOLD, f'[{probe:>10} {seq_str}]')} {ts}  {label}")
        print(f"  ↳ {_c(color, primary_info)}")

        if len(events) > 1:
            for k, info in events[1:]:
                col = EVENT_COLORS.get(k, _YLW)
                print(f"  ↳ also: {_c(col, k)}  {_c(_GRY, info)}")

        print()

    def _write_output(self, sample: dict, events: list[tuple[str, str]]):
        if self._out_f is None:
            return
        rec = {
            "ts":         sample.get("ts") or sample.get("collected_at_utc"),
            "probe_type": sample.get("probe_type"),
            "seq":        sample.get("seq"),
            "event":      bool(events),
            "event_keys": [k for k, _ in events],
            "details":    {k: info for k, info in events},
        }
        self._out_f.write(json.dumps(rec) + "\n")
        self._out_f.flush()

    # ── per-file runners ──────────────────────────────────────────────────────

    def _run_stream(self, path: str):
        for sample in tail_jsonl(path, follow=self.follow):
            events = self._evaluate_sample(sample)
            self._print_event(sample, events)
            self._write_output(sample, events)

    # ── multi-file merged runner (round-robin poll) ───────────────────────────

    def run(self):
        files = []
        if self.fast_path:
            files.append(("fast",       self.fast_path))
        if self.tel_path:
            files.append(("telemetry",  self.tel_path))
        if self.thr_path:
            files.append(("throughput", self.thr_path))

        if not files:
            print("[ERROR] No input files specified. Use --fast / --tel / --thr.", file=sys.stderr)
            sys.exit(1)

        if len(files) == 1:
            # Simple mode — just tail one file
            self._run_stream(files[0][1])
        else:
            # Multi-file: open all simultaneously and interleave by monotonic read
            handles  = [open(p, encoding="utf-8") for _, p in files]
            try:
                while True:
                    progress = False
                    for fh in handles:
                        line = fh.readline()
                        if line:
                            line = line.strip()
                            if line:
                                try:
                                    sample = json.loads(line)
                                    events = self._evaluate_sample(sample)
                                    self._print_event(sample, events)
                                    self._write_output(sample, events)
                                    progress = True
                                except json.JSONDecodeError:
                                    pass
                    if not progress:
                        if not self.follow:
                            break
                        time.sleep(0.25)
            finally:
                for fh in handles:
                    fh.close()

    def close(self):
        if self._out_f:
            self._out_f.close()


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Micro-UXI Event Detector — classifies fault events from sensor JSONL output.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Follow a live fast-probe file:
  python event_detector.py --fast sensor/out/fast_20260421T...jsonl

  # Follow all three probes simultaneously:
  python event_detector.py \\
      --fast sensor/out/fast_*.jsonl \\
      --tel  sensor/out/telemetry_*.jsonl \\
      --thr  sensor/out/throughput_*.jsonl

  # Replay existing file (no follow), save detections:
  python event_detector.py --fast fast.jsonl --no-follow --output detections.jsonl

  # Use a custom config:
  python event_detector.py --fast fast.jsonl --config my_thresholds.json
""",
    )
    parser.add_argument("--fast",    metavar="PATH", default=None,
                        help="Fast probe JSONL file (S2/S3/S4/S6)")
    parser.add_argument("--tel",     metavar="PATH", default=None,
                        help="Telemetry JSONL file (S1)")
    parser.add_argument("--thr",     metavar="PATH", default=None,
                        help="Throughput JSONL file (S5)")
    parser.add_argument("--config",  metavar="PATH",
                        default=os.path.join(os.path.dirname(__file__), "event_config.json"),
                        help="Event threshold config JSON (default: event_config.json)")
    parser.add_argument("--no-follow", dest="follow", action="store_false", default=True,
                        help="Read existing lines and exit (don't tail)")
    parser.add_argument("--print-normal", action="store_true", default=False,
                        help="Also print lines when no event is detected")
    parser.add_argument("--output",  metavar="PATH", default=None,
                        help="Append event decisions to a JSONL file")
    parser.add_argument("--window",  metavar="N", type=int, default=None,
                        help="Override confirm_consecutive window for all events")
    args = parser.parse_args()

    if not os.path.isfile(args.config):
        print(f"[ERROR] Config file not found: {args.config}", file=sys.stderr)
        sys.exit(1)

    cfg = load_config(args.config)

    print("=" * 66)
    print("  Micro-UXI Event Detector")
    print("=" * 66)
    if args.fast:
        print(f"  Fast    : {args.fast}")
    if args.tel:
        print(f"  Telemetry: {args.tel}")
    if args.thr:
        print(f"  Throughput: {args.thr}")
    print(f"  Config  : {args.config}")
    print(f"  Follow  : {args.follow}")
    print(f"  Output  : {args.output or '(stdout only)'}")
    print("=" * 66)
    print(f"  Monitoring for events: {', '.join(PRIORITY_ORDER)}")
    print("=" * 66)
    print()

    detector = EventDetector(cfg, args)
    try:
        detector.run()
    except KeyboardInterrupt:
        print("\n[!] Stopped by user.")
    finally:
        detector.close()


if __name__ == "__main__":
    main()
