# README Skema Fault Injection Micro-UXI

Dokumen ini menjelaskan skema fault injection yang digunakan untuk mengevaluasi sistem Micro-UXI sebagai *network experience black-box event recorder*. Setiap skema mendefinisikan jenis gangguan, dampak ke pengguna, gejala yang diharapkan muncul pada metrik, logika trigger, logika recovery, evidence yang perlu direkam, dan field ground truth yang harus dicatat.

Tujuan utama dokumen ini adalah membuat eksperimen lebih konsisten dan dapat diulang. Setiap fault injection harus memiliki gejala yang jelas, metrik yang dapat diamati, dan ground truth bertimestamp agar hasil deteksi dapat dievaluasi menggunakan precision, recall, F1-score, false alarm rate, mean time to detect, dan kelengkapan evidence.

---

## 1. Model Evaluasi Umum

Setiap run eksperimen sebaiknya mengikuti struktur berikut.

1. **Warm-up / baseline phase**
   Jaringan dibiarkan dalam kondisi normal agar probe dapat mengamati nilai baseline.

2. **Fault injection phase**
   Gangguan terkontrol dijalankan. Fault injector wajib mencatat `fault_start_ts`, `fault_end_ts`, `scenario_id`, dan parameter injeksi.

3. **Event detection phase**
   Micro-UXI mengevaluasi telemetri. Event dipicu jika kondisi skema terpenuhi selama jumlah sampel yang ditentukan.

4. **Post-event / recovery phase**
   Gangguan dihentikan. Event baru ditutup setelah kondisi recovery terpenuhi.

5. **Evidence export phase**
   Sistem menyimpan telemetri, metadata event, snapshot diagnostik, serta pre/event/post window.

---

## 2. Field Umum Event

Setiap event yang terdeteksi sebaiknya memiliki struktur metadata yang konsisten.

```json
{
  "event_id": "evt-...",
  "run_id": "run-...",
  "scenario_id": "S1_DNS_DEGRADED",
  "event_type": "DNS_DEGRADED",
  "affected_scope": "internal | external | all | unknown",
  "affected_targets": ["portal.its.ac.id"],
  "severity": "low | medium | high",
  "ts_start": "2026-...",
  "ts_end": "2026-...",
  "trigger_reason": "max_dns_latency_ms=720 >= threshold=300",
  "recovery_reason": "dns_latency_ms kembali normal selama K detik"
}
```

### 2.1 Affected Scope

Untuk event DNS dan HTTP, target sebaiknya dikelompokkan berdasarkan scope.

* `internal`: layanan milik organisasi/kampus, misalnya `portal.its.ac.id`, `classroom.its.ac.id`, atau endpoint internal lain.
* `external`: layanan publik atau SaaS, misalnya `google.com`, `youtube.com`, `drive.google.com`, atau `atlassian.net`.
* `all`: target internal dan external sama-sama terdampak.
* `unknown`: evidence tidak cukup untuk menentukan scope.

Nama event tetap dibuat stabil. Contoh: event tetap bernama `DNS_DEGRADED`, lalu detail apakah masalah terjadi pada internal, external, atau semua target disimpan di `affected_scope`.

---

## 3. Metrik Umum

Tabel berikut merangkum metrik yang digunakan lintas skema.

| Metrik                         | Arti                                              | Sumber Umum                                         |
| ------------------------------ | ------------------------------------------------- | --------------------------------------------------- |
| `wifi_up` / `wifi_connected`   | Status apakah interface/link Wi-Fi terlihat aktif | `fast_probe.py`, `telemetry_probe.py`               |
| `wifi_rssi_dbm`                | Kekuatan sinyal Wi-Fi                             | `telemetry_probe.py`, konteks `throughput_probe.py` |
| `wifi_bssid`                   | BSSID access point                                | `telemetry_probe.py`, konteks `throughput_probe.py` |
| `ping.success`                 | Status keberhasilan ICMP reachability test        | `fast_probe.py`                                     |
| `ping.rtt_ms`                  | RTT ping satu paket pada fast probe               | `fast_probe.py`                                     |
| `rtt_avg_ms`                   | Rata-rata RTT dari multi-packet ping telemetry    | `telemetry_probe.py`                                |
| `loss_pct`                     | Persentase packet loss dari telemetry ping        | `telemetry_probe.py`                                |
| `dns_success`                  | Status keberhasilan resolusi DNS                  | `fast_probe.py`, `telemetry_probe.py`               |
| `dns_latency_ms`               | Latensi resolusi DNS                              | `fast_probe.py`, `telemetry_probe.py`               |
| `http_dns_ms`                  | Durasi fase DNS pada HTTP/curl check              | `telemetry_probe.py`                                |
| `http_connect_ms`              | Waktu TCP connect pada HTTP/curl check            | `telemetry_probe.py`                                |
| `http_tls_ms`                  | Waktu TLS handshake pada HTTP/curl check          | `telemetry_probe.py`                                |
| `http_ttfb_ms`                 | Time to First Byte                                | `telemetry_probe.py`                                |
| `http_total_ms`                | Total durasi transaksi HTTP                       | `telemetry_probe.py`                                |
| `throughput_total_mbps`        | Throughput download end-to-end                    | `throughput_probe.py`                               |
| `upload_throughput_total_mbps` | Throughput upload end-to-end                      | `throughput_probe.py`                               |

