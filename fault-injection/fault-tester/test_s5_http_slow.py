import json
import time
import subprocess
from datetime import datetime

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

def run_http(url):
    try:
        cmd = [
            "curl", "-s", "-o", "/dev/null", 
            "-w", "%{http_code}:%{time_total}:%{time_starttransfer}",
            "--connect-timeout", "5", "--max-time", "15", url
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
             return {"curl_rc": res.returncode, "success": False}
        
        parts = res.stdout.strip().split(":")
        status = int(parts[0])
        total_ms = float(parts[1]) * 1000
        ttfb_ms = float(parts[2]) * 1000
        
        return {
            "curl_rc": 0,
            "success": True,
            "status": status,
            "total_ms": total_ms,
            "ttfb_ms": ttfb_ms
        }
    except Exception:
        return {"curl_rc": -1, "success": False}

def main():
    cfg = load_config()
    interval = cfg["scheduler"]["telemetry_interval_sec"]
    N = cfg["rules"]["S5_HTTP_SLOW"]["confirm_consecutive"]
    total_threshold = cfg["thresholds"]["http_total_threshold_ms"]
    ttfb_threshold = cfg["thresholds"]["http_ttfb_threshold_ms"]
    
    http_targets = cfg["targets"]["http_targets"]
    iface = cfg["targets"]["iface"]

    print(f"[*] Starting S5 (HTTP_SLOW) Monitor")
    print(f"[*] Interval: {interval}s, Total Threshold: {total_threshold}ms, TTFB Threshold: {ttfb_threshold}ms, N: {N}")

    consecutive_hits = 0
    consecutive_ok = 0
    is_active = False

    while True:
        try:
            start_t = time.monotonic()
            
            wifi_up = check_wifi(iface)
            
            ts = datetime.now().strftime('%H:%M:%S')
            
            hit_this_round = False
            details = []
            
            if wifi_up:
                for t in http_targets:
                    res = run_http(t["url"])
                    if not res["success"]:
                        details.append(f"{t['url']}=FAIL(rc={res['curl_rc']})")
                        if res["curl_rc"] not in (0, 6): # 6 is DNS fail, handled by S2
                            hit_this_round = True
                    else:
                        details.append(f"{t['url']}={res['status']}/{res['total_ms']:.1f}ms ttfb={res['ttfb_ms']:.1f}ms")
                        if res["status"] < 200 or res["status"] >= 400:
                            hit_this_round = True
                        elif res["total_ms"] >= total_threshold or res["ttfb_ms"] >= ttfb_threshold:
                            hit_this_round = True
                            
            if hit_this_round:
                consecutive_hits += 1
                consecutive_ok = 0
            else:
                consecutive_hits = 0
                consecutive_ok += 1
                
            status = f"wifi={'UP' if wifi_up else 'DOWN'} http=[{', '.join(details)}]"
            print(f"[{ts}] S5 Probe | {status} | hits={consecutive_hits}/{N}")
            
            if not is_active and consecutive_hits >= N:
                is_active = True
                print(f"    >>> [ALARM] S5 HTTP_SLOW ACTIVE! (Hits: {consecutive_hits})")
            elif is_active and consecutive_ok >= N:
                is_active = False
                print(f"    >>> [RECOVERY] S5 HTTP_SLOW RECOVERED! (OKs: {consecutive_ok})")
            
            elapsed = time.monotonic() - start_t
            time.sleep(max(0, interval - elapsed))
            
        except KeyboardInterrupt:
            print("\n[*] Stopped.")
            break

if __name__ == "__main__":
    main()
