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
    config = load_config().get("S6_CONNECTIVITY_FLAP", {})
    w_flap_sec = config.get("W_flap_sec", 30)
    m_transition = config.get("m_transition", 4)
    n_flap = config.get("n_flap", 15)
    
    # Store tuple (timestamp, connectivity_ok)
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
        
        # Check primary state
        wifi = data.get("wifi", {})
        wifi_up = wifi.get("wifi_up", False)
        ping = data.get("ping", {})
        ping_success = ping.get("success", False)
        
        # We can use the 'connectivity_ok' flag if present, else calculate
        connectivity_ok = data.get("connectivity_ok", wifi_up and ping_success)
        
        window.append((ts, connectivity_ok))
        
        cutoff = ts - timedelta(seconds=w_flap_sec)
        while window and window[0][0] < cutoff:
            window.popleft()
            
        if len(window) >= n_flap:
            transitions = 0
            for i in range(1, len(window)):
                if window[i][1] != window[i-1][1]:
                    transitions += 1
                    
            print(f"S6: window={len(window)}/{n_flap}, transitions={transitions}/{m_transition} required")
            if transitions >= m_transition:
                print(f"[ALERT] S6 CONNECTIVITY_FLAP detected (transitions={transitions}/{len(window)} in {w_flap_sec}s)")

if __name__ == "__main__":
    main()
