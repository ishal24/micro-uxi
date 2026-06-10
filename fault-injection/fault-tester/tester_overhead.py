#!/usr/bin/env python3
import argparse
import json
import time
from datetime import datetime
from pathlib import Path

try:
    import psutil
except ImportError:
    psutil = None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", default="overhead_log.jsonl")
    parser.add_argument("--interval", type=float, default=2.0)
    args = parser.parse_args()

    if not psutil:
        return

    out_path = Path(args.output)
    
    # Panggilan pertama agar kalkulasi interval CPU psutil presisi
    psutil.cpu_percent(interval=None)
    
    last_net_tx = 0
    last_net_rx = 0
    last_net_ts = time.monotonic()
    
    try:
        net = psutil.net_io_counters()
        if net:
            last_net_tx = net.bytes_sent
            last_net_rx = net.bytes_recv
    except Exception:
        pass

    try:
        while True:
            time.sleep(args.interval)
            
            mono = time.monotonic()
            mem = psutil.virtual_memory()
            
            disk_pct = 0.0
            disk_used_mb = 0.0
            try:
                du = psutil.disk_usage('/')
                disk_pct = round(du.percent, 2)
                disk_used_mb = round(du.used / 1024 / 1024, 2)
            except Exception:
                pass
                
            net_tx_kbs = 0.0
            net_rx_kbs = 0.0
            try:
                net = psutil.net_io_counters()
                if net:
                    dt_net = max(mono - last_net_ts, 0.001)
                    net_tx_kbs = round((net.bytes_sent - last_net_tx) / 1024 / dt_net, 2)
                    net_rx_kbs = round((net.bytes_recv - last_net_rx) / 1024 / dt_net, 2)
                    last_net_tx = net.bytes_sent
                    last_net_rx = net.bytes_recv
                    last_net_ts = mono
            except Exception:
                pass

            record = {
                "run_id": args.run_id,
                "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
                "cpu_pct": round(psutil.cpu_percent(interval=None), 2),
                "mem_used_mb": round(mem.used / 1024 / 1024, 2),
                "mem_pct": round(mem.percent, 2),
                "disk_pct": disk_pct,
                "disk_used_mb": disk_used_mb,
                "net_tx_kbs": max(net_tx_kbs, 0.0),
                "net_rx_kbs": max(net_rx_kbs, 0.0),
            }
            with out_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()