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
    
    try:
        while True:
            time.sleep(args.interval)
            mem = psutil.virtual_memory()
            record = {
                "run_id": args.run_id,
                "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
                "cpu_pct": round(psutil.cpu_percent(interval=None), 2),
                "mem_used_mb": round(mem.used / 1024 / 1024, 2),
                "mem_pct": round(mem.percent, 2),
            }
            with out_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()