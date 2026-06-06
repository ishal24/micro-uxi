# Preliminary Test Guideline untuk Micro-UXI

**Tanggal**: May 2026  
**Target Device**: Arduino UNO Q  
**Tujuan**: Mengambil data kondisi normal jaringan untuk mengalibrasi threshold dan parameter trigger pada event S1–S6.

---

# 1. Overview

Preliminary test adalah pengujian kondisi jaringan **normal** tanpa fault injection. Data dari preliminary test digunakan untuk:

1. Menentukan threshold statis baseline monitoring, seperti:
   - `T_dns_latency`
   - `T_rtt`
   - `T_http_total`
   - `T_http_ttfb`

2. Menentukan parameter trigger berbasis konfirmasi dan window, seperti:
   - `N_dns`
   - `N_rtt`
   - `N_http`
   - `m_dns`, `n_dns`
   - `m_ping`, `n_ping`
   - `m_transition`, `W_flap`

3. Menyediakan baseline normal untuk menghitung **False Alarm Rate (FAR)** sebelum fault injection dilakukan.

Preliminary test **bukan** fault injection. Selama preliminary test, jaringan harus berada dalam kondisi normal sesuai scope penelitian.

---

# 2. Mapping Probe dan Event

Berdasarkan struktur monitoring code saat ini, event S1–S6 dibagi ke dua probe utama:

| Probe | Event | Alasan |
|---|---|---|
| **Fast Probe** | S1 `DNS_DEGRADED` | Mengambil DNS latency cepat |
| **Fast Probe** | S2 `DNS_TIMEOUT_BURST` | Mengambil DNS success/failure secara cepat |
| **Fast Probe** | S3 `LOSS_BURST` | Mengambil ping success/failure untuk window packet loss |
| **Fast Probe** | S6 `CONNECTIVITY_FLAP` | Mengambil state `connectivity_ok` untuk transition count |
| **Telemetry Probe** | S4 `HIGH_RTT` | Mengambil ping batch: `rtt_avg_ms`, `loss_pct`, `rtt_mdev_ms` |
| **Telemetry Probe** | S5 `HTTP_SLOW` | Mengambil HTTP timing: `http_total_ms`, `http_ttfb_ms`, `curl_rc`, `http_status` |

`ThroughputProbe` tidak digunakan untuk S1–S6 karena event bandwidth/throughput tidak termasuk dalam scope pengujian utama.

---

# 3. Sampling Strategy dan Durasi

## 3.1 Prinsip Umum

Interval sampling harus sesuai dengan jenis event.

Event yang bersifat cepat atau transien membutuhkan interval sampling lebih kecil. Jika interval terlalu besar, event pendek dapat terlewat atau jumlah sampel dalam sliding window menjadi terlalu sedikit.

## 3.2 Rekomendasi Interval

| Probe | Event | Interval disarankan | Alasan |
|---|---|---:|---|
| Fast | S1, S2, S3, S6 | 1–2 detik | Butuh observasi cepat untuk DNS timeout, packet loss burst, dan flap |
| Telemetry | S4, S5 | 10–30 detik | HTTP dan ping batch lebih berat; interval tergantung target MTTD |
| Throughput | Tidak digunakan | disabled | Tidak dipakai untuk S1–S6 |

## 3.3 Catatan terhadap Config Lama

Jika `fast_interval_sec = 5`, maka:

```text
n_ping = 20
window = n_ping × fast_interval
window = 20 × 5 detik
window = 100 detik
```

Window 100 detik terlalu panjang untuk `LOSS_BURST` yang ingin menangkap gangguan pendek.

Karena itu, untuk preliminary test dan fault injection S2/S3/S6, lebih baik gunakan:

```json
"fast_interval_sec": 1
```

atau:

```json
"fast_interval_sec": 2
```

Jika `telemetry_interval_sec = 30` dan `N_http = 2`, maka estimasi delay konfirmasi HTTP adalah sekitar:

```text
confirmation_delay ≈ 2 × 30 detik = 60 detik
```

Ini masih bisa diterima jika fault injection S4/S5 dibuat cukup lama, tetapi tidak cocok jika target MTTD rendah. Jika ingin MTTD lebih cepat, gunakan:

```json
"telemetry_interval_sec": 10
```

## 3.4 Durasi Preliminary Test

Target ideal:

```text
10.000 sampel valid per metrik/per target
```

Batas bawah awal:

```text
1.000 sampel valid per metrik/per target
```

Perkiraan durasi:

| Probe | Interval | 1.000 Sampel | 10.000 Sampel |
|---|---:|---:|---:|
| Fast | 1 detik | ±16,7 menit | ±2,8 jam |
| Fast | 2 detik | ±33,3 menit | ±5,6 jam |
| Fast | 5 detik | ±1,4 jam | ±13,9 jam |
| Telemetry | 10 detik | ±2,8 jam | ±27,8 jam |
| Telemetry | 30 detik | ±8,3 jam | ±83,3 jam |

Rekomendasi praktis:

```text
Fast Probe:
  target minimal 10.000 sampel jika interval 1–2 detik masih memungkinkan.

Telemetry Probe:
  minimal 1.000 sampel valid per HTTP/RTT target.
  Jika waktu memungkinkan, tambah durasi agar threshold P99 lebih stabil.
```

Karena telemetry lebih mahal dan lebih lambat, 10.000 sampel telemetry bisa tidak realistis. Jika hanya memperoleh 1.000–2.000 sampel telemetry, threshold P99 tetap dapat digunakan sebagai baseline awal, tetapi harus dicatat sebagai keterbatasan.

---

# 4. Kondisi Jaringan Normal

Preliminary test harus dilakukan pada kondisi normal yang sesuai dengan scope penelitian.

Pastikan:

- Tidak ada fault injection.
- Tidak ada aktivitas abnormal seperti download besar, stress test, atau konfigurasi jaringan berubah.
- Lokasi device tetap.
- SSID/AP tetap.
- DNS resolver tetap.
- Target DNS/HTTP/ping tetap.
- Interface yang dipantau tidak berubah.
- Waktu pengujian dicatat.

Catatan penting:

```text
Jika preliminary test hanya dilakukan saat jaringan sangat sepi,
threshold yang dihasilkan bisa terlalu rendah dan berpotensi menghasilkan false alarm
saat jaringan berada pada kondisi normal yang lebih ramai.
```

Karena itu, pilih waktu yang merepresentasikan kondisi normal dalam scope penelitian. Jika sistem ditujukan untuk lingkungan kampus, preliminary test sebaiknya mencakup sebagian jam operasional normal, bukan hanya jam paling sepi.

---

# 5. Target Pengujian

## 5.1 Prinsip Target

Jangan menggunakan satu target saja. Target harus mewakili beberapa scope:

| Scope | Tujuan |
|---|---|
| Gateway/local | Mendeteksi masalah lokal/AP/upstream dekat |
| External stable | Baseline eksternal yang relatif stabil |
| Internal | Mengukur pengalaman ke layanan internal/kampus |

Threshold harus dihitung **per target** atau **per URL**, bukan di-average.

## 5.2 Rekomendasi Target

### Fast Probe

```json
"fast_probe": {
  "enabled": true,
  "ping_target": "8.8.8.8",
  "targets": [
    {"name": "its.ac.id", "scope": "internal"},
    {"name": "google.com", "scope": "external"}
  ]
}
```

### Telemetry Probe

```json
"telemetry_probe": {
  "enabled": true,
  "ping_target": "8.8.8.8",
  "dns_targets": [
    {"name": "its.ac.id", "scope": "internal"},
    {"name": "google.com", "scope": "external"}
  ],
  "http_targets": [
    {
      "url": "https://www.its.ac.id",
      "scope": "internal",
      "expected_status_min": 200,
      "expected_status_max": 399
    },
    {
      "url": "https://www.gstatic.com/generate_204",
      "scope": "external",
      "expected_status_min": 204,
      "expected_status_max": 204
    }
  ]
}
```

Jika hanya memakai `https://www.its.ac.id` sebagai HTTP target, maka S5 hanya dapat menyimpulkan HTTP slow pada target internal. Untuk mendukung `affected_scope = internal | external | all`, minimal harus ada satu HTTP target internal dan satu HTTP target external.

