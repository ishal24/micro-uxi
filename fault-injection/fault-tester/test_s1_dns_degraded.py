import json
import time
import subprocess
from datetime import datetime

CONFIG_PATH = "tester_config.json"

def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)

def run_ping(target):
    try:
        res = subprocess.run(["ping", "-c", "1", "-W", "1", target], capture_output=True, text=True)
        return res.returncode == 0
    except Exception:
        return False

def run_dns(target, resolver):
    try:
        start = time.monotonic()
        res = subprocess.run(["dig", f"@{resolver}", "+short", "+time=2", target], capture_output=True, text=True)
        latency = (time.monotonic() - start) * 1000
        return {"success": res.returncode == 0 and bool(res.stdout.strip()), "latency_ms": latency}
    except Exception:
        return {"success": False, "latency_ms": 0}

def check_wifi(iface):
    try:
        with open(f"/sys/class/net/{iface}/operstate") as f:
            return f.read().strip() == "up"
    except Exception:
        return True # Fallback

def main():
    cfg = load_config()
    interval = cfg["scheduler"]["fast_interval_sec"]
    N = cfg["rules"]["S1_DNS_DEGRADED"]["confirm_consecutive"]
    threshold = cfg["thresholds"]["dns_latency_threshold_ms"]
    
    ping_target = cfg["targets"]["ping_target"]
    dns_targets = cfg["targets"]["dns_targets"]
    resolver = cfg["targets"]["dns_resolver"]
    iface = cfg["targets"]["iface"]

    print(f"[*] Starting S1 (DNS_DEGRADED) Monitor")
    print(f"[*] Interval: {interval}s, Threshold: {threshold}ms, N: {N}")

    consecutive_hits = 0
    consecutive_ok = 0
    is_active = False

    while True:
        try:
            start_t = time.monotonic()
            
            wifi_up = check_wifi(iface)
            ping_ok = run_ping(ping_target)
            
            hit_this_round = False
            latencies = []
            
            if wifi_up and ping_ok:
                for t in dns_targets:
                    res = run_dns(t["name"], resolver)
                    if res["success"]:
                        latencies.append(f"{t['name']}={res['latency_ms']:.1f}ms")
                        if res["latency_ms"] >= threshold:
                            hit_this_round = True
            
            ts = datetime.now().strftime('%H:%M:%S')
            
            if hit_this_round:
                consecutive_hits += 1
                consecutive_ok = 0
            else:
                consecutive_hits = 0
                consecutive_ok += 1
            
            status = f"wifi={'UP' if wifi_up else 'DOWN'} ping={'OK' if ping_ok else 'FAIL'} dns=[{', '.join(latencies)}]"
            print(f"[{ts}] S1 Probe | {status} | hits={consecutive_hits}/{N}")
            
            if not is_active and consecutive_hits >= N:
                is_active = True
                print(f"    >>> [ALARM] S1 DNS_DEGRADED ACTIVE! (Hits: {consecutive_hits})")
            elif is_active and consecutive_ok >= N:
                is_active = False
                print(f"    >>> [RECOVERY] S1 DNS_DEGRADED RECOVERED! (OKs: {consecutive_ok})")
            
            elapsed = time.monotonic() - start_t
            time.sleep(max(0, interval - elapsed))
            
        except KeyboardInterrupt:
            print("\n[*] Stopped.")
            break

if __name__ == "__main__":
    main()