---

# S1 — DNS_DEGRADED

## Description

`DNS_DEGRADED` adalah kondisi ketika resolusi DNS masih berhasil, tetapi latensinya meningkat secara abnormal dibanding baseline normal atau threshold yang dikonfigurasi. Event ini bukan DNS outage penuh. Ciri utamanya adalah **DNS berhasil, tetapi lambat**.

Skema ini digunakan untuk mengevaluasi apakah Micro-UXI dapat mendeteksi degradasi resolusi nama sebelum berubah menjadi timeout total atau gangguan konektivitas yang lebih luas.

## Fault Injection Method

Fault injection dilakukan dengan menambahkan delay buatan pada trafik DNS.

Contoh parameter:

```yaml
scenario_id: S1_DNS_DEGRADED
fault_type: dns_delay
target_scope: internal | external | all
injected_delay_ms: 200-800
duration_sec: 30-120
```

Pendekatan implementasi yang mungkin:

* Menambahkan delay pada trafik UDP/TCP port 53 menggunakan traffic control di laptop/router fault injection.
* Menambahkan delay hanya untuk domain tertentu.
* Memisahkan pengujian domain internal dan external untuk memvalidasi klasifikasi `affected_scope`.

## User Impact

Pengguna masih terlihat tersambung ke Wi-Fi dan internet, tetapi proses membuka website atau aplikasi terasa lambat karena hostname membutuhkan waktu lebih lama untuk di-resolve sebelum koneksi HTTP dimulai.

Gejala yang dirasakan:

* Load awal halaman terasa lambat.
* Aplikasi yang sering melakukan DNS lookup terasa lambat.
* Koneksi yang sudah terbentuk sebelumnya mungkin tetap normal.

## Expected Observable Symptoms

Pola telemetri yang diharapkan:

* `wifi_up == true`
* `ping.success == true`
* `dns_success == true`
* `dns_latency_ms` meningkat di atas threshold atau deviasi baseline
* `http_total_ms` dapat ikut naik jika HTTP check melibatkan DNS resolution

## Trigger Logic

### Primary Metrics

| Metrik           | Kondisi                                                      | Sumber                                |
| ---------------- | ------------------------------------------------------------ | ------------------------------------- |
| `dns_latency_ms` | `>= dns_latency_threshold_ms` atau melebihi deviasi baseline | `fast_probe.py`, `telemetry_probe.py` |
| `dns_success`    | `true`                                                       | `fast_probe.py`, `telemetry_probe.py` |

### Supporting Metrics

| Metrik           | Fungsi                                                | Sumber                 |
| ---------------- | ----------------------------------------------------- | ---------------------- |
| `wifi_up`        | Memastikan event bukan karena Wi-Fi disconnect        | `fast_probe.py`        |
| `ping.success`   | Memastikan konektivitas IP masih hidup                | `fast_probe.py`        |
| `affected_scope` | Membedakan degradasi DNS internal, external, atau all | konfigurasi target DNS |

### Recommended Rule

```text
Trigger DNS_DEGRADED jika:
  wifi_up == true
  ping.success == true
  dns_success_ratio(scope) >= minimum_success_ratio
  max_dns_latency_ms(scope) >= dns_latency_threshold_ms
  kondisi terjadi selama N sampel berturut-turut
```

Contoh threshold awal:

```yaml
dns_latency_threshold_ms: 300
confirm_consecutive: 2
minimum_success_ratio: 1.0
```

### Baseline-Aware Rule

```text
Trigger DNS_DEGRADED jika:
  dns_success == true
  dns_latency_ms >= rolling_median_dns_latency + k * MAD_dns_latency
  kondisi terjadi selama N sampel berturut-turut
```

## Recovery Logic

```text
Recover jika:
  dns_success_ratio(scope) >= minimum_success_ratio
  max_dns_latency_ms(scope) < dns_latency_threshold_ms
  kondisi stabil selama K detik atau K sampel
```

## Evidence to Record

* Sampel DNS pada pre-event, event, dan post-event window.
* Klasifikasi target internal/external.
* Resolver yang digunakan.
* Snapshot Wi-Fi: SSID, BSSID, RSSI, bitrate, frequency.
* Snapshot network: IP, gateway, resolver DNS.
* Snapshot HTTP timing jika HTTP latency ikut meningkat.

## Ground Truth Fields

```yaml
scenario_id: S1_DNS_DEGRADED
fault_start_ts: ...
fault_end_ts: ...
target_scope: internal | external | all
target_domains: [...]
injected_delay_ms: ...
dns_protocol: udp | tcp | both
```

## Notes / Caveats

* DNS lambat dapat disebabkan oleh resolver overload, forwarding delay, wireless delay, atau upstream delay.
* Jika DNS gagal total, event lebih tepat diklasifikasikan sebagai S2.
* Jika ping ikut gagal, event lebih tepat diarahkan ke connectivity atau packet-loss-related event.

---

# S2 — DNS_TIMEOUT_BURST