---

# 6. Interface dan Lokasi Eksekusi

## 6.1 Tentukan Lokasi Monitoring

Harus dipastikan monitoring dijalankan di mana:

### Opsi A — Monitoring dijalankan di Arduino UNO Q

Ini opsi yang paling sesuai dengan konsep Micro-UXI.

```text
device.iface = interface UNO Q yang ingin dipantau
```

Jika tujuan monitoring adalah pengalaman UNO Q terhadap upstream/internet, gunakan upstream interface.

Jika tujuan monitoring adalah hotspot/AP interface, gunakan `ap0`.

### Opsi B — Monitoring dijalankan di laptop client

Jika monitoring dijalankan di laptop, maka `device.iface` harus menggunakan interface Wi-Fi laptop, bukan `ap0` milik UNO Q.

## 6.2 Pilih Interface yang Tepat

Jika UNO Q memiliki:

```text
ap0 = interface hotspot/access point
wlxd037456b1bc8 = upstream Wi-Fi interface
```

Maka:

```text
Untuk mengukur experience UNO Q ke internet/upstream:
  device.iface = wlxd037456b1bc8

Untuk mengukur status hotspot interface:
  device.iface = ap0
```

Jangan memilih interface tanpa menjelaskan tujuan pengukuran, karena interpretasi hasil akan berbeda.

---

# 7. Config Preliminary Test

## 7.1 Disable Throughput

Karena throughput tidak digunakan untuk S1–S6:

```json
"throughput_probe": {
  "enabled": false
}
```

## 7.2 Gunakan Threshold Sementara Tinggi

Jangan set threshold ke `null`, karena code saat ini dapat gagal jika threshold dikonversi ke `float`.

Untuk preliminary test, gunakan nilai threshold sementara yang sangat tinggi agar detector tidak mudah trigger:

```json
"thresholds": {
  "dns_latency_threshold_ms": 99999,
  "rtt_threshold_ms": 99999,
  "http_total_threshold_ms": 99999,
  "http_ttfb_threshold_ms": 99999,
  "loss_threshold_pct": 100,
  "dns_fail_ratio_threshold": 1.0,
  "flap_transition_threshold": 99999
}
```

Alternatif yang lebih bersih adalah menambahkan mode `collect-only`, tetapi mode tersebut belum tersedia di code saat ini.

## 7.3 Detection Mode

Untuk preliminary test, tujuan utama adalah mengumpulkan data normal. Detector boleh tetap berjalan dengan threshold sementara tinggi, tetapi event hasil preliminary test tidak dipakai sebagai hasil utama kecuali untuk menghitung FAR setelah threshold final dikalibrasi.

---

# 8. Running Preliminary Test

## 8.1 Prepare Environment

Di device yang menjalankan monitoring:

```bash
ip link show
ip addr
ip route
```

Pastikan interface yang digunakan sesuai dengan `device.iface`.

Tes konektivitas:

```bash
ping -c 5 8.8.8.8
dig its.ac.id
dig google.com
curl -I https://www.its.ac.id
curl -I https://www.gstatic.com/generate_204
```

## 8.2 Start Monitoring

Berdasarkan code controller saat ini, gunakan mode `all`.

Contoh:

```bash
python -m monitoring.controller \
  --config monitoring/default_config.json \
  --mode all \
  --duration 8h \
  --output ./monitoring/out/preliminary_test_run1 \
  --detection-mode static
```

Jika argumen berbeda pada versi code yang sedang digunakan, cek:

```bash
python -m monitoring.controller --help
```

Expected output:

```text
./monitoring/out/preliminary_test_run1/samples/fast_*.jsonl
./monitoring/out/preliminary_test_run1/samples/telemetry_*.jsonl
```

## 8.3 Monitor Progress

```bash
while true; do
  fast_count=$(cat ./monitoring/out/preliminary_test_run1/samples/fast_*.jsonl 2>/dev/null | wc -l)
  telem_count=$(cat ./monitoring/out/preliminary_test_run1/samples/telemetry_*.jsonl 2>/dev/null | wc -l)
  echo "Fast: $fast_count | Telemetry: $telem_count"
  sleep 60
done
```

