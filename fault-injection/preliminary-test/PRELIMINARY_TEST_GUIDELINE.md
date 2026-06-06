# Preliminary Test Guideline untuk Micro-UXI

**Tanggal**: May 2026  
**Target Device**: Arduino UNO Q  
**Tujuan**: Mengkalibrasikan threshold dan parameter trigger untuk 6 event (S1–S6)

---

## 1. Overview

Preliminary test adalah pengujian kondisi jaringan **normal** tanpa fault injection. Data dari test ini digunakan untuk:

1. **Menentukan threshold statis** (T_dns_latency, T_rtt, T_http_total, dst) menggunakan P99
2. **Menentukan parameter trigger** (N_dns, m_dns, n_dns, m_ping, dst) melalui pengujian kandidat
3. **Baseline untuk evaluasi metode baseline vs event-driven**

---

## 2. Sampling Strategy & Durasi

### 2.1 Probe Schedule

| Probe | Interval | Target Sample Count | Durasi Minimal | Durasi Target |
|-------|----------|---------------------|---|---|
| **Fast** | 5 detik | 1.000–10.000 | 1.4 jam (1k) | 14 jam (10k) |
| **Telemetry** | 30 detik | 1.000–10.000 | 8.3 jam (1k) | 3.5 hari (10k) |

**Rekomendasi untuk preliminary test ini:**
- **Fast Probe**: 2.000 sampel minimum (2.000 × 5s = 10.000s ≈ 2.8 jam)
- **Telemetry Probe**: 1.000 sampel minimum (1.000 × 30s = 30.000s ≈ 8.3 jam)

**Alasan**:
- Fast probe diperlukan untuk S1, S4, S5 yang butuh confirm_consecutive
- Telemetry probe diperlukan untuk S2, S3, S6 yang butuh sliding window
- Durasi berbeda: fast probe dapat selesai lebih cepat, telemetry probe berjalan lebih lama

**Praktis**: Jalankan kedua probe **secara paralel** selama minimal 8.3 jam.

### 2.2 Kondisi Jaringan Normal

Pastikan selama preliminary test:

✅ **Wi-Fi stable** — tidak ada intermittent disconnect, interference minimal  
✅ **Internet connectivity stable** — upstream ISP tidak ada gangguan  
✅ **No other heavy traffic** — hanya UNO Q dan laptop monitor yang traffic  
✅ **Consistent location** — test di satu tempat saja (lab/kampus), jangan pindah-pindah  
✅ **Time of day** — pilih waktu dengan traffic normal (bukan peak hour)  

---

## 3. Pre-Test Checklist

### 3.1 Hardware & Network Setup

- [ ] Arduino UNO Q sudah di-setup dengan:
  - Access point (HOTSPOT_IF): **ap0** (verify: `ip link show ap0`)
  - Upstream interface (UPSTREAM_IF): **wlxd037456b1bc8** (verify: `ip link show wlxd037456b1bc8`)
  - Client laptop connected ke ap0
  - Laptop dapat reach 8.8.8.8 dan www.google.com

- [ ] Verifikasi interface nama:
```bash
# Di UNO Q, jalankan:
ip link show
# Catat nama interface untuk hotspot (ap0?) dan upstream (wlx...?)
# Update di fault_common.sh jika berbeda
```

### 3.2 Software Prerequisites

- [ ] Monitoring modules tersedia: `monitoring/` folder lengkap
- [ ] Config file: `monitoring/default_config.json` sudah sesuai (lihat §3.3)
- [ ] Python dependencies terinstall:
```bash
pip install -r monitoring/requirements.txt  # jika ada, atau manual install
```

### 3.3 Config Adjustment untuk Preliminary Test

**File**: `monitoring/default_config.json`

Lakukan berikut sebelum menjalankan test:

```json
{
  "device": {
    "device_id": "uno-q-01",
    "iface": "ap0"  // verifikasi ini adalah hotspot interface
  },
  "scheduler": {
    "fast_interval_sec": 5,
    "telemetry_interval_sec": 30,
    "throughput_interval_sec": 900
  },
  "fast_probe": {
    "enabled": true,
    "ping_target": "8.8.8.8",
    "targets": [
      {"name": "its.ac.id", "scope": "internal"},
      {"name": "google.com", "scope": "external"}
    ]
  },
  "telemetry_probe": {
    "enabled": true,
    "dns_targets": [
      {"name": "its.ac.id", "scope": "internal"},
      {"name": "google.com", "scope": "external"},
      {"name": "youtube.com", "scope": "external"}
    ],
    "http_targets": [
      {"url": "https://www.its.ac.id", "scope": "internal", ...}
    ]
  },
  "output": {
    "enabled": true,
    "output_dir": "./monitoring/out"
  },
  "detector": {
    "detection_mode": "static"  // untuk preliminary test gunakan static
  }
}
```

