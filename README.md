# Micro-UXI Sensor

A lightweight network experience monitoring tool for the **Arduino Uno Q** (Debian-based, 2 GB RAM).  
Continuously measures Wi-Fi, ping, DNS, and HTTP metrics and writes results to JSONL, CSV, or JSON.

---

## Requirements

Run the installer once (requires `sudo`):

```bash
sudo bash install.sh
```

This installs system tools (`iw`, `ping`, `dig`, `curl`, `tc`) and sets up a Python virtual environment at `/opt/microuxi-venv` with `psutil` and `dnspython`.

Activate the virtual environment before running anything:

```bash
source /opt/microuxi-venv/bin/activate
```

---

## Quick Start

```bash
cd sensor/

# Run indefinitely (default — Ctrl+C to stop)
python controller.py

# Run for 15 minutes
python controller.py --duration 15m

# Run for 1 hour
python controller.py --duration 1h
```

---

## All Commands

### `controller.py` — Main entry point

```
python controller.py [--config FILE] [--mode MODE] [--duration DURATION] [--format FORMAT] [--verbose]
```

| Argument | Default | Description |
|---|---|---|
| `--config` | `config.json` | Path to the configuration file |
| `--mode` | `loop` | `loop`, `once-telemetry`, or `once-throughput` |
| `--duration` | `0` (indefinite) | How long to run (see duration formats below) |
| `--format` | from config | Output format: `jsonl`, `csv`, or `json` |
| `--verbose` | off | Print full JSON per sample instead of compact one-liners |

#### Duration formats

| Value | Meaning |
|---|---|
| `0` / `inf` / `indefinite` | Run forever until Ctrl+C |
| `900` | 900 seconds |
| `15m` | 15 minutes |
| `1h` | 1 hour |
| `30s` | 30 seconds |

#### Output formats

| Format | Description | Best for |
|---|---|---|
| `jsonl` | One JSON object per line, appended to one session file | **Continuous monitoring** (default) |
| `csv` | Flat rows, one per sample | Analysis in pandas / Excel |
| `json` | One `.json` file per sample | Debugging / small one-off runs |

---

### Usage examples

```bash
# --- LOOP mode ---

# Run indefinitely, default format (JSONL)
python controller.py

# Run for 15 minutes
python controller.py --duration 15m

# Run for 1 hour
python controller.py --duration 1h

# Run for 30 minutes, save as CSV (easy to open in Excel)
python controller.py --duration 30m --format csv

# Run indefinitely, print full JSON per sample
python controller.py --verbose

# Run with a custom config file
python controller.py --config my_config.json

# Run for 2 hours, CSV output, custom config
python controller.py --duration 2h --format csv --config my_config.json


# --- ONE-SHOT modes (single measurement, no loop) ---

# Collect one telemetry sample and exit
python controller.py --mode once-telemetry

# Collect one throughput sample and exit
python controller.py --mode once-throughput

# One-shot with full JSON printed to console
python controller.py --mode once-telemetry --verbose


# --- Run probes directly (standalone) ---

# Run telemetry probe standalone
python telemetry_probe.py

# Run telemetry probe and save output to a file
python telemetry_probe.py --save-json result_telemetry.json

# Run throughput probe standalone
python throughput_probe.py

# Run throughput probe and save output to a file
python throughput_probe.py --save-json result_throughput.json
```

---

## Output files

All output is saved in the directory set by `output.output_dir` in `config.json` (default: `./out/`).

Files are named with a **session ID** (UTC timestamp at start), so multiple runs never overwrite each other:

```
out/
├── telemetry_20260413T063000Z.jsonl    ← all telemetry samples from one run
├── throughput_20260413T063000Z.jsonl   ← all throughput samples from one run
└── ...
```

For CSV format:
```
out/
├── telemetry_20260413T063000Z.csv
├── throughput_20260413T063000Z.csv
└── ...
```

---

## Configuration (`config.json`)

```json
{
  "device": {
    "device_id": "uno-q-01",       // Unique name for this sensor node
    "site_name": "ITS",            // Location label
    "iface": "wlan0"               // Wi-Fi interface to monitor
  },
  "scheduler": {
    "telemetry_interval_sec": 30,  // How often to collect telemetry
    "throughput_interval_sec": 300 // How often to run a throughput test
  },
  "modules": {
    "wifi": true,       // Measure Wi-Fi link state (SSID, RSSI, bitrate)
    "network": true,    // Measure IP address, gateway, DNS resolvers
    "ping": true,       // Measure RTT and packet loss
    "dns": true,        // Measure DNS resolution latency per domain
    "http": true,       // Measure HTTP timing (TTFB, total, TLS)
    "throughput": true  // Run download throughput tests
  },
  "output": {
    "output_dir": "./out",    // Where to save output files
    "format": "jsonl",        // Default format: jsonl | csv | json
    "print_pretty": false     // true = full JSON on console, false = compact lines
  }
}
```

### Tuning tips for extended runs

| Goal | Setting to change |
|---|---|
| Less storage usage | Increase `telemetry_interval_sec` (e.g. `60`) |
| Detect short bursts | Decrease `telemetry_interval_sec` (e.g. `5`) |
| Disable throughput tests | Set `modules.throughput` to `false` |
| Save to a different directory | Change `output.output_dir` |

---

## Console output (compact mode)

While running, each sample prints a one-liner:

```
==============================================================
  Micro-UXI Monitoring Controller
==============================================================
  Device      : uno-q-01  @  ITS
  Interface   : wlan0
  Telemetry   : every 30s
  Throughput  : every 300s
  Duration    : 3600s  (60.0 min)
  Format      : JSONL
  Output dir  : /home/user/sensor/out
  Session ID  : 20260413T063000Z
==============================================================
[TEL #   1] 2026-04-13T06:30:00+00:00  wifi=UP    rssi= -52 dBm  rtt=  14.32 ms  loss=  0.0%
[TEL #   2] 2026-04-13T06:30:30+00:00  wifi=UP    rssi= -53 dBm  rtt=  13.87 ms  loss=  0.0%
[THR #   1] 2026-04-13T06:35:00+00:00  avg=  8.421 Mbps  p95=  8.901 Mbps  success=2/2
...
==============================================================
  Session complete.
  Elapsed     : 3600.2s  (60.0 min)
  Telemetry   : 120 collected
  Throughput  : 12 collected
  Output      : /home/user/sensor/out
==============================================================
```

---

## Analysing results (on your laptop)

After copying the output files from the Uno Q:

```python
import pandas as pd

# Load JSONL telemetry
df = pd.read_json("telemetry_20260413T063000Z.jsonl", lines=True)
print(df[["collected_at_utc", "telemetry"]].head())

# Load CSV telemetry (already flat, no extra parsing needed)
df = pd.read_csv("telemetry_20260413T063000Z.csv")
print(df[["collected_at_utc", "rtt_avg_ms", "loss_pct", "wifi_rssi_dbm"]].describe())
```

---

## File structure

```
micro-uxi/
├── docs/
│   ├── Proposal-TA-DTI.docx (1).pdf   ← Thesis proposal
│   └── Fault Injection Scheme (3).xlsx ← Fault injection design
├── sensor/
│   ├── config.json          ← Main configuration
│   ├── controller.py        ← Entry point — run this
│   ├── telemetry_probe.py   ← Wi-Fi, ping, DNS, HTTP measurements
│   └── throughput_probe.py  ← Download throughput measurements
├── database/                ← (planned) server-side storage
└── install.sh               ← System dependency installer
```