---

# 9. Post-Test: Load Data

## 9.1 Load JSONL

```python
import json
from pathlib import Path

def load_jsonl(pattern):
    samples = []
    for path in Path(".").glob(pattern):
        with open(path, "r") as f:
            for line in f:
                if line.strip():
                    samples.append(json.loads(line))
    return samples

base_dir = Path("./monitoring/out/preliminary_test_run1/samples")

fast_samples = []
for path in base_dir.glob("fast_*.jsonl"):
    with open(path, "r") as f:
        for line in f:
            if line.strip():
                fast_samples.append(json.loads(line))

telem_samples = []
for path in base_dir.glob("telemetry_*.jsonl"):
    with open(path, "r") as f:
        for line in f:
            if line.strip():
                telem_samples.append(json.loads(line))

print(f"Fast samples: {len(fast_samples)}")
print(f"Telemetry samples: {len(telem_samples)}")
```

## 9.2 P99 Helper

```python
import math

def percentile(values, p):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    k = (len(values) - 1) * (p / 100)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return values[int(k)]
    return values[f] * (c - k) + values[c] * (k - f)
```

---

# 10. Threshold Calculation

## 10.1 DNS Latency Threshold S1 — Fast Probe, Per Target

Field yang digunakan:

```text
sample["dns"][i]["target"]
sample["dns"][i]["success"]
sample["dns"][i]["latency_ms"]
```

Script:

```python
dns_latencies_by_target = {}

for sample in fast_samples:
    for dns_entry in sample.get("dns", []):
        if dns_entry.get("success") is True:
            target = dns_entry.get("target")
            latency = dns_entry.get("latency_ms")
            if target is not None and latency is not None:
                dns_latencies_by_target.setdefault(target, []).append(latency)

T_dns_latency = {}

for target, values in dns_latencies_by_target.items():
    if len(values) < 1000:
        print(f"WARNING: {target} only has {len(values)} valid DNS samples")
    T_dns_latency[target] = percentile(values, 99)
    print(f"T_dns_latency[{target}] = {T_dns_latency[target]} ms from {len(values)} samples")
```

Output:

```json
"dns_latency_threshold_ms": {
  "its.ac.id": 25,
  "google.com": 100
}
```

Catatan:

```text
Code detector saat ini belum support threshold dictionary.
Jika ingin memakai per-target threshold, detector.py harus diubah.
Jika code belum diubah, threshold per-target tidak bisa langsung dimasukkan ke config.
```

---

## 10.2 RTT Threshold S4 — Telemetry Probe

Field yang digunakan:

```text
sample["ping"]["rtt_avg_ms"]
```

Script:

```python
rtt_values = []

for sample in telem_samples:
    ping = sample.get("ping", {})
    rtt = ping.get("rtt_avg_ms")
    if rtt is not None:
        rtt_values.append(rtt)

if len(rtt_values) < 1000:
    print(f"WARNING: RTT only has {len(rtt_values)} valid samples")

T_rtt = percentile(rtt_values, 99)
print(f"T_rtt = {T_rtt} ms from {len(rtt_values)} samples")
```

Output:

```json
"rtt_threshold_ms": 50
```

Jika nanti telemetry menggunakan beberapa RTT target, threshold harus dihitung per target.

---

## 10.3 HTTP Total dan TTFB Threshold S5 — Telemetry Probe, Per URL

Field yang digunakan:

```text
sample["http"][i]["url"]
sample["http"][i]["http_ok"]
sample["http"][i]["http_status"]
sample["http"][i]["http_total_ms"]
sample["http"][i]["http_ttfb_ms"]
```

Script:

