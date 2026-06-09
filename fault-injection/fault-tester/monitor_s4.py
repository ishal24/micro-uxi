#!/usr/bin/env python3
import sys
import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'monitor_config.json')

def load_config():
    with open(CONFIG_PATH, 'r') as f:
        return json.load(f)

def main():
    config = load_config().get("S4_HIGH_RTT", {})
    confirm_consecutive = config.get("confirm_consecutive", 2)
    thresholds = config.get("T_rtt", {})
    
    consecutive_counts = {}

    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
            
        # Check supporting triggers
        wifi = data.get("wifi", {})
        wifi_up = wifi.get("wifi_up", False)
        
        if not wifi_up:
            consecutive_counts.clear()
            continue
            
        ping = data.get("ping", {})
        if not ping:
            continue
            
        target = ping.get("target")
        # In fast probe it's rtt_ms, in telemetry it's rtt_avg_ms
        rtt = ping.get("rtt_avg_ms")
        if rtt is None:
            rtt = ping.get("rtt_ms")
            
        if rtt is None or target not in thresholds:
            continue
            
        # For simplification, we don't implement the m_ping < S3 trigger here fully
        # as it would require S3 state. We'll just do the basic RTT check.
        if rtt >= thresholds[target]:
            consecutive_counts[target] = consecutive_counts.get(target, 0) + 1
            print(f"S4: {target} rtt={rtt}ms >= {thresholds[target]}ms (count={consecutive_counts[target]}/{confirm_consecutive})")
        else:
            if consecutive_counts.get(target, 0) > 0:
                print(f"S4: {target} rtt recovered ({rtt}ms). Resetting count.")
            consecutive_counts[target] = 0
            
        if consecutive_counts[target] >= confirm_consecutive:
            print(f"[ALERT] S4 HIGH_RTT detected for ping target: {target} (rtt={rtt}ms, count={consecutive_counts[target]})")

if __name__ == "__main__":
    main()
