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
    n_flap = cfg["rules"]["S6_CONNECTIVITY_FLAP"]["n_flap"]
    m_transition = cfg["rules"]["S6_CONNECTIVITY_FLAP"]["m_transition"]
    
    ping_target = cfg["targets"]["ping_target"]
    iface = cfg["targets"]["iface"]

    print(f"[*] Starting S6 (CONNECTIVITY_FLAP) Monitor")
    print(f"[*] Interval: {interval}s, m-of-n: {m_transition} transitions in {n_flap} samples")

    history = deque(maxlen=n_flap)

    while True:
        try:
            start_t = time.monotonic()
            
            wifi_up = check_wifi(iface)
            ping_ok = run_ping(ping_target)
            connectivity_ok = wifi_up and ping_ok
            
            ts = datetime.now().strftime('%H:%M:%S')
            
            history.append(connectivity_ok)
            window_size = len(history)
            
            transitions = 0
            if window_size > 1:
                hist_list = list(history)
                for left, right in zip(hist_list, hist_list[1:]):
                    if left != right:
                        transitions += 1
            
            status = f"wifi={'UP' if wifi_up else 'DOWN'} ping={'OK' if ping_ok else 'FAIL'}"
            print(f"[{ts}] S6 Probe | {status} | conn_ok={connectivity_ok} | window={window_size} transitions={transitions}")
            
            if window_size == n_flap and transitions >= m_transition:
                print(f"    >>> [ALARM] S6 CONNECTIVITY_FLAP ACTIVE! (Transitions: {transitions}/{m_transition})")
            
            elapsed = time.monotonic() - start_t
            time.sleep(max(0, interval - elapsed))
            
        except KeyboardInterrupt:
            print("\n[*] Stopped.")
            break

if __name__ == "__main__":
    main()