```python
http_timings_by_url = {}

def expected_status_ok(http_entry):
    status = http_entry.get("http_status")
    if status is None:
        return False
    # Default expected range; adjust per URL if config uses stricter rule.
    return 200 <= int(status) <= 399

for sample in telem_samples:
    for http_entry in sample.get("http", []):
        if http_entry.get("http_ok") is True and expected_status_ok(http_entry):
            url = http_entry.get("url")
            total = http_entry.get("http_total_ms")
            ttfb = http_entry.get("http_ttfb_ms")

            if url is None:
                continue

            http_timings_by_url.setdefault(url, {"total": [], "ttfb": []})

            if total is not None:
                http_timings_by_url[url]["total"].append(total)
            if ttfb is not None:
                http_timings_by_url[url]["ttfb"].append(ttfb)

T_http_total = {}
T_http_ttfb = {}

for url, timings in http_timings_by_url.items():
    if len(timings["total"]) < 500:
        print(f"WARNING: {url} only has {len(timings['total'])} valid HTTP total samples")
    if len(timings["ttfb"]) < 500:
        print(f"WARNING: {url} only has {len(timings['ttfb'])} valid HTTP TTFB samples")

    T_http_total[url] = percentile(timings["total"], 99)
    T_http_ttfb[url] = percentile(timings["ttfb"], 99)

    print(f"T_http_total[{url}] = {T_http_total[url]} ms")
    print(f"T_http_ttfb[{url}] = {T_http_ttfb[url]} ms")
```

Output:

```json
"http_total_threshold_ms": {
  "https://www.its.ac.id": 1200,
  "https://www.gstatic.com/generate_204": 500
},
"http_ttfb_threshold_ms": {
  "https://www.its.ac.id": 600,
  "https://www.gstatic.com/generate_204": 200
}
```

Catatan:

```text
Code detector saat ini belum support threshold dictionary untuk HTTP.
Jika ingin memakai per-URL threshold, detector.py harus diubah.
```

---

# 11. Sliding Window Parameter Calculation

S2, S3, dan S6 tidak cukup dihitung dari satu sampel. Parameter ditentukan dari window.

## 11.1 S2 DNS_TIMEOUT_BURST — Fast Probe

Gunakan fast samples karena S2 berasal dari fast probe.

### Candidate

```text
n_dns = 10, 15, 20
m_dns = 2, 3, 4
```

### Window Calculation

Jika pakai sample-based window:

```python
def dns_fail_count_window(samples, target_scope=None):
    fail_count = 0
    total_count = 0

    for sample in samples:
        for dns_entry in sample.get("dns", []):
            if target_scope is not None and dns_entry.get("scope") != target_scope:
                continue
            total_count += 1
            if dns_entry.get("success") is False:
                fail_count += 1

    return fail_count, total_count
```

Untuk replay:

```python
def evaluate_s2_windows(fast_samples, n_dns, m_dns, scope=None):
    triggers = []

    for i in range(n_dns - 1, len(fast_samples)):
        window = fast_samples[i - n_dns + 1 : i + 1]
        fail_count, total_count = dns_fail_count_window(window, target_scope=scope)

        if total_count >= n_dns and fail_count >= m_dns:
            triggers.append(fast_samples[i])

    return triggers
```

Catatan:

```text
Jika ada dua DNS target per fast sample, total_count bisa lebih besar daripada n_dns.
Karena itu definisikan dengan jelas apakah n_dns berarti:
  a. jumlah fast samples, atau
  b. jumlah DNS checks.

Untuk implementasi awal, lebih sederhana:
  n_dns = jumlah DNS checks dalam window
  m_dns = jumlah DNS failures dalam window
```

## 11.2 S3 LOSS_BURST — Fast Probe

Gunakan fast samples karena S3 berasal dari `ping.success` fast probe.

### Candidate

```text
n_ping = 20, 30, 40
m_ping = 2, 3, 4, 5
```

### Window Calculation

```python
def evaluate_s3_windows(fast_samples, n_ping, m_ping):
    triggers = []

    for i in range(n_ping - 1, len(fast_samples)):
        window = fast_samples[i - n_ping + 1 : i + 1]

        ping_samples = [
            s for s in window
            if s.get("ping", {}).get("success") is not None
        ]

        if len(ping_samples) < n_ping:
            continue

        fail_count = sum(
            1 for s in ping_samples
            if s.get("ping", {}).get("success") is False
        )

        wifi_up_count = sum(
            1 for s in window
            if s.get("wifi", {}).get("wifi_up") is True
        )

        if wifi_up_count < len(window):
            continue

        if fail_count >= m_ping:
            triggers.append(fast_samples[i])

    return triggers
```

