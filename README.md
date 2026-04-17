# Micro-UXI Sensor

A lightweight, multi-rate network experience monitoring tool for the **Arduino Uno Q** (Debian-based, 2 GB RAM).

Runs **three independent probe threads** in parallel:

| Thread | Rate | Purpose | Fault scenarios |
|---|---|---|---|
| `fast_probe` | 1–2 Hz | Ping + DNS burst detection | S2, S3, S6 |
| `telemetry` | 30 s | Full Wi-Fi / ping / DNS / HTTP snapshot | S1, S4 |
| `throughput` | 5 min | Download bandwidth test | S5 |

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
python controller.py [--config FILE] [--mode MODE] [--duration DURATION] [--format FORMAT] [--verbose] [--no-fast]
```

| Argument | Default | Description |
|---|---|---|
| `--config` | `config.json` | Path to the configuration file |
| `--mode` | `loop` | `loop`, `once-telemetry`, `once-throughput`, or `once-fast` |
| `--duration` | `0` (indefinite) | How long to run (see duration formats below) |
| `--format` | from config | Output format: `jsonl`, `csv`, or `json` |
| `--verbose` | off | Print full JSON per sample instead of compact one-liners |
| `--no-fast` | off | Disable the fast probe thread (saves CPU on slower devices) |

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

# Run for 30 minutes, save as CSV
python controller.py --duration 30m --format csv

# Run indefinitely, print full JSON per sample
python controller.py --verbose

# Run without the fast probe thread (e.g. on a very slow device)
python controller.py --duration 1h --no-fast

# Run with a custom config file
python controller.py --config my_config.json

# Run for 2 hours, CSV output, custom config
python controller.py --duration 2h --format csv --config my_config.json


# --- ONE-SHOT modes (single measurement, no loop) ---

# Collect one telemetry sample and exit
python controller.py --mode once-telemetry

# Collect one throughput sample and exit
python controller.py --mode once-throughput

# Collect one fast probe sample and exit
python controller.py --mode once-fast

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

# Run fast probe standalone (10 samples, 1s interval)
python fast_probe.py --count 10 --interval 1

# Run fast probe standalone and pipe to a file
python fast_probe.py --count 100 --interval 2 > fast_out.jsonl
```

---

## Output files

All output is saved in the directory set by `output.output_dir` in `config.json` (default: `./out/`).

Files are named with a **session ID** (UTC timestamp at start), so multiple runs never overwrite each other:

```
out/
├── fast_20260413T063000Z.jsonl          ← 1–2 Hz burst detection samples
├── telemetry_20260413T063000Z.jsonl     ← 30s full telemetry samples
├── throughput_20260413T063000Z.jsonl    ← 5-min throughput samples
└── ...
```

For CSV format:
```
out/
├── fast_20260413T063000Z.csv
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
  "fast_probe": {
    "enabled": true,               // Set false to disable fast-path thread
    "interval_sec": 2,             // Seconds between fast samples (1 = 1 Hz)
    "ping_target": "8.8.8.8",      // Target for single-packet ICMP ping
    "ping_timeout_sec": 1,         // Ping timeout (keep at 1s)
    "dns_domains": ["google.com", "its.ac.id"],  // Domains to resolve at high rate
    "dns_timeout_sec": 2           // DNS resolution timeout
  },
  "scheduler": {
    "telemetry_interval_sec": 30,  // How often to collect full telemetry
    "throughput_interval_sec": 300 // How often to run a throughput test
  },
  "modules": {
    "wifi": true,       // Measure Wi-Fi link state (SSID, RSSI, bitrate)
    "network": true,    // Measure IP address, gateway, DNS resolvers
    "ping": true,       // Measure RTT and packet loss (5 packets)
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

### Tuning tips

| Goal | Setting to change |
|---|---|
| Faster burst detection | Decrease `fast_probe.interval_sec` to `1` |
| Save CPU on slow device | Increase `fast_probe.interval_sec` to `5`, or use `--no-fast` |
| Less storage usage | Increase `telemetry_interval_sec` (e.g. `60`) |
| Disable throughput tests | Set `modules.throughput` to `false` |
| Save to a different directory | Change `output.output_dir` |
| Use local throughput server | Change `throughput.routine.url` to `http://LAPTOP_IP:8080/testfile.bin` |

---

## Console output

```
==================================================================
  Micro-UXI Monitoring Controller  —  threaded multi-rate
==================================================================
  Fast probe  : every 2s  (ping + DNS — catches S2/S3/S6 bursts)
  Telemetry   : every 30s  (full snapshot — S1/S4)
  Throughput  : every 300s  (download — S5)
  Duration    : 3600s  (60.0 min)
  Fast probe prints only on anomaly. Telemetry every 30s.
==================================================================

# Fast probe is SILENT unless an anomaly is detected:
[FAST ⚠ #  456] 06:35:12  wifi=UP  ping=FAIL  dns=google.com=FAIL  its.ac.id=OK

# Telemetry prints every 30s and includes fast probe anomaly count:
[TEL #   1] 06:30:00  wifi=UP   rssi= -52dBm  rtt=  74.32ms  loss=  0.0%
[TEL #   2] 06:30:30  wifi=UP   rssi= -53dBm  rtt=  73.87ms  loss=  0.0%  [2 fast anomalies]
[THR #   1] 06:35:00  avg=  8.421Mbps  p95=  8.901Mbps  runs=3/3 [OK]
```

---

## Throughput test — recommended setup

Using `proof.ovh.net` introduces uncontrolled external variance.
For thesis experiments, **use a local HTTP server on your laptop** instead:

```bash
# On your laptop — create a 1 MB test file and serve it:
dd if=/dev/urandom of=testfile_1mb.bin bs=1M count=1
python3 -m http.server 8080

# Then update config.json:
# "url": "http://LAPTOP_IP:8080/testfile_1mb.bin"
# "expected_bytes": 1048576
# "max_time_sec": 60
```

Benefits over external server:
- No external variability — same network path every run
- Fault injection (`tc`, `iptables`) on your LAN directly affects this endpoint
- Works without internet
- Fully reproducible

For **S5 Bandwidth Throttling**, `iperf3` gives more accurate bandwidth measurement:
```bash
# Laptop: iperf3 -s
# Uno Q:  iperf3 -c LAPTOP_IP -t 10 --json
```

---

## Analysing results (on your laptop)

```python
import pandas as pd

# Fast probe — high-frequency, good for burst analysis
df_fast = pd.read_json("fast_20260413T063000Z.jsonl", lines=True)
df_fast["ts"] = pd.to_datetime(df_fast["ts"])
df_fast["ping_rtt"] = df_fast["ping"].apply(
    lambda x: x.get("rtt_ms") if isinstance(x, dict) else None)
print(df_fast[["ts", "ping_rtt", "connectivity_ok"]].describe())

# Telemetry — flat CSV, easiest for pandas
df_tel = pd.read_csv("telemetry_20260413T063000Z.csv")
print(df_tel[["collected_at_utc", "rtt_avg_ms", "loss_pct", "wifi_rssi_dbm"]].describe())
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
│   ├── fast_probe.py        ← 1–2 Hz burst sampler
│   ├── telemetry_probe.py   ← Full Wi-Fi / ping / DNS / HTTP measurements
│   └── throughput_probe.py  ← Download throughput measurements
├── database/                ← Output files from runs
└── install.sh               ← System dependency installer
```