## Description

`DNS_TIMEOUT_BURST` adalah kondisi ketika query DNS gagal atau timeout secara beruntun dalam jendela waktu pendek. Berbeda dengan `DNS_DEGRADED`, skema ini merepresentasikan kegagalan resolusi DNS, bukan DNS yang masih berhasil tetapi lambat.

Event ini dianggap DNS-specific apabila konektivitas IP masih tersedia, tetapi resolusi DNS gagal.

## Fault Injection Method

Fault injection dilakukan dengan membuat query DNS drop atau timeout.

Contoh parameter:

```yaml
scenario_id: S2_DNS_TIMEOUT_BURST
fault_type: dns_timeout_burst
target_scope: internal | external | all
burst_duration_sec: 5-10
repeat_count: 3
recovery_gap_sec: 5
```

Pendekatan implementasi yang mungkin:

* Drop trafik UDP/TCP port 53.
* Drop DNS hanya untuk domain atau resolver tertentu.
* Drop DNS internal dan external secara terpisah untuk menguji klasifikasi scope.

## User Impact

Pengguna masih dapat tersambung ke Wi-Fi dan beberapa koneksi IP yang sudah aktif mungkin tetap berjalan, tetapi layanan baru gagal dibuka karena hostname tidak dapat di-resolve.

Gejala yang dirasakan:

* Browser menampilkan DNS error.
* Aplikasi gagal memulai sesi baru.
* Layanan yang sudah terbuka mungkin masih berjalan sementara karena cache DNS atau koneksi lama.

## Expected Observable Symptoms

Pola telemetri yang diharapkan:

* `wifi_up == true`
* `ping.success == true`
* `dns_success == false` pada scope yang terdampak
* `dns_latency_ms` dapat mendekati durasi timeout
* HTTP check dapat gagal lebih awal karena gagal DNS resolution

## Trigger Logic

### Primary Metrics

| Metrik           | Kondisi                           | Sumber                                |
| ---------------- | --------------------------------- | ------------------------------------- |
| `dns_success`    | `false` pada scope yang terdampak | `fast_probe.py`, `telemetry_probe.py` |
| `dns_fail_ratio` | `>= dns_fail_ratio_threshold`     | turunan dari sampel DNS               |

### Supporting Metrics

| Metrik           | Fungsi                                             | Sumber                 |
| ---------------- | -------------------------------------------------- | ---------------------- |
| `wifi_up`        | Memastikan Wi-Fi tidak down                        | `fast_probe.py`        |
| `ping.success`   | Memastikan konektivitas IP masih hidup             | `fast_probe.py`        |
| `affected_scope` | Memisahkan DNS outage internal, external, atau all | konfigurasi target DNS |

### Recommended Rule

```text
Trigger DNS_TIMEOUT_BURST jika:
  wifi_up == true
  ping.success == true
  dns_fail_ratio(scope) >= dns_fail_ratio_threshold
  kondisi terjadi selama N sampel berturut-turut dalam burst_window_sec
```

Contoh threshold awal:

```yaml
dns_fail_ratio_threshold: 1.0
confirm_consecutive: 2
burst_window_sec: 5-10
```

### Scope Classification

```text
jika internal_dns_fail_ratio >= threshold dan external_dns_fail_ratio < threshold:
  affected_scope = internal

jika external_dns_fail_ratio >= threshold dan internal_dns_fail_ratio < threshold:
  affected_scope = external

jika internal_dns_fail_ratio >= threshold dan external_dns_fail_ratio >= threshold:
  affected_scope = all
```

## Recovery Logic

```text
Recover jika:
  dns_success_ratio(scope) >= recovery_success_ratio
  kondisi stabil selama K detik atau K sampel
```

## Evidence to Record

* Sampel DNS success/fail untuk semua scoped target.
* Resolver yang digunakan.
* Tipe error DNS jika tersedia.
* Status ping selama DNS failure.
* Snapshot Wi-Fi dan network.
* Output HTTP error jika HTTP check gagal karena DNS.

## Ground Truth Fields

```yaml
scenario_id: S2_DNS_TIMEOUT_BURST
fault_start_ts: ...
fault_end_ts: ...
target_scope: internal | external | all
target_domains: [...]
drop_ratio: 1.0
burst_duration_sec: ...
repeat_count: ...
```

## Notes / Caveats

* Probe sebaiknya membedakan timeout dari NXDOMAIN, SERVFAIL, REFUSED, dan tipe gagal DNS lain.
* Jika ping ikut gagal bersama DNS, event lebih tepat diklasifikasikan sebagai S6 atau S3 tergantung pola konektivitas.
* DNS caching dapat menyembunyikan DNS outage singkat, sehingga target uji sebaiknya meminimalkan efek cache.

---

# S3 — LOSS_BURST

## Description

`LOSS_BURST` adalah kondisi ketika packet loss meningkat tajam pada interval pendek saat Wi-Fi masih associated. Event ini merepresentasikan degradasi konektivitas yang bersifat transien, bukan disconnected state yang stabil.

## Fault Injection Method

Fault injection dilakukan dengan menambahkan packet loss pada jalur jaringan.

Contoh parameter:

```yaml
scenario_id: S3_LOSS_BURST
fault_type: packet_loss_burst
loss_pct: 5-20
burst_duration_sec: 3-10
repeat_count: 3
```

Pendekatan implementasi yang mungkin:

* Menambahkan packet loss menggunakan traffic control pada laptop/router fault injection.
* Menerapkan loss hanya pada ICMP untuk evaluasi terkontrol.
* Menerapkan loss pada semua traffic untuk menguji dampak UXI yang lebih luas.

## User Impact

Pengguna dapat mengalami kegagalan loading yang intermittent, freeze singkat, panggilan video tidak stabil, atau aplikasi melakukan retry secara acak.

Gejala yang dirasakan:

* Sebagian request berhasil, sebagian gagal.
* Kualitas video call menurun.
* Halaman web dapat load sebagian atau perlu refresh.
* Latency terasa tidak stabil.

## Expected Observable Symptoms

Pola telemetri yang diharapkan:

* `wifi_up == true`
* `ping.success` kadang gagal
* `ping_loss_pct_window` meningkat
* DNS dapat tetap sukses atau ikut gagal tergantung tingkat loss
* HTTP dapat menunjukkan timeout/retry pada loss yang lebih berat

## Trigger Logic

### Primary Metrics

| Metrik                 | Kondisi                        | Sumber                        |
| ---------------------- | ------------------------------ | ----------------------------- |
| `ping_loss_pct_window` | `>= loss_threshold_pct`        | turunan dari sampel fast ping |
| `ping.success`         | beberapa sampel bernilai false | `fast_probe.py`               |

### Supporting Metrics

| Metrik                      | Fungsi                                                    | Sumber               |
| --------------------------- | --------------------------------------------------------- | -------------------- |
| `wifi_up`                   | Memastikan link masih associated                          | `fast_probe.py`      |
| `dns_success`               | Membantu membedakan packet loss dari DNS-specific failure | `fast_probe.py`      |
| `http_total_ms` / `curl_rc` | Menunjukkan dampak ke aplikasi jika terdampak             | `telemetry_probe.py` |

### Recommended Rule

```text
Trigger LOSS_BURST jika:
  wifi_up == true
  ping_loss_pct_window >= loss_threshold_pct
  sample_count_window >= minimum_samples
  kondisi terjadi dalam burst_window_sec
```

Contoh threshold awal:

```yaml
loss_threshold_pct: 20
window_sec: 10
minimum_samples: 5
```

## Recovery Logic

```text
Recover jika:
  ping_loss_pct_window < recovery_loss_threshold_pct
  kondisi stabil selama K detik atau K sampel
```

## Evidence to Record

* Window fast ping success/failure.
* Rasio packet loss terhitung.
* Sampel DNS pada window yang sama.
* Snapshot Wi-Fi untuk membuktikan perangkat tidak disconnect.
* HTTP timing/error jika application check terdampak.

## Ground Truth Fields

```yaml
scenario_id: S3_LOSS_BURST
fault_start_ts: ...
fault_end_ts: ...
loss_pct: ...
loss_target: icmp | dns | http | all
burst_duration_sec: ...
repeat_count: ...
```

## Notes / Caveats

* Satu ping gagal belum cukup untuk membuktikan packet loss burst. Metrik utama sebaiknya packet loss percentage dalam sliding window.
* ICMP bisa diperlakukan berbeda dari application traffic, sehingga gejala aplikasi sebaiknya tetap direkam jika memungkinkan.
* Jika DNS dan ping gagal terus-menerus, event mungkin lebih tepat diklasifikasikan sebagai S6.

---

# S4 — HIGH_RTT

## Description

`HIGH_RTT` adalah kondisi ketika round-trip time meningkat secara signifikan dibanding baseline normal atau threshold yang dikonfigurasi. Event ini merepresentasikan degradasi latency, bukan selalu packet loss atau outage.

## Fault Injection Method

Fault injection dilakukan dengan menambahkan delay pada jalur jaringan.

Contoh parameter:

```yaml
scenario_id: S4_HIGH_RTT
fault_type: rtt_increase
injected_delay_ms: 100-500
duration_sec: 60-180
target: gateway | internet | all
```

Pendekatan implementasi yang mungkin:

* Menambahkan delay menggunakan traffic control.
* Menerapkan delay pada ICMP dan application traffic.
* Menerapkan delay pada upstream path dengan packet loss rendah.

## User Impact

Pengguna dapat merasakan interaksi lambat, page load tertunda, login lambat, lag pada video call, dan response aplikasi yang terlambat meskipun konektivitas masih tersedia.

## Expected Observable Symptoms

Pola telemetri yang diharapkan:

* `rtt_avg_ms` meningkat
* `rtt_max_ms` dan `rtt_mdev_ms` dapat meningkat
* `loss_pct` tetap rendah atau sedang
* `http_ttfb_ms` atau `http_total_ms` dapat meningkat
* `dns_latency_ms` bisa meningkat atau tidak, tergantung scope injeksi

## Trigger Logic

### Primary Metrics