## 11.3 S6 CONNECTIVITY_FLAP — Fast Probe

Gunakan fast samples karena S6 berasal dari `connectivity_ok`.

### Candidate

```text
W_flap = 20, 30, 60 detik
m_transition = 2, 3, 4
```

### Window Calculation

Untuk sample-based window:

```python
def transition_count(states):
    count = 0
    for i in range(1, len(states)):
        if states[i] != states[i - 1]:
            count += 1
    return count

def evaluate_s6_windows(fast_samples, n_flap, m_transition):
    triggers = []

    for i in range(n_flap - 1, len(fast_samples)):
        window = fast_samples[i - n_flap + 1 : i + 1]
        states = [s.get("connectivity_ok") for s in window]

        if any(state is None for state in states):
            continue

        transitions = transition_count(states)

        if transitions >= m_transition:
            triggers.append(fast_samples[i])

    return triggers
```

Jika pakai time-based window, gunakan timestamp dan ambil semua sample dengan timestamp dalam `W_flap`.

---

# 12. Confirm Consecutive Testing

Confirm consecutive digunakan untuk:

```text
S1 DNS_DEGRADED
S4 HIGH_RTT
S5 HTTP_SLOW
```

Candidate:

```text
N = 1, 2, 3, 4
```

Prosedur:

```text
1. Gunakan threshold hasil P99.
2. Jalankan detector pada normal validation data.
3. Hitung FAR.
4. Jalankan detector pada fault injection calibration data.
5. Hitung MTTD, recall, dan F1.
6. Pilih N terkecil yang memenuhi target FAR dan tetap menghasilkan MTTD rendah.
```

Catatan:

```text
Code saat ini belum menyediakan offline_replay mode.
Untuk melakukan pengujian kandidat N tanpa menjalankan ulang data secara live,
perlu dibuat script replay tambahan.
```

---

# 13. FAR Calculation

FAR lebih jelas dihitung sebagai false event starts per hour, bukan event per sample.

Rumus:

```text
FAR = jumlah event start pada normal run / durasi normal run dalam jam
```

Contoh:

```python
false_event_starts = sum(
    1 for e in events
    if e.get("kind") == "started"
)

duration_hours = test_duration_seconds / 3600
far_per_hour = false_event_starts / duration_hours

print(f"FAR = {far_per_hour} false events/hour")
```

Jika format event log berbeda, sesuaikan field `kind` dengan format output code.

Target FAR harus ditentukan sebelum memilih parameter. Contoh:

```text
FAR <= 0.5 false events/hour
```

atau:

```text
FAR <= 1 false event per 2 jam
```

Jangan memilih parameter hanya karena “kelihatan bagus”. Gunakan target FAR yang eksplisit.

---

# 14. Final Config Output

Setelah threshold dan parameter dipilih, hasil akhir berupa config kalibrasi.

## 14.1 Jika Detector Belum Diubah

Jika code detector masih hanya menerima threshold global, maka config harus tetap berbentuk angka:

```json
{
  "thresholds": {
    "dns_latency_threshold_ms": 300,
    "rtt_threshold_ms": 50,
    "http_total_threshold_ms": 1200,
    "http_ttfb_threshold_ms": 600,
    "loss_threshold_pct": 20,
    "flap_transition_threshold": 2
  }
}
```

Namun ini berarti threshold belum per-target/per-URL.

## 14.2 Jika Detector Sudah Support Per-Target Threshold

Jika detector sudah diubah untuk mendukung threshold dictionary:

```json
{
  "thresholds": {
    "dns_latency_threshold_ms": {
      "its.ac.id": 25,
      "google.com": 100
    },
    "rtt_threshold_ms": {
      "8.8.8.8": 50
    },
    "http_total_threshold_ms": {
      "https://www.its.ac.id": 1200,
      "https://www.gstatic.com/generate_204": 500
    },
    "http_ttfb_threshold_ms": {
      "https://www.its.ac.id": 600,
      "https://www.gstatic.com/generate_204": 200
    }
  },
  "events": {
    "DNS_DEGRADED": {
      "confirm_consecutive": 2,
      "recovery_consecutive": 2
    },
    "DNS_TIMEOUT_BURST": {
      "n_dns_window_samples": 10,
      "m_dns_minimum": 2
    },
    "LOSS_BURST": {
      "n_ping_window_samples": 20,
      "m_ping_minimum": 4
    },
    "HIGH_RTT": {
      "confirm_consecutive": 2,
      "recovery_consecutive": 2
    },
    "HTTP_SLOW": {
      "confirm_consecutive": 2,
      "recovery_consecutive": 2
    },
    "CONNECTIVITY_FLAP": {
      "flap_window_sec": 30,
      "m_transition": 2
    }
  }
}
```

