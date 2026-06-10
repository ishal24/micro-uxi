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

def run_dns(target, resolver):
    try:
        res = subprocess.run(["dig", f"@{resolver}", "+short", "+time=2", target], capture_output=True, text=True)
        return res.returncode == 0 and bool(res.stdout.strip())
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
    n_dns = cfg["rules"]["S2_DNS_TIMEOUT_BURST"]["n_dns"]
    m_dns = cfg["rules"]["S2_DNS_TIMEOUT_BURST"]["m_dns"]
    
    ping_target = cfg["targets"]["ping_target"]
    dns_targets = cfg["targets"]["dns_targets"]
    resolver = cfg["targets"]["dns_resolver"]
    iface = cfg["targets"]["iface"]

    print(f"[*] Starting S2 (DNS_TIMEOUT_BURST) Monitor")
    print(f"[*] Interval: {interval}s, m-of-n: {m_dns}-of-{n_dns}")

    history = deque(maxlen=n_dns)
    is_active = False

    while True:
        try:
            start_t = time.monotonic()
            
            wifi_up = check_wifi(iface)
            ping_ok = run_ping(ping_target)
            
            dns_all_ok = True
            details = []
            
            for t in dns_targets:
                ok = run_dns(t["name"], resolver)
                details.append(f"{t['name']}={'OK' if ok else 'FAIL'}")
                if not ok:
                    dns_all_ok = False
            
            ts = datetime.now().strftime('%H:%M:%S')
            
            # Hanya catat failure jika layer dasar (wifi & ping) hidup
            if wifi_up and ping_ok:
                history.append(dns_all_ok)
            
            fail_count = sum(1 for ok in history if not ok)
            window_size = len(history)
            
            status = f"wifi={'UP' if wifi_up else 'DOWN'} ping={'OK' if ping_ok else 'FAIL'} dns=[{', '.join(details)}]"
            print(f"[{ts}] S2 Probe | {status} | window={window_size} fails={fail_count}")
            
            if window_size == n_dns:
                if not is_active and fail_count >= m_dns:
                    is_active = True
                    print(f"    >>> [ALARM] S2 DNS_TIMEOUT_BURST ACTIVE! (Fails: {fail_count}/{n_dns})")
                elif is_active and fail_count == 0:
                    is_active = False
                    print(f"    >>> [RECOVERY] S2 DNS_TIMEOUT_BURST RECOVERED! (Clean window)")
            
            elapsed = time.monotonic() - start_t
            time.sleep(max(0, interval - elapsed))
            
        except KeyboardInterrupt:
            print("\n[*] Stopped.")
            break

if __name__ == "__main__":
    main()