**⚠️ Important**: Ganti hardcoded threshold `thresholds` dengan placeholder saat preliminary test:

```json
"thresholds": {
  "dns_latency_threshold_ms": null,      // akan di-set dari P99
  "rtt_threshold_ms": null,              // akan di-set dari P99
  "http_total_threshold_ms": null,       // akan di-set dari P99
  "http_ttfb_threshold_ms": null,        // akan di-set dari P99
  ...
}
```

atau gunakan nilai temporary tinggi agar detector tidak trigger:

```json
"thresholds": {
  "dns_latency_threshold_ms": 99999,
  "rtt_threshold_ms": 99999,
  "http_total_threshold_ms": 99999,
  ...
}
```

---

## 4. Running Preliminary Test

### 4.1 Step 1: Prepare Environment

```bash
# Di UNO Q, pastikan interfaces up
sudo ip link set ap0 up
sudo ip link set wlxd037456b1bc8 up

# Cek IP addresses
ip addr show ap0
ip addr show wlxd037456b1bc8

# Test connectivity dari client ke upstream
ping -c 5 8.8.8.8
dig its.ac.id
```

### 4.2 Step 2: Start Monitoring

Di client (laptop yang connect ke ap0):

```bash
cd /path/to/micro-uxi

# Run monitoring controller
python -m monitoring.controller \
  --config monitoring/default_config.json \
  --mode monitor \
  --duration 8h \
  --output-dir ./monitoring/out/preliminary_test_run1

# Note: 
# - duration: sesuaikan dengan target durasi (8h = 8.3 jam untuk 1k telemetry sample)
# - output-dir: data akan disimpan ke JSONL files
```

**Expected output**:
- Fast probe samples: `./monitoring/out/preliminary_test_run1/samples/fast_run-*.jsonl`
- Telemetry samples: `./monitoring/out/preliminary_test_run1/samples/telemetry_run-*.jsonl`
- Console output: sample counts printed setiap 1-2 menit

### 4.3 Step 3: Monitor Progress

Di terminal terpisah:

```bash
# Watch sample count growth
while true; do
  fast_count=$(wc -l < ./monitoring/out/preliminary_test_run1/samples/fast_*.jsonl 2>/dev/null || echo 0)
  telem_count=$(wc -l < ./monitoring/out/preliminary_test_run1/samples/telemetry_*.jsonl 2>/dev/null || echo 0)
  echo "Fast: $fast_count | Telemetry: $telem_count"
  sleep 60
done
```

**Target**:
- Fast: 2.000+ sampel (≈ 2.8 jam)
- Telemetry: 1.000+ sampel (≈ 8.3 jam)

---

## 5. Post-Test: Threshold Calculation

### 5.0 Critical Concept: Per-Target Thresholds

**⚠️ FOUNDATION**: Semua threshold HARUS dihitung **per-target**, bukan di-average:

**Why**:
- its.ac.id (internal) mungkin lebih cepat (P99 = 25ms)
- google.com (external) mungkin lebih lambat (P99 = 100ms)
- Jika di-average menjadi 62.5ms:
  - Terlalu tinggi untuk detect S1 pada its.ac.id (miss detection)
  - Terlalu rendah untuk external, banyak false alarm

**Trigger Logic** (from S1 specification):
```
affected_scope = internal     jika hanya its.ac.id trigger
affected_scope = external     jika hanya google.com trigger
affected_scope = all          jika keduanya trigger
```

**Implementation**:
```python
# WRONG (averaged)
if dns_latency_avg >= 62.5:
    trigger()

# CORRECT (per-target)
triggered_targets = []
for target in ["its.ac.id", "google.com"]:
    if dns_latency[target] >= threshold[target]:
        triggered_targets.append(target)

if triggered_targets:
    affected_scope = determine_scope(triggered_targets)
    trigger(affected_scope=affected_scope)
```

### 5.1 Extract Data

Setelah preliminary test selesai, load data dari JSONL dan segregate PER-TARGET:

```python
import json
from pathlib import Path
from statistics import quantiles

# Load fast probe samples
fast_samples = []
with open("./monitoring/out/preliminary_test_run1/samples/fast_run-*.jsonl") as f:
    for line in f:
        fast_samples.append(json.loads(line))

# Load telemetry samples
telem_samples = []
with open("./monitoring/out/preliminary_test_run1/samples/telemetry_run-*.jsonl") as f:
    for line in f:
        telem_samples.append(json.loads(line))

print(f"Fast samples: {len(fast_samples)}")
print(f"Telemetry samples: {len(telem_samples)}")

# ⚠️ IMPORTANT: All thresholds MUST be per-target (not averaged)
# This will be reflected in sections 5.2.1, 5.2.3 below
```

### 5.2 Threshold Calculation (P99)

#### 5.2.1 DNS Latency Threshold (S1) — Per-Target

**⚠️ IMPORTANT**: Threshold MUST be per-target (its.ac.id, google.com), not averaged!

```python
from statistics import quantiles

# Extract successful DNS latencies PER-TARGET
dns_latencies_by_target = {}

for sample in fast_samples:
    for dns_entry in sample.get("dns", []):
        if dns_entry["success"]:
            target_name = dns_entry["name"]  # "its.ac.id" or "google.com"
            if target_name not in dns_latencies_by_target:
                dns_latencies_by_target[target_name] = []
            dns_latencies_by_target[target_name].append(dns_entry["latency_ms"])

# Calculate P99 PER-TARGET
thresholds_dns = {}
for target, latencies in dns_latencies_by_target.items():
    if len(latencies) >= 1000:
        p99 = quantiles(latencies, n=100)[98]
        thresholds_dns[target] = p99
        print(f"T_dns_latency({target}): {p99}ms (from {len(latencies)} samples)")
    else:
        print(f"WARNING: {target} has only {len(latencies)} samples, need >= 1000")

# Example result:
# T_dns_latency(its.ac.id): 25ms
# T_dns_latency(google.com): 100ms

# Store in config as dict:
thresholds["dns_latency_threshold_ms"] = thresholds_dns
```

#### 5.2.2 RTT Threshold (S4) — Single Target

**Note**: RTT has single target (8.8.8.8), so one threshold only.

```python
# Extract RTT from fast probe ping
rtt_values = []
for sample in fast_samples:
    ping = sample.get("ping", {})
    if ping.get("success"):
        rtt_values.append(ping["rtt_ms"])

if len(rtt_values) >= 1000:
    p99_rtt = quantiles(rtt_values, n=100)[98]
    print(f"T_rtt(8.8.8.8): {p99_rtt}ms (from {len(rtt_values)} samples)")
    thresholds["rtt_threshold_ms"] = p99_rtt
else:
    print(f"WARNING: RTT has only {len(rtt_values)} samples, need >= 1000")
```

#### 5.2.3 HTTP Total & TTFB Threshold (S5) — Per-URL

