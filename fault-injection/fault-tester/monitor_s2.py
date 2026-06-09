#!/usr/bin/env python3
import sys
import json
import os
import dateutil.parser
from collections import deque
from datetime import timedelta

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'monitor_config.json')

def load_config():
    with open(CONFIG_PATH, 'r') as f:
        return json.load(f)

def main():
    config = load_config().get("S2_DNS_TIMEOUT_BURST", {})
    n_dns = config.get("n_dns", 10)
    m_dns = config.get("m_dns", 3)
    w_dns_sec = config.get("W_dns_sec", 20)
    
    # Store deque of (timestamp, is_fail) per target
    windows = {}

    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
            
        ts_str = data.get("ts")
        if not ts_str:
            continue
        ts = dateutil.parser.isoparse(ts_str)
        
        # Check supporting triggers
        wifi = data.get("wifi", {})
        wifi_up = wifi.get("wifi_up", False)
        ping = data.get("ping", {})
        ping_success = ping.get("success", False)
        
        if not wifi_up or not ping_success:
            windows.clear()
            continue
            
        dns_list = data.get("dns", [])
        for dns_entry in dns_list:
            target = dns_entry.get("target")
            success = dns_entry.get("success", False)
            is_fail = not success
            
            if target not in windows:
                windows[target] = deque()
            
            # Add current sample
            windows[target].append((ts, is_fail))
            
            # Remove old samples outside window
            cutoff = ts - timedelta(seconds=w_dns_sec)
            while windows[target] and windows[target][0][0] < cutoff:
                windows[target].popleft()
                
            # Check conditions
            if len(windows[target]) >= n_dns:
                fail_count = sum(1 for item in windows[target] if item[1])
                print(f"S2: {target} window={len(windows[target])}/{n_dns}, fails={fail_count}/{m_dns} required")
                if fail_count >= m_dns:
                    print(f"[ALERT] S2 DNS_TIMEOUT_BURST detected for target: {target} (fails={fail_count}/{len(windows[target])} in {w_dns_sec}s)")

if __name__ == "__main__":
    main()
