# Potential Issues & Recommendations

## Critical Issues

### ⚠️ Issue 1: Hardcoded Interface Names

**File**: `fault-injection/fi-scripts/fault_common.sh`

```bash
HOTSPOT_IF="${HOTSPOT_IF:-ap0}"
UPSTREAM_IF="${UPSTREAM_IF:-wlxd037456b1bc8}"
```

**Problem**:
- `UPSTREAM_IF=wlxd037456b1bc8` adalah MAC-based name yang spesifik untuk USB adapter Anda
- Jika adapter berbeda atau dipindah port, script akan gagal dengan error "Interface not found"
- Interface name bisa berubah setiap reboot

**Recommendation**:
1. Verify interface names sebelum menjalankan fault injection:
```bash
ip link show  # Catat nama interface hotspot dan upstream
```

2. Set environment variable sebelum menjalankan script:
```bash
export HOTSPOT_IF=ap0
export UPSTREAM_IF=wlan0  # atau nama actual interface Anda
sudo ./fault_dns_delay.sh start 400
```

3. Atau hardcode saat test:
```bash
sed -i 's/UPSTREAM_IF=.*/UPSTREAM_IF="wlan0"/' fault_common.sh
```

---

### ⚠️ Issue 2: Threshold Hardcoded & Not Per-Target

**File**: `monitoring/default_config.json`

```json
"thresholds": {
  "dns_latency_threshold_ms": 800,
  "rtt_threshold_ms": 300,
  "http_total_threshold_ms": 2000,
  ...
}
```

**Problems**:
1. Threshold ini adalah **placeholder generic**, tidak dikalibrasi dari preliminary test
2. **Critical**: `dns_latency_threshold_ms` dan `http_total_threshold_ms` HARUS per-target, bukan single value
   - its.ac.id mungkin P99=25ms, google.com P99=100ms
   - Single value 800ms membuat detection invalid
3. False alarm rate akan tinggi atau deteksi terlalu lambat