**Note**: HTTP has single URL in config (https://www.its.ac.id), but structure supports per-URL.

```python
# Extract HTTP timings from telemetry samples PER-URL
http_timings_by_url = {}

for sample in telem_samples:
    for http_entry in sample.get("http", []):
        if http_entry["success"]:
            url = http_entry["url"]
            if url not in http_timings_by_url:
                http_timings_by_url[url] = {"total": [], "ttfb": []}
            http_timings_by_url[url]["total"].append(http_entry["total_ms"])
            http_timings_by_url[url]["ttfb"].append(http_entry["ttfb_ms"])

# Calculate P99 PER-URL
thresholds_http_total = {}
thresholds_http_ttfb = {}

for url, timings in http_timings_by_url.items():
    total_samples = len(timings["total"])
    ttfb_samples = len(timings["ttfb"])
    
    if total_samples >= 500:  # HTTP might have fewer samples than DNS/RTT
        p99_total = quantiles(timings["total"], n=100)[98]
        thresholds_http_total[url] = p99_total
        print(f"T_http_total({url}): {p99_total}ms (from {total_samples} samples)")
    else:
        print(f"WARNING: {url} HTTP total has only {total_samples} samples, need >= 500")
    
    if ttfb_samples >= 500:
        p99_ttfb = quantiles(timings["ttfb"], n=100)[98]
        thresholds_http_ttfb[url] = p99_ttfb
        print(f"T_http_ttfb({url}): {p99_ttfb}ms (from {ttfb_samples} samples)")
    else:
        print(f"WARNING: {url} HTTP TTFB has only {ttfb_samples} samples, need >= 500")

thresholds["http_total_threshold_ms"] = thresholds_http_total
thresholds["http_ttfb_threshold_ms"] = thresholds_http_ttfb
```

### 5.3 Loss & Flap Baseline

#### 5.3.1 DNS Timeout Ratio (S2)

```python
# Calculate DNS failure ratio in telemetry windows
dns_failure_ratios = []
for sample in telem_samples:
    dns_entries = sample.get("dns", [])
    failures = sum(1 for d in dns_entries if not d["success"])
    total = len(dns_entries)
    if total > 0:
        dns_failure_ratios.append(failures / total)

# Expected value in normal condition
avg_dns_failure = sum(dns_failure_ratios) / len(dns_failure_ratios)
max_dns_failure = max(dns_failure_ratios)

print(f"Avg DNS failure ratio: {avg_dns_failure:.2%}")
print(f"Max DNS failure ratio: {max_dns_failure:.2%}")

# This helps determine baseline for m_dns parameter
```

#### 5.3.2 Packet Loss Ratio (S3)

```python
# From telemetry ping batch
ping_loss_ratios = []
for sample in telem_samples:
    ping = sample.get("ping", {})
    if ping.get("total_sent") > 0:
        loss_ratio = ping.get("lost", 0) / ping.get("total_sent", 1)
        ping_loss_ratios.append(loss_ratio)

avg_loss = sum(ping_loss_ratios) / len(ping_loss_ratios)
max_loss = max(ping_loss_ratios)

print(f"Avg packet loss: {avg_loss:.2%}")
print(f"Max packet loss: {max_loss:.2%}")
```

#### 5.3.3 Connectivity State Transitions (S6)

```python
# Count wifi_up state transitions
wifi_states = [sample.get("wifi", {}).get("wifi_up") for sample in telem_samples]
transitions = sum(1 for i in range(1, len(wifi_states)) if wifi_states[i] != wifi_states[i-1])

print(f"Total transitions in {len(telem_samples)} samples: {transitions}")
print(f"Expected transition frequency: {transitions / len(telem_samples) * 100:.4f}%")
```

---

## 6. Confirm Consecutive Testing (S1, S4, S5)

Setelah threshold diketahui **per-target**, lakukan testing kandidat `N` untuk S1, S4, S5.

### 6.1 Setup: Run Detector dengan kandidat N

**⚠️ Important**: Detector HARUS sudah implement per-target logic. Update detector code jika belum:

```python
# In detector.py, for S1 DNS_DEGRADED trigger:
triggered_targets = []
for target in self.targets:
    if dns_latency[target] >= threshold[target]:
        triggered_targets.append(target)

if len(triggered_targets) > 0:
    # trigger event dengan affected_scope
    affected_scope = self._determine_scope(triggered_targets)
```

Modifikasi `monitoring/default_config.json`:

```json
"events": {
  "DNS_DEGRADED": {
    "confirm_consecutive": 1,  // Test N=1 dulu
    "recovery_consecutive": 2
  },
  "HIGH_RTT": {
    "confirm_consecutive": 1,
    "recovery_consecutive": 2
  },
  "HTTP_SLOW": {
    "confirm_consecutive": 1,
    "recovery_consecutive": 2
  }
}
```

Jalankan detector pada preliminary test data dengan threshold yang sudah dikalibrasi:

```bash
python -m monitoring.controller \
  --config monitoring/default_config.json \
  --mode offline_replay \
  --input-dir ./monitoring/out/preliminary_test_run1/samples \
  --output-dir ./monitoring/out/preliminary_test_analysis_N1
```

### 6.2 Calculate False Alarm Rate (FAR)

```python
import json

# Load event log
with open("./monitoring/out/preliminary_test_analysis_N1/events_*.jsonl") as f:
    events = [json.loads(line) for line in f]

# Count false alarms (event triggered during normal condition)
false_alarms = sum(1 for e in events if e["hit"])

total_samples = len(fast_samples)  # or telemetry_samples
far = false_alarms / total_samples

print(f"N=1: FAR = {far:.4f} ({false_alarms} false alarms in {total_samples} samples)")
```

### 6.3 Repeat untuk N=2, 3, 4

Ulangi §6.1 dan §6.2 dengan:
- `confirm_consecutive: 2` → calculate FAR
- `confirm_consecutive: 3` → calculate FAR
- `confirm_consecutive: 4` → calculate FAR

### 6.4 Decision: Pick Best N

**Kriteria**:
- FAR harus < 0.5% (maximum 1 false alarm per 200 samples)
- Pick **smallest N** yang mencapai FAR target

**Contoh hasil**:
```
N=1: FAR = 2.1% (terlalu tinggi)
N=2: FAR = 0.3% ✓ (acceptable)
N=3: FAR = 0.1% (lebih baik, tapi detection lebih lambat)
N=4: FAR = 0.05% (overkill)

Decision: Gunakan N=2 untuk S1, S4, S5
```

---

## 7. Sliding Window Testing (S2, S3, S6)

### 7.1 Test m_dns and n_dns untuk S2

**Kandidat window sizes**:
- n_dns = 10, 15, 20

**Kandidat m values**:
- m_dns = 2, 3, 4

### 7.2 Procedure untuk setiap kombinasi

1. Update config:
```json
"events": {
  "DNS_TIMEOUT_BURST": {
    "n_dns_window_samples": 10,
    "m_dns_minimum": 2
  }
}
```

2. Run detector on preliminary data:
```bash
python -m monitoring.controller \
  --mode offline_replay \
  --config monitoring/default_config.json
```

3. Calculate FAR:
```python
far_dns_10_2 = count_false_alarms / total_samples
print(f"n=10, m=2: FAR = {far_dns_10_2:.4f}")
```

4. Repeat untuk all (n, m) kombinasi

### 7.3 Decision Matrix

Buat table untuk FAR semua kombinasi:

| n_dns \ m_dns | m=2 | m=3 | m=4 |
|---|---|---|---|
| **10** | FAR? | FAR? | FAR? |
| **15** | FAR? | FAR? | FAR? |
| **20** | FAR? | FAR? | FAR? |

**Pick combination dengan FAR < 0.5% dan N terkecil.**

### 7.4 Repeat untuk S3 (m_ping, n_ping) dan S6 (m_transition)

---

## 8. Final Output

Setelah semua analysis selesai, generate **final config** dengan struktur per-target:

```json
{
  "thresholds": {
    "dns_latency_threshold_ms": {
      "its.ac.id": 25,
      "google.com": 100
    },
    "rtt_threshold_ms": 50,
    "http_total_threshold_ms": {
      "https://www.its.ac.id": 1200
    },
    "http_ttfb_threshold_ms": {
      "https://www.its.ac.id": 600
    },
    "loss_threshold_pct": <tuned_from_S3>,
    "flap_transition_threshold": <m_transition>
  },
  "events": {
    "DNS_DEGRADED": {
      "confirm_consecutive": <best_N>,
      "recovery_consecutive": 2
    },
    "DNS_TIMEOUT_BURST": {
      "n_dns_window_samples": <best_n_dns>,
      "m_dns_minimum": <best_m_dns>
    },
    "LOSS_BURST": {
      "n_ping_window_samples": <best_n_ping>,
      "m_ping_minimum": <best_m_ping>
    },
    "HIGH_RTT": {
      "confirm_consecutive": <best_N>,
      "recovery_consecutive": 2
    },
    "HTTP_SLOW": {
      "confirm_consecutive": <best_N>,
      "recovery_consecutive": 2
    },
    "CONNECTIVITY_FLAP": {
      "m_transition": <best_m_transition>,
      "flap_window_sec": 90
    }
  }
}
```

**Key differences from placeholder config**:
- `dns_latency_threshold_ms` is now **dict per-target**, not single number
- `http_total_threshold_ms` is now **dict per-URL**, not single number
- `http_ttfb_threshold_ms` is now **dict per-URL**, not single number
- All thresholds are calculated from P99, not hardcoded

---

## 9. Troubleshooting

### Q: Fast probe berhenti setelah N sampel
**A**: Check log untuk errors. Likely causes:
- DNS timeout (2s) terlalu pendek → increase
- Interface down → verify `ip link show`
- Python error → check exception log

### Q: FAR > 1% untuk semua N values
**A**: Threshold terlalu rendah, atau jaringan tidak stabil:
- Verify threshold calculation (P99 correct?)
- Check preliminary test data: ada anomali?
- Network unstable during test? → repeat test

### Q: Telemetry probe tidak berjalan
**A**: Check requirements:
- HTTP target reachable? `curl https://www.its.ac.id`
- DNS targets resolvable? `dig its.ac.id`
- Interface IP addressable? `ip route`

---

## 10. Notes & Tips

1. **Parallel Probes**: Fast dan Telemetry berjalan paralel, tidak perlu menunggu
2. **Data Backup**: Simpan output directory sebelum delete
3. **Version Control**: Document hasil di Git dengan timestamp
4. **Repeatability**: Jika setup berubah (interface, DNS target), repeat preliminary test
5. **Sampling Consistency**: Jangan pause monitoring di tengah-tengah; akan corrupt window calculations