| Metrik       | Kondisi                                              | Sumber               |
| ------------ | ---------------------------------------------------- | -------------------- |
| `rtt_avg_ms` | `>= rtt_threshold_ms` atau melebihi deviasi baseline | `telemetry_probe.py` |
| `loss_pct`   | `< loss_threshold_pct`                               | `telemetry_probe.py` |

### Supporting Metrics

| Metrik          | Fungsi                                     | Sumber               |
| --------------- | ------------------------------------------ | -------------------- |
| `rtt_mdev_ms`   | Mengindikasikan variasi RTT/jitter         | `telemetry_probe.py` |
| `http_ttfb_ms`  | Menunjukkan dampak latency ke aplikasi     | `telemetry_probe.py` |
| `wifi_rssi_dbm` | Membantu diagnosis latency akibat RF/Wi-Fi | `telemetry_probe.py` |

### Recommended Rule

```text
Trigger HIGH_RTT jika:
  rtt_avg_ms >= rtt_threshold_ms
  loss_pct < loss_threshold_pct
  kondisi terjadi selama N telemetry samples
```

Contoh threshold awal:

```yaml
rtt_threshold_ms: 150
loss_threshold_pct: 10
confirm_consecutive: 2
```

### Baseline-Aware Rule

```text
Trigger HIGH_RTT jika:
  rtt_avg_ms >= rolling_median_rtt + k * MAD_rtt
  loss_pct < loss_threshold_pct
  kondisi terjadi selama N sampel
```

## Recovery Logic

```text
Recover jika:
  rtt_avg_ms < recovery_rtt_threshold_ms
  loss_pct < loss_threshold_pct
  kondisi stabil selama K detik atau K telemetry samples
```

## Evidence to Record

* Ping RTT min/avg/max/mdev.
* Packet loss percentage.
* HTTP timing selama latency meningkat.
* Snapshot Wi-Fi.
* Snapshot network.
* Nilai baseline jika tersedia.

## Ground Truth Fields

```yaml
scenario_id: S4_HIGH_RTT
fault_start_ts: ...
fault_end_ts: ...
injected_delay_ms: ...
delay_target: gateway | internet | all
affected_protocols: icmp | dns | http | all
```

## Notes / Caveats

* High RTT dapat disebabkan oleh sinyal Wi-Fi buruk, bufferbloat, upstream congestion, atau server-side delay.
* Jika packet loss tinggi, event lebih tepat diarahkan ke S3 atau mixed event, bukan pure HIGH_RTT.
* Pengukuran gateway RTT dan external RTT akan membantu isolasi root cause.

---

# S5 — HTTP_SLOW

## Description

`HTTP_SLOW` adalah kondisi ketika application-layer check menjadi lambat atau gagal. Event ini dideteksi melalui timing transaksi HTTP, seperti DNS lookup time, TCP connect time, TLS handshake time, Time to First Byte, dan total request time.

Skema ini berfokus pada pengalaman akses aplikasi, bukan kapasitas bandwidth mentah. Sebuah layanan dapat memiliki ping dan DNS yang terlihat normal, tetapi tetap lambat pada level HTTP/TLS/application response.

Untuk tahap awal, target HTTP yang digunakan dapat difokuskan pada layanan internal/kampus, misalnya:

```text
https://www.its.ac.id
```

Pada tahap berikutnya, target dapat diperluas ke layanan lain seperti portal akademik, classroom, Drive, YouTube, atau aplikasi SaaS lain sesuai kebutuhan pengujian.

## Fault Injection Method

Fault injection dilakukan dengan menambahkan delay, timeout, atau gangguan pada trafik HTTP/application.

Contoh parameter:

```yaml
scenario_id: S5_HTTP_SLOW
fault_type: http_slow
injected_delay_ms: 300-2000
duration_sec: 60-180
target_scope: internal | external | all
target_urls:
  - https://www.its.ac.id
```

Pendekatan implementasi yang mungkin:

* Menambahkan delay pada trafik HTTP/HTTPS ke target tertentu.
* Memperlambat response dari test web server lokal/internal.
* Menginjeksikan delay pada fase TCP/TLS/TTFB jika lingkungan uji mendukung.
* Menggunakan satu target awal, misalnya `https://www.its.ac.id`, lalu menambah target aplikasi lain pada iterasi berikutnya.

## User Impact

Pengguna mengalami page load lambat, login aplikasi tertunda, API response lambat, atau timeout aplikasi walaupun Wi-Fi, ping, dan DNS tampak normal.

Gejala yang dirasakan:

* Halaman web membutuhkan waktu lama untuk mulai tampil.
* Aplikasi terasa lambat saat membuka halaman pertama.
* Request HTTP dapat timeout.
* Layanan tertentu lambat, sementara layanan lain mungkin tetap normal.

## Expected Observable Symptoms

Pola telemetri yang diharapkan:

* `http_total_ms` meningkat
* `http_ttfb_ms` dapat meningkat jika delay terjadi pada response server/aplikasi
* `http_tls_ms` dapat meningkat jika TLS handshake terdampak
* `curl_rc != 0` atau HTTP status error jika terjadi timeout/failure
* DNS dan ping dapat tetap normal

## Trigger Logic

### Primary Metrics