**MUST DO**:
1. Preliminary test **WAJIB** dilakukan (lihat PRELIMINARY_TEST_GUIDELINE.md)
2. Threshold diperhitungkan dari P99 **per-target** (§5.2 guideline)
3. Final config structure harus:
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
    ...
  }
}
```

**Recommendation**:
1. Jangan gunakan placeholder threshold untuk testing
2. Follow §5–8 di PRELIMINARY_TEST_GUIDELINE.md untuk calibration
3. Verify detector.py implement per-target trigger logic (§6.1 guideline)

---

### ⚠️ Issue 3: DNS Target Mismatch Between Fast & Telemetry Probe

**File**: `monitoring/default_config.json`

Fast probe targets:
```json
"targets": [
  {"name": "its.ac.id", "scope": "internal"},
  {"name": "google.com", "scope": "external"}
]
```

Telemetry probe targets:
```json
"dns_targets": [
  {"name": "its.ac.id", "scope": "internal"},
  {"name": "google.com", "scope": "external"},
  {"name": "youtube.com", "scope": "external"}  // Extra!
]
```

**Problem**:
- `youtube.com` tidak ada di fast probe, hanya di telemetry
- Ini menyulitkan korelasi antara fast samples dan telemetry samples
- Event trigger logic mungkin tidak konsisten jika mixing targets

**Recommendation**:
1. Keep target list sama untuk fast dan telemetry:
```json
// Gunakan HANYA untuk preliminary test
"fast_probe": {
  "targets": [
    {"name": "its.ac.id", "scope": "internal"},
    {"name": "google.com", "scope": "external"}
  ]
},
"telemetry_probe": {
  "dns_targets": [
    {"name": "its.ac.id", "scope": "internal"},
    {"name": "google.com", "scope": "external"}
  ]
}
```

2. Atau, jika perlu youtube.com untuk S5 testing:
   - Tambahkan di fast probe juga (tapi akan increase fast probe duration)
   - Atau tulis trigger logic yang robust terhadap missing targets

---

## Medium Severity Issues

### ⚠️ Issue 4: HTTP Timeout Mungkin Terlalu Lama

**File**: `monitoring/default_config.json`

```json
"telemetry_probe": {
  "http_connect_timeout_sec": 5,
  "http_max_time_sec": 15
}
```

**Problem**:
- Telemetry probe interval 30 detik
- Jika HTTP request timeout 15 detik, dan ada 1 target, itu OK (15 + overhead < 30)
- Tapi jika ada multiple targets atau slow network, bisa overlap dengan interval berikutnya
- Jika timeout terjadi, telemetry sample akan terlambat, menyebabkan data gap

**Recommendation**:
1. Verifikasi durasi actual HTTP request:
```bash
time curl -I https://www.its.ac.id --max-time 15 --connect-timeout 5
```

2. Set timeout lebih konservatif:
```json
"http_connect_timeout_sec": 3,
"http_max_time_sec": 10
```

3. Atau verify dengan preliminary test bahwa HTTP request selalu < 20 detik

---

### ⚠️ Issue 5: DNS Timeout Inconsistency

**File**: `monitoring/default_config.json`

```json
"fast_probe": {
  "dns_timeout_sec": 2.0
},
"telemetry_probe": {
  "dns_timeout_sec": 5
}
```

**Problem**:
- Fast probe timeout 2 detik, interval 5 detik → OK margin 3 detik
- Telemetry probe timeout 5 detik, interval 30 detik → OK margin 25 detik
- Tapi inconsistency bisa menyebabkan behavior berbeda saat evaluasi

**Recommendation**:
1. Jalankan preliminary test dan measure actual DNS latency P99:
```python
# Dari preliminary test data
p99_dns = quantiles(dns_latencies, n=100)[98]
print(f"Measured P99 DNS latency: {p99_dns}ms")
```

2. Set timeout dengan safety margin:
```json
"dns_timeout_sec": ceiling(p99_dns / 1000 + 1)  # P99 + 1 second margin
```

3. Atau standardize to 3 detik untuk keduanya (conservative):
```json
"fast_probe": {
  "dns_timeout_sec": 3.0
},
"telemetry_probe": {
  "dns_timeout_sec": 3.0
}
```

---

### ⚠️ Issue 6: confirm_consecutive vs recovery_consecutive Tidak Dijelaskan

**File**: `monitoring/default_config.json`

```json
"DNS_DEGRADED": {
  "confirm_consecutive": 2,
  "recovery_consecutive": 2
}
```

**Problem**:
- `recovery_consecutive` adalah jumlah sampel **baik** yang diperlukan untuk trigger **recovery**
- Ini not implemented/explained dalam kode detector
- Mungkin ada bug atau incomplete implementation

**Recommendation**:
1. Check detector.py untuk lihat apakah `recovery_consecutive` digunakan
2. Jika tidak digunakan, remove dari config atau implement
3. Atau clarify bahwa `recovery_consecutive` adalah part of future work

---

## Low Severity / Info

### ℹ️ Issue 7: Throughput Probe Disabled

**File**: `monitoring/default_config.json`

```json
"throughput_probe": {
  "enabled": false
}
```

**Info**: Throughput probe tidak digunakan untuk test ini. OK. Tapi perhatikan:
- S5 (HTTP_SLOW) bukan bandwidth test
- Jika ingin test bandwidth throttle, perlu enable dan setup HTTP server di `http-serve/`

---

### ℹ️ Issue 8: Evidence Manager Dependency

**File**: `monitoring/controller.py`

Setiap sample collection juga trigger evidence manager. Jika disk space limited, output bisa membesar cepat.

**Recommendation**:
```json
"evidence": {
  "enabled": false  // Disable untuk preliminary test jika disk terbatas
}
```

---

### ℹ️ Issue 9: Multiple Runs Need Separate Output Dirs

**Usage**:
```bash
# Run 1
python -m monitoring.controller ... --output-dir ./out/run1

# Run 2 (jangan gunakan output-dir yang sama)
python -m monitoring.controller ... --output-dir ./out/run2
```

**Why**: JSONL files akan append, bukan overwrite. Jika rerun dengan dir yang sama, data akan corrupt.

---

## Summary Checklist untuk Sebelum Preliminary Test

- [ ] Verify interface names (HOTSPOT_IF, UPSTREAM_IF)
- [ ] Set environment variables atau update fault_common.sh
- [ ] Calibrate thresholds akan dilakukan AFTER preliminary test (§5 guideline)
- [ ] **Threshold MUST per-target** (dns: its.ac.id vs google.com, http: per-URL)
- [ ] Verify detector.py implement per-target trigger logic (NOT averaging)
- [ ] Standardize DNS targets di fast & telemetry probe
- [ ] Verify HTTP timeout < interval (15s < 30s margin)
- [ ] Check DNS latency actual values dari test sample
- [ ] Prepare separate output directories untuk setiap run
- [ ] Ensure disk space sufficient (1000–10000 JSONL samples × 2 probes)
- [ ] Document network environment (ISP, location, time of day)

---

## Questions untuk User

1. **Interface names**: Verify HOTSPOT_IF dan UPSTREAM_IF dengan `ip link show` di UNO Q
2. **HTTP target**: Apakah `https://www.its.ac.id` reachable dari UNO Q? Atau perlu setup local HTTP server?
3. **Testing location**: Apakah network environment akan sama sepanjang preliminary test + fault injection test?
4. **Multiple runs**: Apakah akan ada multiple preliminary tests (repeat untuk stability), atau single run?
5. **Detector implementation** ⭐: Apakah `monitoring/detector.py` sudah implement per-target trigger logic? Atau masih averaging?
