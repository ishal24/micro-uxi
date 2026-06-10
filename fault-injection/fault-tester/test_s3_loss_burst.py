import json
import time
import subprocess
from datetime import datetime
from collections import deque

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

def check_wifi(iface):
    try:
        with open(f"/sys/class/net/{iface}/operstate") as f:
            return f.read().strip() == "up"
    except Exception:
        return True

def main():
    cfg = load_config()
    interval = cfg["scheduler"]["fast_interval_sec"]
    n_ping = cfg["rules"]["S3_LOSS_BURST"]["n_ping"]
    m_ping = cfg["rules"]["S3_LOSS_BURST"]["m_ping"]
    
    ping_target = cfg["targets"]["ping_target"]
    iface = cfg["targets"]["iface"]

    print(f"[*] Starting S3 (LOSS_BURST) Monitor")
    print(f"[*] Interval: {interval}s, m-of-n: {m_ping}-of-{n_ping}")

    history = deque(maxlen=n_ping)
    is_active = False

    while True:
        try:
            start_t = time.monotonic()
            
            wifi_up = check_wifi(iface)
            ping_ok = run_ping(ping_target)
            
            ts = datetime.now().strftime('%H:%M:%S')
            
            if wifi_up:
                history.append(ping_ok)
            
            fail_count = sum(1 for ok in history if not ok)
            window_size = len(history)
            loss_pct = (fail_count / window_size * 100) if window_size > 0 else 0
            
            status = f"wifi={'UP' if wifi_up else 'DOWN'} ping={'OK' if ping_ok else 'FAIL'}"
            print(f"[{ts}] S3 Probe | {status} | window={window_size} fails={fail_count} ({loss_pct:.1f}%)")
            
            if window_size == n_ping:
                if not is_active and fail_count >= m_ping:
                    is_active = True
                    print(f"    >>> [ALARM] S3 LOSS_BURST ACTIVE! (Fails: {fail_count}/{n_ping})")
                elif is_active and fail_count == 0:
                    is_active = False
                    print(f"    >>> [RECOVERY] S3 LOSS_BURST RECOVERED! (Clean window)")
            
            elapsed = time.monotonic() - start_t
            time.sleep(max(0, interval - elapsed))
            
        except KeyboardInterrupt:
            print("\n[*] Stopped.")
            break

if __name__ == "__main__":
    main()
