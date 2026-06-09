#!/usr/bin/env python3
import sys
import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'monitor_config.json')

def load_config():
    with open(CONFIG_PATH, 'r') as f:
        return json.load(f)

def main():
    config = load_config().get("S5_HTTP_SLOW", {})
    confirm_consecutive = config.get("confirm_consecutive", 2)
    t_http_total = config.get("T_http_total", {})
    t_http_ttfb = config.get("T_http_ttfb", {})
    expected_status = config.get("EXPECTED_HTTP_STATUS", {})
    
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
            
        http_list = data.get("http", [])
        for http_entry in http_list:
            url = http_entry.get("url")
            if url not in t_http_total:
                continue
                
            total_ms = http_entry.get("http_total_ms", 0)
            ttfb_ms = http_entry.get("http_ttfb_ms", 0)
            curl_rc = http_entry.get("curl_rc", 0)
            status = http_entry.get("http_status", 0)
            
            is_slow = False
            
            # Primary Trigger conditions
            if total_ms >= t_http_total.get(url, 99999):
                is_slow = True
            elif ttfb_ms >= t_http_ttfb.get(url, 99999):
                is_slow = True
            elif curl_rc != 0 and curl_rc != 6:
                is_slow = True
            elif status not in expected_status.get(url, []):
                is_slow = True
                
            if is_slow:
                consecutive_counts[url] = consecutive_counts.get(url, 0) + 1
                print(f"S5: {url} HTTP slow trigger matched (count={consecutive_counts[url]}/{confirm_consecutive})")
            else:
                if consecutive_counts.get(url, 0) > 0:
                    print(f"S5: {url} HTTP speed recovered. Resetting count.")
                consecutive_counts[url] = 0
                
            if consecutive_counts[url] >= confirm_consecutive:
                print(f"[ALERT] S5 HTTP_SLOW detected for url: {url} (count={consecutive_counts[url]})")

if __name__ == "__main__":
    main()
