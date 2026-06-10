import json
import time
import subprocess
from datetime import datetime
import re

CONFIG_PATH = "tester_config.json"

def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)

def check_wifi(iface):
    try:
        with open(f"/sys/class/net/{iface}/operstate") as f:
            return f.read().strip() == "up"
    except Exception:
        return True

def run_ping_batch(target):
    try:
        res = subprocess.run(["ping", "-c", "5", "-i", "0.2", "-W", "1", target], capture_output=True, text=True)
        out = res.stdout
        
        loss_match = re.search(r'(\d+)% packet loss', out)
        loss_pct = float(loss_match.group(1)) if loss_match else 100.0
        
        rtt_match = re.search(r'rtt min/avg/max/mdev = [\d\.]+/([\d\.]+)/[\d\.]+/[\d\.]+ ms', out)
        rtt_avg = float(rtt_match.group(1)) if rtt_match else None
        
        return {"success": loss_pct < 100, "loss_pct": loss_pct, "rtt_avg_ms": rtt_avg}
    except Exception:
        return {"success": False, "loss_pct": 100.0, "rtt_avg_ms": None}

def main():
    cfg = load_config()
    interval = cfg["scheduler"]["telemetry_interval_sec"]
    N = cfg["rules"]["S4_HIGH_RTT"]["confirm_consecutive"]
    threshold = cfg["thresholds"]["rtt_threshold_ms"]
    
    ping_target = cfg["targets"]["ping_target"]
    iface = cfg["targets"]["iface"]

    print(f"[*] Starting S4 (HIGH_RTT) Monitor")
    print(f"[*] Interval: {interval}s, Threshold: {threshold}ms, N: {N}")

    consecutive_hits = 0
    consecutive_ok = 0
    is_active = False

    while True:
        try:
            start_t = time.monotonic()
            
            wifi_up = check_wifi(iface)
            
            ts = datetime.now().strftime('%H:%M:%S')
            
            hit_this_round = False
            rtt_str = "FAIL"
            loss_str = "100%"
            
            if wifi_up:
                ping_res = run_ping_batch(ping_target)
                if ping_res["success"] and ping_res["rtt_avg_ms"] is not None:
                    rtt_str = f"{ping_res['rtt_avg_ms']:.1f}ms"
                    loss_str = f"{ping_res['loss_pct']:.0f}%"
                    
                    if ping_res["rtt_avg_ms"] >= threshold:
                        # Exclude loss burst scenario (if loss > 15%, S3 should catch it, not S4)
                        if ping_res["loss_pct"] < 15:
                            hit_this_round = True
                else:
                    loss_str = f"{ping_res['loss_pct']:.0f}%"
            
            if hit_this_round:
                consecutive_hits += 1
                consecutive_ok = 0
            else:
                consecutive_hits = 0
                consecutive_ok += 1
                
            status = f"wifi={'UP' if wifi_up else 'DOWN'} rtt={rtt_str} loss={loss_str}"
            print(f"[{ts}] S4 Probe | {status} | hits={consecutive_hits}/{N}")
            
            if not is_active and consecutive_hits >= N:
                is_active = True
                print(f"    >>> [ALARM] S4 HIGH_RTT ACTIVE! (Hits: {consecutive_hits})")
            elif is_active and consecutive_ok >= N:
                is_active = False
                print(f"    >>> [RECOVERY] S4 HIGH_RTT RECOVERED! (OKs: {consecutive_ok})")
            
            elapsed = time.monotonic() - start_t
            time.sleep(max(0, interval - elapsed))
            
        except KeyboardInterrupt:
            print("\n[*] Stopped.")
            break

if __name__ == "__main__":
    main()