---

# 15. Known Gaps terhadap Code Saat Ini

Guideline ini merekomendasikan beberapa hal yang belum sepenuhnya didukung code saat ini.

| Rekomendasi | Status code saat ini | Perlu perubahan |
|---|---|---|
| Per-target DNS threshold | Belum support | Ubah `detector.py` agar bisa membaca threshold dict |
| Per-URL HTTP threshold | Belum support | Ubah `detector.py` agar bisa membaca threshold dict |
| Offline replay | Belum ada | Tambah script `tools/replay_detector.py` |
| S2 temporal sliding window | Belum sesuai penuh | Tambah DNS history/window |
| S3 m-of-n count | Code sekarang memakai `loss_threshold_pct` | Bisa tetap pakai persentase atau ubah ke m-of-n |
| S5 supporting trigger eksplisit | Belum lengkap | Tambah cek DNS/RTT/loss agar tidak salah klasifikasi |
| Collect-only mode | Belum ada | Bisa ditambah, atau pakai threshold sementara tinggi |

---

# 16. Troubleshooting

## Q: Threshold P99 terlihat terlalu tinggi

Kemungkinan penyebab:

- Preliminary test mengandung gangguan yang sebenarnya bukan kondisi normal.
- Target tidak stabil.
- HTTP target terlalu berat.
- Ada traffic abnormal selama preliminary test.

Solusi:

- Cek distribusi data.
- Cek outlier tertinggi.
- Ulang preliminary test.
- Pisahkan target internal dan external.
- Jangan gabungkan threshold antar target.

## Q: FAR tetap tinggi walau N dinaikkan

Kemungkinan penyebab:

- Threshold terlalu rendah.
- Jaringan normal memang sangat fluktuatif.
- Preliminary test tidak representatif.
- Target tidak stabil.

Solusi:

- Gunakan validation normal run terpisah.
- Evaluasi target yang bermasalah.
- Tambah jumlah sampel preliminary.
- Pertimbangkan threshold per target/per scope.

## Q: S3 tidak pernah trigger

Kemungkinan penyebab:

- `fast_interval_sec` terlalu besar.
- `loss_window_sec` terlalu kecil.
- `minimum_samples` tidak tercapai.
- Fault injection terlalu pendek.

Solusi:

- Turunkan `fast_interval_sec` ke 1 detik.
- Pastikan window memiliki minimal `n_ping` sampel.
- Perpanjang durasi fault injection.

## Q: S5 sering trigger saat DNS atau RTT bermasalah

Kemungkinan penyebab:

- HTTP slow hanya symptom, bukan root cause.
- Detector belum mengecek supporting trigger DNS/RTT/loss.

Solusi:

- Tambahkan supporting trigger:
  - `dns_success == true`
  - `dns_latency_ms < T_dns_latency`
  - `rtt_avg_ms < T_rtt`
  - `ping_fail_count < m_ping`

---

# 17. Notes

1. Preliminary test harus disimpan dengan timestamp dan config yang digunakan.
2. Jika target, interface, lokasi, atau resolver berubah, preliminary test perlu diulang.
3. Threshold per-target lebih valid daripada threshold rata-rata.
4. FAR dihitung pada data normal, bukan pada fault injection.
5. MTTD, recall, dan F1 dihitung pada data fault injection dengan ground truth.
6. Jangan memakai data yang sama untuk semua tahap jika memungkinkan. Idealnya:
   - data normal calibration untuk P99
   - data normal validation untuk FAR
   - data fault calibration untuk memilih parameter
   - data fault test untuk evaluasi final