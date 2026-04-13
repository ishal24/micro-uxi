#!/usr/bin/env python3
"""
Fast Probe — lightweight high-frequency sampler.

Runs at 1–2 Hz to catch short-duration burst events that the 30s telemetry
loop would miss:
  S2  DNS Outage Burst     (5–10 s bursts)
  S3  Packet Loss Burst    (3–10 s bursts)
  S6  Connectivity Flap    (3–10 s flaps)

Output fields per sample:
  seq            monotonic counter for this session
  wifi_up        link-layer state from /sys (no subprocess overhead)
  ping.*         single-packet ICMP result
  dns[]          one entry per domain: success flag + latency
  connectivity_ok  all three layers healthy simultaneously
"""

import os
import re
import subprocess
import time
from datetime import datetime, timezone

os.environ["PATH"] += ":/usr/sbin"

try:
    import dns.resolver as _dns_mod
    _HAS_DNSPYTHON = True
except ImportError:
    _HAS_DNSPYTHON = False


class FastProbe:

    def __init__(self, config: dict):
        self.config = config
        fp  = config.get("fast_probe", {})
        dev = config.get("device", {})

        self.device_id    = dev.get("device_id", "unknown")
        self.iface        = dev.get("iface", "wlan0")
        self.ping_target  = fp.get("ping_target",
                            config.get("ping", {}).get("target", "8.8.8.8"))
        self.ping_timeout = int(fp.get("ping_timeout_sec", 1))
        self.dns_domains  = fp.get("dns_domains",
                            config.get("dns", {}).get("domains_routine", ["google.com"]))
        self.dns_timeout  = fp.get("dns_timeout_sec", 2)
        self._seq = 0

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _run(cmd, timeout=5):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return r.returncode, r.stdout.strip(), r.stderr.strip()
        except subprocess.TimeoutExpired:
            return -999, "", "TIMEOUT"
        except Exception as e:
            return -1, "", str(e)

    def _wifi_state(self) -> bool | None:
        """Read link state from /sys — no subprocess, ~0 ms."""
        try:
            with open(f"/sys/class/net/{self.iface}/operstate") as f:
                return f.read().strip() == "up"
        except Exception:
            return None

    def _ping_once(self):
        """
        Fire a single ICMP packet.
        Returns (success: bool, rtt_ms: float | None).
        """
        rc, out, _ = self._run(
            ["ping", "-c", "1", "-W", str(self.ping_timeout), self.ping_target],
            timeout=self.ping_timeout + 2,
        )
        success = rc == 0
        rtt_ms  = None
        if success:
            m = re.search(r"time=([0-9.]+)", out)
            if m:
                rtt_ms = float(m.group(1))
        return success, rtt_ms

    def _dns_once(self, domain: str):
        """
        Single DNS resolution.
        Uses dnspython (preferred) or dig fallback.
        Returns (success: bool, latency_ms: float | None).
        Cache is intentionally bypassed — we want to see live resolver performance.
        """
        if _HAS_DNSPYTHON:
            resolver = _dns_mod.Resolver()
            resolver.cache    = None          # bypass cache — measure live latency
            resolver.lifetime = self.dns_timeout
            start = time.monotonic()
            try:
                resolver.resolve(domain, "A")
                return True, round((time.monotonic() - start) * 1000, 2)
            except Exception:
                return False, round((time.monotonic() - start) * 1000, 2)
        else:
            # fallback: dig with hard timeout
            start = time.monotonic()
            rc, out, _ = self._run(
                ["dig", domain, f"+time={int(self.dns_timeout)}", "+tries=1", "+short"],
                timeout=self.dns_timeout + 1,
            )
            elapsed = round((time.monotonic() - start) * 1000, 2)
            return (rc == 0 and bool(out.strip())), elapsed

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def collect(self) -> dict:
        self._seq += 1

        wifi_up  = self._wifi_state()
        ping_ok, rtt_ms = self._ping_once()

        dns_results = []
        for domain in self.dns_domains:
            ok, lat = self._dns_once(domain)
            dns_results.append({
                "domain":     domain,
                "success":    ok,
                "latency_ms": lat,
            })

        dns_all_ok      = all(d["success"] for d in dns_results)
        connectivity_ok = bool(wifi_up) and ping_ok and dns_all_ok

        return {
            "probe_type":       "fast",
            "ts":               datetime.now(timezone.utc).isoformat(),
            "seq":              self._seq,
            "device_id":        self.device_id,
            "wifi_up":          wifi_up,
            "ping": {
                "target":  self.ping_target,
                "success": ping_ok,
                "rtt_ms":  rtt_ms,
            },
            "dns":              dns_results,
            "connectivity_ok":  connectivity_ok,
        }


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

def _load_config(path):
    import json
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    import argparse, json
    p = argparse.ArgumentParser(description="Micro-UXI fast probe (standalone)")
    p.add_argument("--config", default="config.json")
    p.add_argument("--count", type=int, default=5, help="Number of samples to collect")
    p.add_argument("--interval", type=float, default=1.0, help="Seconds between samples")
    args = p.parse_args()

    config = _load_config(args.config)
    probe  = FastProbe(config)
    for _ in range(args.count):
        t0     = time.monotonic()
        result = probe.collect()
        print(json.dumps(result, indent=2))
        elapsed = time.monotonic() - t0
        time.sleep(max(0, args.interval - elapsed))


if __name__ == "__main__":
    main()