| Metrik          | Kondisi                                                         | Sumber               |
| --------------- | --------------------------------------------------------------- | -------------------- |
| `http_total_ms` | `>= http_total_threshold_ms` atau melebihi deviasi baseline     | `telemetry_probe.py` |
| `http_ttfb_ms`  | `>= http_ttfb_threshold_ms` atau melebihi deviasi baseline      | `telemetry_probe.py` |
| `curl_rc`       | non-zero menandakan HTTP check gagal                            | `telemetry_probe.py` |
| `http_status`   | di luar range expected 2xx/3xx menandakan problem aplikasi/HTTP | `telemetry_probe.py` |

### Supporting Metrics

| Metrik                           | Fungsi                                               | Sumber                                |
| -------------------------------- | ---------------------------------------------------- | ------------------------------------- |
| `dns_success` / `dns_latency_ms` | Membedakan HTTP slow dari DNS slow                   | `fast_probe.py`, `telemetry_probe.py` |
| `rtt_avg_ms`                     | Membedakan HTTP slow dari latency umum               | `telemetry_probe.py`                  |
| `loss_pct`                       | Membedakan HTTP slow dari packet loss                | `telemetry_probe.py`                  |
| `affected_scope`                 | Membedakan internal vs external application slowness | konfigurasi target HTTP               |

### Recommended Rule

```text
Trigger HTTP_SLOW jika:
  wifi_connected == true
  DNS tidak gagal secara global
  dan salah satu kondisi berikut terpenuhi:
    http_total_ms(scope) >= http_total_threshold_ms
    http_ttfb_ms(scope) >= http_ttfb_threshold_ms
    curl_rc != 0
    http_status di luar expected range
  kondisi terjadi selama N telemetry samples
```

Contoh threshold awal:

```yaml
http_total_threshold_ms: 2000
http_ttfb_threshold_ms: 1000
confirm_consecutive: 2
```

### Baseline-Aware Rule

```text
Trigger HTTP_SLOW jika:
  http_total_ms >= rolling_median_http_total + k * MAD_http_total
  atau http_ttfb_ms >= rolling_median_ttfb + k * MAD_ttfb
```

## Recovery Logic

```text
Recover jika:
  HTTP check kembali menghasilkan expected status
  http_total_ms < recovery_http_total_threshold_ms
  kondisi stabil selama K detik atau K telemetry samples
```

## Evidence to Record

* HTTP timing breakdown.
* Curl return code dan stderr.
* HTTP status code.
* DNS timing untuk target yang sama.
* Ping RTT/loss di sekitar event.
* Snapshot Wi-Fi dan network.
* Scope target internal/external.
* URL target yang diuji, misalnya `https://www.its.ac.id`.

## Ground Truth Fields

```yaml
scenario_id: S5_HTTP_SLOW
fault_start_ts: ...
fault_end_ts: ...
target_scope: internal | external | all
target_urls:
  - https://www.its.ac.id
injected_delay_ms: ...
timeout_sec: ...
affected_phase: dns | tcp | tls | ttfb | total | unknown
```

## Notes / Caveats

* HTTP slow dapat disebabkan oleh DNS, TCP, TLS, delay server, packet loss, atau bandwidth constraint. Timing breakdown diperlukan untuk mengetahui fase dominan.
* Event ini tidak sama dengan throughput/bandwidth throttle. HTTP slow fokus pada waktu transaksi aplikasi, sedangkan bandwidth throttle fokus pada kapasitas transfer data.
* Pada tahap awal, satu target seperti `https://www.its.ac.id` cukup untuk validasi. Target aplikasi tambahan dapat dimasukkan pada iterasi berikutnya.

---

# S6 — CONNECTIVITY_FLAP

## Description

`CONNECTIVITY_FLAP` adalah kondisi ketika konektivitas berubah berulang antara reachable dan unreachable dalam jendela waktu pendek. Event ini tidak terbatas pada Wi-Fi disconnection. Wi-Fi link flap hanya salah satu kemungkinan penyebab; upstream connectivity flap juga dapat terjadi ketika Wi-Fi masih associated.

Ciri utama event ini adalah **state transition berulang**, bukan hanya satu sampel gagal.

## Fault Injection Method

Fault injection dilakukan dengan memutus dan memulihkan konektivitas secara berulang.

Contoh parameter:

```yaml
scenario_id: S6_CONNECTIVITY_FLAP
fault_type: connectivity_flap
down_duration_sec: 2-10
up_duration_sec: 2-10
repeat_count: 3-5
affected_layer: wifi | gateway | upstream | dns | all
```

Pendekatan implementasi yang mungkin:

* Memblokir seluruh outbound traffic secara berulang.
* Memutus gateway reachability secara sementara.
* Disable dan enable Wi-Fi association untuk Wi-Fi-specific flap.
* Drop DNS dan ping bersama-sama saat Wi-Fi tetap associated untuk meniru upstream flap.

## User Impact

Pengguna mengalami disconnect intermittent, aplikasi berulang kali reconnect, call drop/freeze, dan sesi web/app gagal secara tidak stabil.

## Expected Observable Symptoms

Pola telemetri yang diharapkan:

* `connectivity_ok` berubah `true -> false -> true` secara berulang
* `ping.success` dapat bergantian sukses/gagal
* `dns_success` dapat bergantian sukses/gagal
* `wifi_up` dapat tetap true pada upstream flap
* `wifi_up` dapat berubah true/false pada Wi-Fi link flap
* HTTP check dapat bergantian sukses/gagal

## Trigger Logic

### Primary Metrics

| Metrik            | Kondisi                                 | Sumber                       |
| ----------------- | --------------------------------------- | ---------------------------- |
| `connectivity_ok` | terjadi state transition berulang       | turunan dari `fast_probe.py` |
| `ping.success`    | dapat bergantian true/false             | `fast_probe.py`              |
| `dns_success`     | dapat bergantian true/false             | `fast_probe.py`              |
| `wifi_up`         | membedakan Wi-Fi flap dan upstream flap | `fast_probe.py`              |

### Supporting Metrics

| Metrik                    | Fungsi                                           | Sumber               |
| ------------------------- | ------------------------------------------------ | -------------------- |
| `wifi_bssid`              | Mendeteksi roaming/reassociation AP              | `telemetry_probe.py` |
| `wifi_rssi_dbm`           | Membantu identifikasi instabilitas RF/Wi-Fi      | `telemetry_probe.py` |
| `http_status` / `curl_rc` | Mengonfirmasi dampak ke application reachability | `telemetry_probe.py` |

### Recommended Rule

```text
Trigger CONNECTIVITY_FLAP jika:
  state_transition_count(connectivity_ok) >= flap_transition_threshold
  dalam flap_window_sec
```

Contoh threshold awal:

```yaml
flap_transition_threshold: 2
flap_window_sec: 30
confirm_consecutive: 1
```

### Suspected Layer Classification

```text
jika wifi_up bergantian true/false:
  suspected_layer = wifi_link

jika wifi_up tetap true tetapi ping dan DNS bergantian fail/success:
  suspected_layer = upstream

jika ping tetap OK tetapi DNS bergantian fail/success:
  suspected_layer = dns

jika ping dan DNS tetap OK tetapi HTTP bergantian fail/success:
  suspected_layer = application
```

## Recovery Logic

```text
Recover jika:
  connectivity_ok == true
  tidak ada state transition tambahan selama K detik
```

## Evidence to Record

* Urutan state connectivity dari fast probe.
* Timeline ping success/failure.
* Timeline DNS success/failure.
* Timeline Wi-Fi link state.
* Snapshot BSSID/RSSI jika Wi-Fi dicurigai.
* HTTP success/failure jika application reachability terdampak.

## Ground Truth Fields

```yaml
scenario_id: S6_CONNECTIVITY_FLAP
fault_start_ts: ...
fault_end_ts: ...
down_duration_sec: ...
up_duration_sec: ...
repeat_count: ...
affected_layer: wifi | gateway | upstream | dns | all
```

## Notes / Caveats

* Satu kali outage belum tentu flap. Flap membutuhkan transisi berulang.
* Wi-Fi disconnection dan upstream outage tetap direpresentasikan sebagai satu event type yang sama, tetapi dibedakan melalui `suspected_layer`.
* Jika seluruh sampel tetap gagal tanpa recovery, event lebih tepat dikategorikan sebagai sustained outage, bukan flap.

---

# Additional Events

Bagian ini berisi event tambahan yang bukan bagian utama S1–S6, tetapi berguna untuk eksperimen lanjutan atau perluasan evaluasi.

---

# A1 — BANDWIDTH_THROTTLE / THROUGHPUT_DEGRADED

## Description

`BANDWIDTH_THROTTLE` atau `THROUGHPUT_DEGRADED` adalah kondisi ketika throughput download atau upload turun di bawah threshold atau baseline yang diharapkan. Event ini dideteksi menggunakan active throughput testing.

Event ini berbeda dari `HTTP_SLOW`. `HTTP_SLOW` mengukur waktu transaksi aplikasi/HTTP, sedangkan `BANDWIDTH_THROTTLE` mengukur kapasitas transfer data.

## Fault Injection Method

Fault injection dilakukan dengan membatasi bandwidth.

Contoh parameter:

```yaml
scenario_id: A1_BANDWIDTH_THROTTLE
fault_type: bandwidth_throttle
download_limit_mbps: 1-5
upload_limit_mbps: 1-5
duration_sec: 60-180
target: cloudflare | internal_server | iperf_server
```

Pendekatan implementasi yang mungkin:

* Membatasi bandwidth download dan/atau upload menggunakan traffic control.
* Mengarahkan throughput test ke Cloudflare untuk external throughput.
* Mengarahkan throughput test ke server internal jika ingin membandingkan internal vs external throughput.

## User Impact

Pengguna mengalami download lambat, upload lambat, sinkronisasi file lambat, kualitas video menurun, dan performa SaaS yang terasa berat.

## Expected Observable Symptoms

Pola telemetri yang diharapkan:

* `throughput_total_mbps` turun di bawah threshold pada download test
* `upload_throughput_total_mbps` turun di bawah threshold pada upload test
* `run_health.failed_runs` dapat meningkat jika transfer gagal
* `http_total_ms` dapat meningkat jika bandwidth throttle cukup berat

