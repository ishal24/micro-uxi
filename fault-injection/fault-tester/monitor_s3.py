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
    config = load_config().get("S3_LOSS_BURST", {})
    n_ping = config.get("n_ping", 20)
    m_ping = config.get("m_ping", 4)
    w_ping_sec = config.get("W_ping_sec", 40)
    
    # window holds tuple (timestamp, ping_is_fail, wifi_is_up)
    window = deque()

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
        
        wifi = data.get("wifi", {})
        wifi_up = wifi.get("wifi_up", False)
        
        ping = data.get("ping", {})
        if not ping:
            continue
            
        target = ping.get("target")
        success = ping.get("success", False)
        is_fail = not success
        
        window.append((ts, is_fail, wifi_up))
        
        cutoff = ts - timedelta(seconds=w_ping_sec)
        while window and window[0][0] < cutoff:
            window.popleft()
            
        if len(window) >= n_ping:
            # Check supporting trigger: wifi_up == true and all wifi_up in window
            if not wifi_up:
                continue
            all_wifi_up = all(item[2] for item in window)
            if not all_wifi_up:
                continue
                
            fail_count = sum(1 for item in window if item[1])
            print(f"S3: {target} window={len(window)}/{n_ping}, fails={fail_count}/{m_ping} required")
            if fail_count >= m_ping:
                print(f"[ALERT] S3 LOSS_BURST detected for ping target: {target} (fails={fail_count}/{len(window)} in {w_ping_sec}s)")

if __name__ == "__main__":
    main()
