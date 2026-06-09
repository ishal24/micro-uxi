#!/usr/bin/env python3
import sys
import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'monitor_config.json')

def load_config():
    with open(CONFIG_PATH, 'r') as f:
        return json.load(f)

def main():
    config = load_config().get("S1_DNS_DEGRADED", {})
    confirm_consecutive = config.get("confirm_consecutive", 2)
    thresholds = config.get("T_dns_latency", {})
    
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
        ping = data.get("ping", {})
        ping_success = ping.get("success", False)
        
        # if wifi is down or ping is failing, this is not just DNS degraded
        if not wifi_up or not ping_success:
            consecutive_counts.clear()
            continue
        
        dns_list = data.get("dns", [])
        for dns_entry in dns_list:
            target = dns_entry.get("target")
            success = dns_entry.get("success", False)
            latency = dns_entry.get("latency_ms", 0)
            
            if target not in thresholds:
                continue
                
            if success and latency >= thresholds[target]:
                consecutive_counts[target] = consecutive_counts.get(target, 0) + 1
                print(f"S1: {target} latency={latency}ms >= {thresholds[target]}ms (count={consecutive_counts[target]}/{confirm_consecutive})")
            else:
                if consecutive_counts.get(target, 0) > 0:
                    print(f"S1: {target} latency recovered ({latency}ms). Resetting count.")
                consecutive_counts[target] = 0
                
            if consecutive_counts[target] >= confirm_consecutive:
                print(f"[ALERT] S1 DNS_DEGRADED detected for target: {target} (latency={latency}ms, count={consecutive_counts[target]})")

if __name__ == "__main__":
    main()