## Trigger Logic

### Primary Metrics

| Metrik                                            | Kondisi                     | Sumber                |
| ------------------------------------------------- | --------------------------- | --------------------- |
| `summary.download.throughput_total_mbps.avg`      | `< download_threshold_mbps` | `throughput_probe.py` |
| `summary.upload.upload_throughput_total_mbps.avg` | `< upload_threshold_mbps`   | `throughput_probe.py` |
| `summary.download.run_health`                     | semua/ sebagian run gagal   | `throughput_probe.py` |
| `summary.upload.run_health`                       | semua/ sebagian run gagal   | `throughput_probe.py` |

### Recommended Rule

```text
Trigger BANDWIDTH_THROTTLE jika:
  download_throughput_total_mbps < download_threshold_mbps
  atau upload_throughput_total_mbps < upload_threshold_mbps
  atau semua throughput run gagal
  kondisi terjadi selama N throughput samples
```

Contoh threshold awal:

```yaml
throughput_download_threshold_mbps: 3
throughput_upload_threshold_mbps: 3
confirm_consecutive: 1
```

## Recovery Logic

```text
Recover jika:
  download_throughput_total_mbps >= recovery_download_threshold_mbps
  upload_throughput_total_mbps >= recovery_upload_threshold_mbps
  run_health menunjukkan transfer berhasil
  kondisi stabil selama K samples
```

## Evidence to Record

* Throughput measurement runs.
* Summary download dan upload.
* Run health download dan upload.
* Target throughput test.
* Snapshot Wi-Fi dan network.

## Ground Truth Fields

```yaml
scenario_id: A1_BANDWIDTH_THROTTLE
fault_start_ts: ...
fault_end_ts: ...
download_limit_mbps: ...
upload_limit_mbps: ...
target: cloudflare | internal_server | iperf_server
```

## Notes / Caveats

* Jika throughput target adalah Cloudflare, `affected_scope` secara praktis adalah `external`.
* Perbandingan internal/external throughput baru bermakna jika tersedia endpoint throughput internal dan external.
* Event ini sebaiknya tetap berada di bagian Additional Events agar S5 utama tetap fokus pada `HTTP_SLOW` sesuai definisi application-layer degradation.

---

# 4. Konfigurasi Threshold Awal

Threshold awal berikut hanya baseline awal dan perlu dituning berdasarkan hasil eksperimen.

```yaml
thresholds:
  dns_latency_threshold_ms: 300
  dns_fail_ratio_threshold: 1.0
  dns_recovery_success_ratio: 1.0

  loss_threshold_pct: 20
  loss_window_sec: 10

  rtt_threshold_ms: 150
  rtt_loss_upper_bound_pct: 10

  http_total_threshold_ms: 2000
  http_ttfb_threshold_ms: 1000

  throughput_download_threshold_mbps: 3
  throughput_upload_threshold_mbps: 3

  flap_transition_threshold: 2
  flap_window_sec: 30

  confirm_consecutive: 2
  recovery_consecutive: 2
```

---

# 5. Checklist Minimal Evidence Bundle

Setiap event yang terdeteksi minimal menghasilkan struktur berikut.

```text
[event_id]/
  event_meta.json
  ground_truth_ref.json
  pre_window.jsonl atau pre_window.csv
  event_window.jsonl atau event_window.csv
  post_window.jsonl atau post_window.csv
  net_snapshot.txt
  wifi_snapshot.txt
  probe_config.json
```

Untuk event DNS, tambahkan:

```text
  dns_samples.jsonl
```

Untuk event HTTP, tambahkan:

```text
  http_timing_samples.jsonl
```

Untuk event throughput, tambahkan:

```text
  throughput_samples.jsonl
```

---

# 6. Ground Truth Alignment

Event terdeteksi dianggap cocok dengan fault injection jika:

```text
event_type sesuai dengan expected scenario type
and event.ts_start berada dalam [fault_start_ts - delta, fault_end_ts + delta]
```

Toleransi awal yang disarankan:

```yaml
alignment_delta_sec: 2-5
```

Jika beberapa event cocok dengan satu fault, gunakan salah satu strategi yang ditetapkan sejak awal:

* `first-match`: menggunakan event valid pertama.
* `best-overlap`: menggunakan event dengan overlap waktu terbesar.

Strategi yang dipilih harus konsisten untuk seluruh eksperimen.

---

<!-- # 7. Catatan Desain

* S1–S6 dipertahankan sebagai skema utama sesuai definisi event pada proposal.
* S5 ditetapkan sebagai `HTTP_SLOW`, yaitu degradasi application-layer berdasarkan timing HTTP.
* `BANDWIDTH_THROTTLE` tidak digabung ke S5, melainkan ditempatkan sebagai Additional Event `A1`.
* Untuk tahap awal, target HTTP S5 dapat menggunakan `https://www.its.ac.id`. Target tambahan dapat dimasukkan pada iterasi berikutnya.
* Jika implementasi baseline-aware belum tersedia, threshold statis dapat digunakan sebagai baseline pembanding sementara. Versi lanjutan sebaiknya memakai rolling median/MAD atau EWMA. -->
