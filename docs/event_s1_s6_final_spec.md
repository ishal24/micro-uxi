# README Skema Fault Injection Micro-UXI — S1 sampai S6

Dokumen ini mendefinisikan skema fault injection dan trigger event untuk enam event utama Micro-UXI:

1. S1 — `DNS_DEGRADED`
2. S2 — `DNS_TIMEOUT_BURST`
3. S3 — `LOSS_BURST`
4. S4 — `HIGH_RTT`
5. S5 — `HTTP_SLOW`
6. S6 — `CONNECTIVITY_FLAP`

Dokumen ini ditulis sebagai **spesifikasi trigger yang implementable**. Artinya, setiap parameter yang masuk ke trigger harus jelas nilainya, sumber datanya, dan fungsinya. Tidak ada istilah ambigu seperti “dipantau” di dalam trigger. Jika sebuah metrik hanya direkam untuk investigasi, metrik tersebut dimasukkan ke bagian **Evidence**, bukan **Trigger Logic**.

---

## 0. Definisi Istilah

### 0.1 Primary Trigger

Primary trigger adalah kondisi utama yang membuat event dinyatakan terjadi. Primary trigger harus berupa kondisi yang dapat langsung diimplementasikan di kode.

Contoh:

```text
dns_latency_ms >= T_dns_latency
ping_loss_pct_window >= T_loss
state_transition_count(connectivity_ok) >= T_transition
```

### 0.2 Guard Condition

Guard condition adalah kondisi yang harus benar agar event tidak salah klasifikasi. Jika guard condition tidak terpenuhi, event tidak boleh dipicu.

Contoh:

```text
wifi_up == true
ping.success == true
dns_success == true
```

### 0.3 Exclusion Condition

Exclusion condition adalah kondisi yang digunakan untuk mencegah satu event diklasifikasikan sebagai event lain.

Contoh pada `HTTP_SLOW`:

```text
dns_latency_ms < T_dns_latency
rtt_avg_ms < T_rtt
loss_pct < T_loss_guard
```

Jika DNS lambat, RTT tinggi, atau packet loss tinggi, maka HTTP lambat kemungkinan hanya dampak dari event jaringan lain. Dalam kondisi tersebut, event sebaiknya diarahkan ke S1, S3, atau S4, bukan S5.

### 0.4 Classification Output

Classification output adalah metadata hasil klasifikasi, bukan kondisi trigger.

Contoh:

```text
affected_scope = internal | external | all | unknown
suspected_layer = wifi_link | upstream | dns | application | unknown
```

Field seperti `affected_scope` dan `suspected_layer` tidak memicu event secara langsung. Field ini diisi setelah trigger terpenuhi.

### 0.5 Evidence-only Field

Evidence-only field adalah metrik yang direkam untuk analisis pasca-event, tetapi tidak menentukan apakah event aktif atau tidak.

Contoh:

```text
wifi_rssi_dbm
wifi_bssid
wifi_bitrate_mbps
gateway_ip
dns_resolvers
curl_stderr
```

Field tersebut berguna untuk investigasi, tetapi tidak boleh ditulis sebagai trigger kecuali memang ada aturan eksplisitnya.

---

## 1. Prinsip Umum Threshold dan Kalibrasi

### 1.1 Baseline Phase

Sebelum fault injection dijalankan, sistem harus menjalankan baseline phase pada kondisi jaringan normal. Baseline phase digunakan untuk mendapatkan distribusi normal metrik jaringan.

Baseline phase harus memenuhi syarat berikut:

```text
Tidak ada fault injection aktif.
SSID, AP, channel, resolver DNS, dan target uji dijaga tetap.
Probe berjalan dengan interval sampling yang sama seperti saat eksperimen.
Data yang gagal karena masalah alat ukur atau proses probe tidak valid harus dikeluarkan dari perhitungan threshold.
```

Untuk threshold berbasis P99, target jumlah data adalah:

```text
Minimal valid sample per metrik/per target = 10.000
```

Jika 10.000 valid sample tidak tercapai, minimal 1.000 valid sample dapat digunakan sebagai baseline awal, tetapi hasil threshold harus diperlakukan sebagai threshold preliminary dan perlu divalidasi ulang.

### 1.2 Threshold P99

Untuk baseline monitoring statis, threshold numerik dihitung menggunakan P99 dari data normal.

Bentuk umum:

```text
T_metric = P99(metric_normal)
```

Interpretasinya:

```text
Jika T_metric = P99(metric_normal), maka sekitar 99% data normal berada di bawah atau sama dengan T_metric.
Nilai di atas T_metric dianggap abnormal terhadap kondisi normal jaringan uji.
```

Threshold tidak diambil dari angka universal. Contoh `dns_latency_ms = 300 ms` hanya valid jika hasil baseline phase menunjukkan:

```text
T_dns_latency = P99(dns_latency_ms normal) = 300 ms
```

### 1.3 Confirm Consecutive

`confirm_consecutive` adalah jumlah sampel berturut-turut yang harus memenuhi kondisi trigger sebelum event benar-benar dinyatakan aktif.

Bentuk umum:

```text
confirm_consecutive == N_event
```

Nilai `N_event` tidak ditetapkan manual. Nilai ini ditentukan melalui uji kandidat:

```text
N_event ∈ {1, 2, 3, 4}
```

Prosedur penentuannya:

```text
1. Jalankan detector pada data normal tanpa fault.
2. Hitung FAR (False Alarm Rate) untuk setiap kandidat N.
3. Jalankan detector pada data fault injection.
4. Hitung MTTD (Mean Time To Detect), recall, dan missed event untuk setiap kandidat N.
5. Pilih nilai N terkecil yang menghasilkan FAR rendah dan MTTD tetap rendah.
```

Catatan:

```text
Semakin kecil N, deteksi lebih cepat tetapi false alarm bisa meningkat.
Semakin besar N, false alarm menurun tetapi MTTD meningkat.
```

### 1.4 Sliding Window

Sliding window digunakan untuk metrik yang tidak cukup dinilai dari satu sampel, seperti failure ratio, packet loss ratio, dan transition count.

Sliding window berarti sistem mengambil kumpulan sampel terbaru, menghitung metrik agregat dari kumpulan tersebut, lalu menggeser window setiap kali sampel baru masuk.

Contoh sample-based window:

```text
n = 10 sampel
sampling_interval = 1 detik

t=10 -> window berisi sampel t=1 sampai t=10
t=11 -> window berisi sampel t=2 sampai t=11
t=12 -> window berisi sampel t=3 sampai t=12
```

Hubungan antara jumlah sampel dan durasi window:

```text
W = n × sampling_interval
```

Jika sampling interval tidak stabil, gunakan time-based window:

```text
window = semua sampel dengan timestamp >= current_time - W
```

### 1.5 Minimum Sample dalam Window

Untuk failure ratio seperti DNS failure:

```text
n_dns >= 10
```

Alasannya:

```text
Jika n = 10, 1 failure = 10%.
Jika n = 20, 1 failure = 5%.
```

Untuk packet loss:

```text
n_ping >= 20
```

Alasannya:

```text
Jika n = 20, 1 ping gagal = 5%.
Resolusi 5% lebih layak untuk membedakan loss 5%, 10%, 15%, dan 20%.
```

Untuk connectivity flap:

```text
n_flap ditentukan dari W_flap dan sampling_interval_fast.
```

Agar state transition terlihat dengan cukup jelas:

```text
sampling_interval_fast sebaiknya 1–2 detik.
```

Jika sampling interval 5 detik, window 30 detik hanya berisi sekitar 6 sampel. Itu terlalu kasar untuk event flap yang down/up-nya pendek.

---

## 2. Event Priority dan Overlap

Beberapa event dapat menyebabkan gejala di event lain. Untuk mengurangi salah klasifikasi, digunakan aturan prioritas berikut.

```text
S6 CONNECTIVITY_FLAP memiliki prioritas lebih tinggi daripada S3 LOSS_BURST.
Jika CONNECTIVITY_FLAP aktif, LOSS_BURST boleh disuppress agar satu flap tidak dihitung sebagai loss burst.

S2 DNS_TIMEOUT_BURST memiliki prioritas lebih tinggi daripada S5 HTTP_SLOW untuk curl error yang disebabkan DNS.
Jika curl_rc menunjukkan DNS resolve failure, event tidak diklasifikasikan sebagai HTTP_SLOW.

S1 DNS_DEGRADED memiliki prioritas lebih tinggi daripada S5 HTTP_SLOW jika HTTP lambat terjadi bersamaan dengan DNS latency tinggi.
Jika DNS latency sudah melewati threshold, HTTP slow dianggap dampak DNS, bukan pure HTTP_SLOW.

S3 LOSS_BURST memiliki prioritas lebih tinggi daripada S4 HIGH_RTT dan S5 HTTP_SLOW jika packet loss tinggi.
Jika loss tinggi, RTT dan HTTP timing dapat ikut memburuk sebagai dampak loss.

S4 HIGH_RTT memiliki prioritas lebih tinggi daripada S5 HTTP_SLOW jika RTT umum tinggi.
Jika RTT tinggi, HTTP slow dapat menjadi dampak general latency.
```

---

# S1 - DNS_DEGRADED

## Description

`DNS_DEGRADED` adalah kondisi ketika resolusi DNS masih berhasil, tetapi waktu resolusinya meningkat secara abnormal dibanding kondisi normal jaringan. Event ini bukan DNS outage penuh. Ciri utamanya adalah DNS query tetap sukses, tetapi lambat.

Event ini digunakan untuk mendeteksi degradasi pada proses resolusi nama. Karena DNS adalah tahap awal dalam banyak transaksi aplikasi berbasis domain, DNS yang lambat dapat membuat aplikasi atau website terasa lambat walaupun konektivitas IP masih tersedia.

## User Impact

Dari sisi user, koneksi terlihat masih normal: Wi-Fi aktif, ping masih bisa sukses, dan internet tidak sepenuhnya mati. Namun, proses membuka website atau aplikasi terasa lambat, terutama pada fase awal akses. Pengguna dapat merasakan halaman web lama mulai terbuka, aplikasi lambat saat login, atau layanan yang sering melakukan DNS lookup terasa tidak responsif.

Koneksi yang sudah terbentuk sebelumnya bisa tetap berjalan normal karena tidak selalu membutuhkan DNS lookup baru.

## Data Source

Event ini menggunakan data dari fast probe DNS.

Field yang digunakan:

```text
wifi.wifi_up
ping.success
dns[].success
dns[].latency_ms
dns[].scope
dns[].target
```

## Trigger Logic

### Primary Trigger

```text
Trigger DNS_DEGRADED jika:
  wifi.wifi_up == true
  ping.success == true
  dns_success_ratio(scope) >= S_min
  max_dns_latency_ms(scope) >= T_dns_latency(scope)
  confirm_consecutive == N_dns
```

### Parameter

#### `wifi.wifi_up == true`

Field ini adalah guard condition. Event `DNS_DEGRADED` hanya boleh terjadi jika interface Wi-Fi aktif. Jika Wi-Fi tidak aktif, maka masalah bukan DNS degraded.

#### `ping.success == true`

Field ini adalah guard condition. Event `DNS_DEGRADED` hanya boleh terjadi jika IP reachability masih hidup. Jika ping gagal, maka masalah lebih mungkin berasal dari packet loss, upstream outage, atau connectivity flap.

#### `dns_success_ratio(scope) >= S_min`

`dns_success_ratio(scope)` dihitung sebagai:

```text
dns_success_ratio(scope) = successful_dns_queries(scope) / total_dns_queries(scope)
```

Untuk taxonomy yang strict:

```text
S_min = 1.0
```

Alasannya:

```text
S1 didefinisikan sebagai DNS lambat tetapi tetap berhasil.
Jika DNS gagal atau timeout, event harus diarahkan ke S2.
```

Jika pada baseline normal terdapat failure DNS sporadis, nilai `S_min` boleh diturunkan, tetapi harus ditentukan dari baseline normal dan dicatat sebagai parameter eksperimen.

#### `max_dns_latency_ms(scope)`

Jika dalam satu scope terdapat lebih dari satu DNS target, gunakan latency terbesar dari DNS query yang berhasil:

```text
max_dns_latency_ms(scope) = max(dns[].latency_ms untuk dns.success == true pada scope tersebut)
```

Alasannya:

```text
Satu target DNS yang lambat dalam scope tersebut sudah cukup menunjukkan degradasi pengalaman untuk scope itu.
```

#### `T_dns_latency(scope)`

Threshold DNS latency dihitung dari baseline phase.

Bentuk:

```text
T_dns_latency(scope) = P99(max_dns_latency_ms(scope) normal | dns_success_ratio(scope) >= S_min)
```

Catatan:

```text
Threshold dihitung per scope, bukan satu angka global, karena target internal dan eksternal dapat memiliki karakteristik DNS normal yang berbeda.
```

#### `N_dns`

`N_dns` adalah jumlah sampel berturut-turut yang harus memenuhi primary trigger.

Nilai final ditentukan melalui sweep:

```text
N_dns ∈ {1, 2, 3, 4}
```

Pemilihan:

```text
FAR dihitung dari baseline normal tanpa fault.
MTTD dan recall dihitung dari fault injection S1.
Pilih N_dns terkecil yang menghasilkan FAR rendah dan MTTD rendah.
```

## Recovery Logic

```text
Recover DNS_DEGRADED jika:
  wifi.wifi_up == true
  ping.success == true
  dns_success_ratio(scope) >= S_min
  max_dns_latency_ms(scope) < T_dns_latency_recovery(scope)
  recovery_consecutive == R_dns
```

`T_dns_latency_recovery` dapat memakai threshold recovery yang lebih rendah daripada trigger threshold untuk mencegah event buka-tutup cepat.

Jika tidak ada threshold recovery terpisah, gunakan:

```text
T_dns_latency_recovery(scope) = T_dns_latency(scope)
```

## Classification Output

```text
affected_scope = internal | external | all | unknown
affected_targets = DNS target yang latency-nya melewati threshold
```

Aturan:

```text
Jika hanya scope internal yang trigger -> affected_scope = internal
Jika hanya scope external yang trigger -> affected_scope = external
Jika internal dan external sama-sama trigger -> affected_scope = all
Jika scope tidak dapat ditentukan -> affected_scope = unknown
```

## Evidence

```text
DNS samples pre/event/post
dns target
resolver
dns latency
dns status
Wi-Fi snapshot
network snapshot
ping status di sekitar event
```

## Implementation Note

Kode saat ini sudah mendekati spesifikasi ini, tetapi static threshold masih berasal dari `default_config.json`, bukan hasil P99 baseline. Jika ingin sesuai dokumen ini, perlu pipeline kalibrasi yang mengisi `T_dns_latency(scope)` dari baseline phase.

---

# S2 - DNS_TIMEOUT_BURST

## Description

`DNS_TIMEOUT_BURST` adalah kondisi ketika query DNS gagal atau timeout secara berulang dalam jendela waktu pendek. Event ini berbeda dari `DNS_DEGRADED` karena masalah utamanya bukan DNS yang lambat, tetapi DNS yang tidak berhasil memberikan respons.

Event ini hanya dianggap DNS-specific jika Wi-Fi aktif dan IP reachability masih tersedia. Jika ping juga gagal, maka kegagalan DNS kemungkinan hanya dampak dari gangguan konektivitas yang lebih luas.

## User Impact

Dari sisi user, perangkat masih terlihat tersambung ke Wi-Fi dan beberapa koneksi yang sudah terbentuk sebelumnya mungkin tetap berjalan. Namun, layanan baru yang membutuhkan DNS lookup dapat gagal dibuka. Browser dapat menampilkan DNS error, aplikasi gagal login, dan layanan berbasis domain tidak dapat diakses.

Gejala dapat terlihat tidak konsisten karena sebagian domain mungkin masih bisa diakses jika hasil DNS sebelumnya masih tersimpan di cache.

## Data Source

Event ini menggunakan data dari fast probe DNS.

Field yang digunakan:

```text
wifi.wifi_up
ping.success
dns[].success
dns[].timeout
dns[].status
dns[].scope
dns[].target
```

## Trigger Logic

### Primary Trigger

```text
Trigger DNS_TIMEOUT_BURST jika:
  wifi.wifi_up == true
  ping.success == true
  dns_fail_count(scope, W_dns) >= m_dns
  sample_count(scope, W_dns) >= n_dns_min
```

Alternatif bentuk rasio:

```text
Trigger DNS_TIMEOUT_BURST jika:
  wifi.wifi_up == true
  ping.success == true
  dns_fail_ratio(scope, W_dns) >= T_dns_fail_ratio(scope)
  sample_count(scope, W_dns) >= n_dns_min
```

### Parameter

#### `wifi.wifi_up == true`

Guard condition. Jika Wi-Fi tidak aktif, event bukan DNS timeout burst.

#### `ping.success == true`

Guard condition. Jika ping gagal, event bukan DNS-specific. Event lebih tepat diarahkan ke S3 atau S6.

#### `W_dns`

`W_dns` adalah sliding window untuk menghitung DNS failure dalam rentang waktu tertentu.

Jika sampling interval stabil:

```text
W_dns = n_dns × sampling_interval_dns
```

Jika sampling interval tidak stabil:

```text
W_dns = semua DNS sample dengan timestamp >= current_time - W_dns
```

#### `sample_count(scope, W_dns)`

Jumlah DNS sample dalam window untuk scope tertentu.

Syarat minimum:

```text
n_dns_min >= 10
```

Alasannya:

```text
Dengan 10 sampel, resolusi failure ratio adalah 10%.
Jika kurang dari 10 sampel, rasio terlalu kasar dan rawan false alarm.
```

#### `dns_fail_count(scope, W_dns)`

Jumlah DNS query gagal dalam window.

Definisi gagal:

```text
dns.success == false
```

Termasuk:

```text
timeout
SERVFAIL
REFUSED
resolver error
error lain yang membuat DNS query tidak menghasilkan jawaban valid
```

#### `m_dns`

`m_dns` adalah jumlah minimal DNS failure dalam window.

Nilai final tidak di-hard-code. Nilai ditentukan melalui sweep kandidat:

```text
m_dns ∈ {2, 3, 4, 5}
```

Pemilihan:

```text
FAR dihitung dari baseline normal.
MTTD dan recall dihitung dari fault injection S2.
Pilih m_dns yang menghasilkan FAR rendah tanpa membuat MTTD terlalu tinggi.
```

#### `dns_fail_ratio(scope, W_dns)`

Jika menggunakan bentuk rasio:

```text
dns_fail_ratio(scope, W_dns) = dns_fail_count(scope, W_dns) / sample_count(scope, W_dns)
```

#### `T_dns_fail_ratio(scope)`

Threshold rasio DNS failure dihitung dari baseline phase.

Bentuk:

```text
T_dns_fail_ratio(scope) = P99(dns_fail_ratio(scope, W_dns) normal)
```

Karena P99 normal sering bernilai 0, trigger praktis tetap harus memiliki `m_dns` minimum.

Rekomendasi implementasi:

```text
Trigger menggunakan dns_fail_count >= m_dns.
dns_fail_ratio digunakan untuk metadata dan severity.
```

## Recovery Logic

```text
Recover DNS_TIMEOUT_BURST jika:
  wifi.wifi_up == true
  ping.success == true
  dns_success_ratio(scope, W_dns_recovery) >= S_recovery
  recovery_consecutive == R_dns_timeout
```

Untuk recovery strict:

```text
S_recovery = 1.0
```

Jika baseline normal menunjukkan DNS failure sporadis, `S_recovery` boleh diturunkan berdasarkan data normal.

## Classification Output

```text
affected_scope = internal | external | all | unknown
affected_targets = DNS target yang gagal dalam window
```

Aturan:

```text
Internal trigger, external tidak trigger -> affected_scope = internal
External trigger, internal tidak trigger -> affected_scope = external
Internal dan external trigger -> affected_scope = all
Tidak cukup data -> affected_scope = unknown
```

## Evidence

```text
DNS success/fail samples pre/event/post
DNS status dan timeout flag
resolver
ping status
Wi-Fi status
network snapshot
```

## Implementation Note

Kode saat ini belum menghitung S2 sebagai temporal burst. Kode saat ini menghitung `dns_fail_ratio` dari DNS entries dalam satu sample, bukan dari beberapa sample dalam sliding window waktu. Agar sesuai spesifikasi ini, perlu ditambahkan DNS history berbasis timestamp.

---

# S3 - LOSS_BURST

## Description

`LOSS_BURST` adalah kondisi ketika packet loss meningkat secara signifikan dalam interval pendek saat Wi-Fi masih aktif. Event ini merepresentasikan degradasi konektivitas transien, bukan disconnected state yang stabil.

Event ini tidak boleh dipicu dari satu ping gagal. Packet loss harus dihitung dari beberapa sampel dalam sliding window.

## User Impact

Dari sisi user, koneksi terasa tidak stabil. Sebagian request berhasil, sebagian gagal. Pengguna dapat mengalami halaman web berhenti di tengah loading, video call freeze, audio putus-putus, aplikasi melakukan retry, atau game dan remote session terasa patah-patah.

Masalah ini biasanya dirasakan sebagai internet yang kadang jalan dan kadang tidak.

## Data Source

Event ini menggunakan fast probe ping.

Field yang digunakan:

```text
wifi.wifi_up
ping.success
```

## Trigger Logic

### Primary Trigger

```text
Trigger LOSS_BURST jika:
  wifi.wifi_up == true
  sample_count(W_ping) >= n_ping_min
  ping_loss_pct_window(W_ping) >= T_loss
```

Alternatif bentuk count:

```text
Trigger LOSS_BURST jika:
  wifi.wifi_up == true
  sample_count(W_ping) >= n_ping_min
  ping_fail_count(W_ping) >= m_ping
```

### Parameter

#### `wifi.wifi_up == true`

Guard condition. Jika Wi-Fi tidak aktif, event bukan loss burst, melainkan connectivity problem.

#### `W_ping`

Sliding window untuk menghitung ping loss.

Jika sampling interval stabil:

```text
W_ping = n_ping × sampling_interval_ping
```

Jika sampling interval tidak stabil:

```text
W_ping = semua ping sample dengan timestamp >= current_time - W_ping
```

#### `sample_count(W_ping)`

Jumlah ping sample dalam window.

Syarat minimum:

```text
n_ping_min >= 20
```

Alasannya:

```text
Dengan 20 sampel, 1 ping gagal = 5%.
Resolusi 5% lebih layak untuk menghitung packet loss dibanding 10 sampel yang resolusinya 10%.
```

#### `ping_fail_count(W_ping)`

Jumlah ping gagal dalam window.

Definisi gagal:

```text
ping.success == false
```

#### `ping_loss_pct_window(W_ping)`

```text
ping_loss_pct_window = ping_fail_count(W_ping) / sample_count(W_ping) × 100%
```

#### `T_loss`

Threshold packet loss dihitung dari baseline phase.

Bentuk:

```text
T_loss = P99(ping_loss_pct_window normal)
```

Jika P99 normal bernilai 0 atau sangat kecil, gunakan count minimum `m_ping` sebagai syarat tambahan agar satu ping gagal tidak langsung menjadi event.

#### `m_ping`

`m_ping` adalah jumlah minimum ping failure dalam window.

Nilai final ditentukan melalui sweep kandidat:

```text
m_ping ∈ {2, 3, 4, 5}
```

Contoh interpretasi jika `n_ping = 20`:

```text
m_ping = 2 -> 10% loss
m_ping = 3 -> 15% loss
m_ping = 4 -> 20% loss
```

Pemilihan:

```text
FAR dihitung dari baseline normal.
MTTD dan recall dihitung dari fault injection S3.
```

## Recovery Logic

```text
Recover LOSS_BURST jika:
  sample_count(W_ping) >= n_ping_min
  ping_loss_pct_window(W_ping) < T_loss_recovery
  recovery_consecutive == R_loss
```

Jika tidak ada threshold recovery terpisah:

```text
T_loss_recovery = T_loss
```

Agar event tidak cepat buka-tutup, disarankan threshold recovery lebih rendah daripada trigger threshold.

## Classification Output

```text
affected_scope = all
```

Alasan:

```text
Fast ping target pada konfigurasi saat ini hanya satu target.
Karena itu, event belum dapat membedakan internal/external.
```

Jika nanti ping target dibuat per scope, `affected_scope` dapat dihitung dari target yang terdampak.

## Evidence

```text
ping success/fail samples pre/event/post
ping_loss_pct_window
sample_count
Wi-Fi status
DNS samples di sekitar event
HTTP timing di sekitar event jika tersedia
```

Catatan:

```text
DNS dan HTTP tidak menjadi trigger S3.
DNS dan HTTP hanya evidence untuk melihat dampak packet loss ke layer lain.
```

## Implementation Note

Kode saat ini sudah menggunakan sliding window untuk S3. Namun default config belum konsisten:

```text
fast_interval_sec = 5
loss_window_sec = 10
minimum_samples = 5
```

Dengan interval 5 detik, window 10 detik kemungkinan tidak cukup untuk mencapai 5 sampel. Untuk S3, gunakan fast interval lebih kecil, misalnya 1 detik atau 0.5 detik.

---

# S4 - HIGH_RTT

## Description

`HIGH_RTT` adalah kondisi ketika round-trip time meningkat secara abnormal dibanding kondisi normal jaringan, sementara packet loss tetap rendah. Event ini merepresentasikan degradasi latency, bukan outage atau packet loss burst.

Ciri utama event ini adalah koneksi tetap tersedia, tetapi waktu respons jaringan meningkat.

## User Impact

Dari sisi user, koneksi masih berjalan tetapi terasa lambat. Halaman web membutuhkan waktu lebih lama untuk merespons, login aplikasi tertunda, video call mengalami delay, remote desktop terasa berat, dan aplikasi interaktif menjadi kurang responsif.

Berbeda dengan `LOSS_BURST`, gejala utama pada `HIGH_RTT` bukan request gagal, tetapi respons yang terlambat.

## Data Source

Event ini menggunakan telemetry probe ping batch.

Field yang digunakan:

```text
ping.rtt_avg_ms
ping.loss_pct
```

## Trigger Logic

### Primary Trigger

```text
Trigger HIGH_RTT jika:
  rtt_avg_ms is not null
  loss_pct is not null
  rtt_avg_ms >= T_rtt
  loss_pct < T_loss_guard
  confirm_consecutive == N_rtt
```

### Parameter

#### `rtt_avg_ms is not null`

Guard condition. Jika RTT tidak berhasil diukur, sistem tidak boleh menyimpulkan `HIGH_RTT`.

#### `loss_pct is not null`

Guard condition. `HIGH_RTT` hanya boleh diklasifikasikan sebagai pure latency event jika loss diketahui. Jika loss tidak diketahui, event tidak boleh diklasifikasikan sebagai pure `HIGH_RTT`.

#### `rtt_avg_ms >= T_rtt`

Primary threshold untuk latency.

Threshold dihitung dari baseline phase:

```text
T_rtt(target) = P99(rtt_avg_ms normal untuk target tersebut)
```

Threshold harus dihitung per target karena RTT ke gateway, target internal, dan target eksternal dapat memiliki distribusi normal yang berbeda.

#### `loss_pct < T_loss_guard`

Exclusion condition. Jika loss tinggi, event lebih tepat diarahkan ke `LOSS_BURST` atau mixed event, bukan pure `HIGH_RTT`.

Threshold guard dihitung dari baseline phase:

```text
T_loss_guard = P99(loss_pct normal dari telemetry ping batch)
```

Jika `T_loss_guard` bernilai 0, maka pure `HIGH_RTT` hanya berlaku ketika `loss_pct == 0`.

#### `N_rtt`

Jumlah telemetry sample berturut-turut yang harus memenuhi trigger.

Nilai final ditentukan melalui sweep:

```text
N_rtt ∈ {1, 2, 3, 4}
```

Pemilihan:

```text
FAR dihitung dari baseline normal.
MTTD dan recall dihitung dari fault injection S4.
```

Catatan:

```text
Jika telemetry_interval_sec = 30 dan N_rtt = 2, maka delay deteksi dapat mendekati 60 detik.
Untuk eksperimen S4 yang menargetkan MTTD rendah, telemetry interval perlu dibuat lebih cepat.
```

## Recovery Logic

```text
Recover HIGH_RTT jika:
  rtt_avg_ms is not null
  loss_pct is not null
  rtt_avg_ms < T_rtt_recovery
  loss_pct < T_loss_guard
  recovery_consecutive == R_rtt
```

Jika tidak ada recovery threshold terpisah:

```text
T_rtt_recovery = T_rtt
```

## Classification Output

```text
affected_scope = all
```

Alasan:

```text
Telemetry ping target pada konfigurasi saat ini hanya satu target.
Jika target RTT dibuat per scope, affected_scope dapat dihitung dari target yang melewati threshold.
```

## Evidence

```text
rtt_min_ms
rtt_avg_ms
rtt_max_ms
rtt_mdev_ms
loss_pct
Wi-Fi snapshot
DNS samples
HTTP timing samples jika tersedia
```

Catatan:

```text
rtt_mdev_ms, DNS, HTTP, RSSI, dan BSSID adalah evidence/diagnostic.
Mereka bukan trigger S4 kecuali diberi aturan eksplisit.
```

## Implementation Note

Kode saat ini sudah memiliki struktur S4 yang benar, yaitu `rtt_avg_ms >= threshold` dan `loss_pct < loss_limit`. Namun kode saat ini masih mengizinkan `loss_pct == None` untuk tetap trigger. Untuk mengikuti spesifikasi ini, `loss_pct` harus wajib tersedia.

---

# S5 - HTTP_SLOW

## Description

`HTTP_SLOW` adalah kondisi ketika transaksi HTTP menjadi lambat atau gagal pada layer aplikasi, setelah penyebab yang lebih rendah seperti Wi-Fi down, DNS failure, DNS degraded, high RTT, dan packet loss tinggi dikeluarkan.

Event ini berfokus pada pengalaman akses aplikasi. Sebuah layanan dapat mengalami HTTP slow walaupun Wi-Fi, ping, dan DNS terlihat normal.

## User Impact

Dari sisi user, aplikasi atau website terasa lambat meskipun koneksi terlihat aktif. Halaman web lama menampilkan konten pertama, login aplikasi tertunda, request API lambat, atau layanan tertentu mengalami timeout.

Masalah ini dapat terjadi hanya pada target tertentu, misalnya layanan internal lambat sementara layanan eksternal tetap normal.

## Data Source

Event ini menggunakan telemetry probe HTTP check dan telemetry probe pendukung.

Field yang digunakan sebagai trigger/guard:

```text
wifi.wifi_connected
ping.rtt_avg_ms
ping.loss_pct
http[].curl_rc
http[].http_status
http[].http_dns_ms
http[].http_total_ms
http[].http_ttfb_ms
http[].expected_status_min
http[].expected_status_max
http[].scope
http[].url
```

## Trigger Logic

### Primary Trigger

```text
Trigger HTTP_SLOW jika:
  wifi.wifi_connected == true
  rtt_avg_ms is not null
  loss_pct is not null
  rtt_avg_ms < T_rtt
  loss_pct < T_loss_guard

  dan untuk HTTP target tertentu:
    curl_rc not in DNS_RELATED_CURL_RC
    http_dns_ms < T_http_dns(url)
    salah satu:
      http_total_ms >= T_http_total(url)
      atau http_ttfb_ms >= T_http_ttfb(url)
      atau curl_rc in HTTP_FAILURE_CURL_RC
      atau http_status not in expected range

  confirm_consecutive == N_http
```

### Parameter

#### `wifi.wifi_connected == true`

Guard condition. Jika Wi-Fi tidak connected, event bukan HTTP slow.

#### `rtt_avg_ms is not null` dan `loss_pct is not null`

Guard condition. HTTP slow hanya boleh diklasifikasikan sebagai pure application-layer event jika kondisi RTT dan loss diketahui.

#### `rtt_avg_ms < T_rtt`

Exclusion condition. Jika RTT umum tinggi, HTTP lambat kemungkinan dampak dari `HIGH_RTT`, bukan pure `HTTP_SLOW`.

```text
T_rtt = P99(rtt_avg_ms normal)
```

#### `loss_pct < T_loss_guard`

Exclusion condition. Jika packet loss tinggi, HTTP timeout atau HTTP lambat kemungkinan dampak dari `LOSS_BURST`.

```text
T_loss_guard = P99(loss_pct normal)
```

#### `curl_rc not in DNS_RELATED_CURL_RC`

Exclusion condition. Jika curl gagal karena DNS resolve failure, event harus diarahkan ke S2.

Minimal definisi:

```text
DNS_RELATED_CURL_RC = {6}
```

`curl_rc == 6` berarti host tidak dapat di-resolve. Karena itu tidak boleh diklasifikasikan sebagai pure HTTP slow.

#### `http_dns_ms < T_http_dns(url)`

Exclusion condition. Jika fase DNS pada HTTP request lambat, HTTP total time dapat ikut naik karena DNS. Dalam kondisi ini, root event lebih tepat diarahkan ke S1.

Threshold:

```text
T_http_dns(url) = P99(http_dns_ms normal untuk URL tersebut | http_ok == true)
```

#### `http_total_ms >= T_http_total(url)`

Primary threshold untuk total durasi transaksi HTTP.

Threshold:

```text
T_http_total(url) = P99(http_total_ms normal untuk URL tersebut | http_ok == true)
```

#### `http_ttfb_ms >= T_http_ttfb(url)`

Primary threshold untuk time to first byte. Parameter ini digunakan untuk mendeteksi keterlambatan awal response server atau aplikasi.

Threshold:

```text
T_http_ttfb(url) = P99(http_ttfb_ms normal untuk URL tersebut | http_ok == true)
```

#### `curl_rc in HTTP_FAILURE_CURL_RC`

Primary categorical trigger untuk HTTP failure yang bukan DNS-related.

Minimal definisi:

```text
HTTP_FAILURE_CURL_RC = semua curl_rc != 0 kecuali DNS_RELATED_CURL_RC
```

Jika ingin lebih strict, daftar `HTTP_FAILURE_CURL_RC` harus didefinisikan eksplisit di konfigurasi.

#### `http_status not in expected range`

Primary categorical trigger untuk HTTP response di luar status yang diharapkan.

Expected range diambil dari konfigurasi target:

```text
expected_status_min <= http_status <= expected_status_max
```

Default:

```text
expected_status_min = 200
expected_status_max = 399
```

#### `N_http`

Jumlah HTTP check berturut-turut yang harus memenuhi trigger.

Nilai final ditentukan melalui sweep:

```text
N_http ∈ {1, 2, 3}
```

Catatan:

```text
HTTP check biasanya memiliki interval sampling lebih lambat daripada fast probe.
Karena itu N_http tidak boleh terlalu besar tanpa menghitung dampaknya ke MTTD.
```

## Recovery Logic

```text
Recover HTTP_SLOW jika:
  wifi.wifi_connected == true
  rtt_avg_ms < T_rtt
  loss_pct < T_loss_guard
  untuk affected HTTP target:
    curl_rc == 0
    http_status dalam expected range
    http_dns_ms < T_http_dns(url)
    http_total_ms < T_http_total_recovery(url)
    http_ttfb_ms < T_http_ttfb_recovery(url)
  recovery_consecutive == R_http
```

Jika tidak ada threshold recovery terpisah:

```text
T_http_total_recovery(url) = T_http_total(url)
T_http_ttfb_recovery(url) = T_http_ttfb(url)
```

## Classification Output

```text
affected_scope = internal | external | all | unknown
affected_targets = HTTP target yang memenuhi primary trigger
```

Aturan:

```text
Hanya target internal trigger -> affected_scope = internal
Hanya target external trigger -> affected_scope = external
Internal dan external sama-sama trigger -> affected_scope = all
Tidak cukup target untuk menentukan scope -> affected_scope = unknown
```

## Evidence

```text
HTTP timing breakdown
curl_rc
curl_stderr
http_status
http_dns_ms
http_connect_ms
http_tls_ms
http_ttfb_ms
http_total_ms
DNS samples
RTT/loss samples
Wi-Fi snapshot
network snapshot
```

Catatan:

```text
DNS, RTT, dan loss bukan evidence-only pada S5.
Mereka adalah guard/exclusion condition.
Jika guard/exclusion gagal, S5 tidak boleh trigger sebagai pure HTTP_SLOW.
```

## Implementation Note

Kode saat ini belum memenuhi spesifikasi S5 ini. Kode saat ini masih menganggap semua `curl_rc != 0` sebagai HTTP_SLOW dan belum mengecualikan DNS degraded, high RTT, atau loss burst. Agar sesuai spesifikasi ini, perlu ditambahkan guard/exclusion condition pada `_eval_http_slow()`.

---

# S6 - CONNECTIVITY_FLAP

## Description

`CONNECTIVITY_FLAP` adalah kondisi ketika state konektivitas berubah berulang antara reachable dan unreachable dalam jendela waktu pendek. Event ini merepresentasikan koneksi putus-nyambung.

Event ini tidak harus selalu berarti Wi-Fi disconnect. Flap dapat terjadi pada beberapa layer:

```text
wifi_link
upstream
dns
application
```

Namun layer yang dicurigai harus ditulis sebagai classification output, bukan dicampur ke primary trigger.

## User Impact

Dari sisi user, koneksi terasa putus-nyambung. Aplikasi berulang kali reconnect, sesi web gagal atau terputus, video call freeze lalu pulih, login aplikasi gagal secara intermittent, dan layanan real-time menjadi tidak stabil.

Berbeda dari outage penuh, flap biasanya muncul dan hilang dalam waktu pendek.

## Data Source

Event ini menggunakan fast probe history.

Field yang digunakan:

```text
connectivity_ok
wifi.wifi_up
ping.success
dns[].success
```

HTTP history dapat digunakan untuk classification application-layer flap jika tersedia.

## Trigger Logic

### Primary Trigger

```text
Trigger CONNECTIVITY_FLAP jika:
  sample_count(W_flap) >= n_flap_min
  state_transition_count(connectivity_ok, W_flap) >= T_transition
```

### Parameter

#### `connectivity_ok`

`connectivity_ok` harus didefinisikan eksplisit.

Definisi current code:

```text
connectivity_ok = wifi.wifi_up == true
                  AND ping.success == true
                  AND all dns[].success == true
```

Konsekuensi definisi ini:

```text
DNS failure dapat membuat connectivity_ok menjadi false.
Artinya DNS-layer flap dapat ikut terdeteksi sebagai CONNECTIVITY_FLAP.
```

Jika penelitian ingin `CONNECTIVITY_FLAP` hanya untuk global connectivity/IP connectivity, definisi yang lebih tepat adalah:

```text
connectivity_ok = wifi.wifi_up == true
                  AND ping.success == true
```

Keputusan harus dipilih sebelum eksperimen dan ditulis di konfigurasi. Dokumen ini menggunakan definisi current code selama tidak diubah:

```text
connectivity_ok = wifi_up AND ping_success AND dns_all_ok
```

#### `W_flap`

Window waktu untuk menghitung state transition.

Jika fault injection menggunakan:

```text
down_duration_sec = 2–10
up_duration_sec = 2–10
```

maka satu siklus putus-pulih berlangsung:

```text
cycle_time = down_duration_sec + up_duration_sec
           = 4–20 detik
```

Karena itu, kandidat awal yang code-able:

```text
W_flap ∈ {20, 30} detik
```

Nilai final dipilih berdasarkan FAR pada baseline normal dan MTTD/recall pada fault injection S6.

#### `sample_count(W_flap)`

Jumlah sample dalam window. Agar transition count tidak terlalu kasar:

```text
n_flap_min >= 10
```

Jika `fast_interval_sec = 1`, maka 20 detik menghasilkan sekitar 20 sample.
Jika `fast_interval_sec = 2`, maka 20 detik menghasilkan sekitar 10 sample.
Jika `fast_interval_sec = 5`, maka 20 detik hanya menghasilkan sekitar 4 sample dan tidak direkomendasikan.

#### `state_transition_count(connectivity_ok, W_flap)`

Jumlah perubahan state `connectivity_ok` dalam window.

Contoh:

```text
true -> false = 1 transition
false -> true = 1 transition
```

Urutan:

```text
true -> false -> true
```

berarti:

```text
state_transition_count = 2
```

#### `T_transition`

Threshold jumlah transisi.

Nilai minimum semantik:

```text
T_transition_min = 2
```

Alasannya:

```text
2 transisi merepresentasikan satu siklus putus-pulih.
```

Untuk definisi lebih ketat:

```text
T_transition = 4
```

Alasannya:

```text
4 transisi merepresentasikan dua siklus putus-pulih penuh.
```

Nilai final ditentukan melalui sweep:

```text
T_transition ∈ {2, 3, 4}
W_flap ∈ {20, 30}
```

Pemilihan:

```text
FAR dihitung pada baseline normal.
MTTD, recall, dan event fragmentation dihitung pada fault injection S6.
```

## Recovery Logic

```text
Recover CONNECTIVITY_FLAP jika:
  connectivity_ok == true
  tidak ada transition baru selama recovery_hold_sec
  recovery_consecutive == R_flap
```

`recovery_hold_sec` harus lebih besar dari sampling interval fast probe.

## Classification Output

```text
suspected_layer = wifi_link | upstream | dns | application | unknown
```

Aturan classification:

```text
Jika wifi_up berubah true/false:
  suspected_layer = wifi_link

Jika wifi_up stabil true, tetapi ping.success berubah true/false:
  suspected_layer = upstream

Jika wifi_up stabil true, ping.success stabil true, tetapi dns_all_ok berubah true/false:
  suspected_layer = dns

Jika wifi_up stabil true, ping.success stabil true, dns_all_ok stabil true, tetapi http_ok berubah true/false:
  suspected_layer = application

Jika tidak cukup data:
  suspected_layer = unknown
```

Catatan:

```text
suspected_layer bukan primary trigger.
suspected_layer hanya metadata untuk menjelaskan layer yang kemungkinan menyebabkan flap.
```

## Evidence

```text
connectivity_ok timeline
wifi_up timeline
ping.success timeline
dns_all_ok timeline
http_ok timeline jika tersedia
wifi_bssid
wifi_rssi_dbm
network snapshot
```

## Implementation Note

Kode saat ini sudah menghitung `state_transition_count(connectivity_ok)` dalam `flap_window_sec`. Namun kode belum mensyaratkan `sample_count(W_flap) >= n_flap_min`. Jika ingin mengikuti spesifikasi ini, tambahkan minimum sample count untuk S6.

Kode saat ini juga mendefinisikan `connectivity_ok` sebagai gabungan Wi-Fi, ping, dan DNS. Definisi ini harus diputuskan secara eksplisit karena memengaruhi overlap antara S2 dan S6.

---

# 3. Ringkasan Trigger Final

| Event | Primary Trigger | Guard / Exclusion Utama | Window / Consecutive |
|---|---|---|---|
| S1 `DNS_DEGRADED` | `max_dns_latency_ms(scope) >= T_dns_latency(scope)` | `wifi_up == true`, `ping.success == true`, `dns_success_ratio >= S_min` | `N_dns` consecutive |
| S2 `DNS_TIMEOUT_BURST` | `dns_fail_count(scope, W_dns) >= m_dns` | `wifi_up == true`, `ping.success == true` | Sliding window `W_dns`, `n_dns_min >= 10` |
| S3 `LOSS_BURST` | `ping_loss_pct_window >= T_loss` atau `ping_fail_count >= m_ping` | `wifi_up == true` | Sliding window `W_ping`, `n_ping_min >= 20` |
| S4 `HIGH_RTT` | `rtt_avg_ms >= T_rtt` | `loss_pct is not null`, `loss_pct < T_loss_guard` | `N_rtt` consecutive |
| S5 `HTTP_SLOW` | `http_total_ms >= T_http_total` atau `http_ttfb_ms >= T_http_ttfb` atau HTTP failure non-DNS | `wifi_connected == true`, `rtt < T_rtt`, `loss < T_loss_guard`, `http_dns_ms < T_http_dns`, `curl_rc != 6` | `N_http` consecutive |
| S6 `CONNECTIVITY_FLAP` | `state_transition_count(connectivity_ok, W_flap) >= T_transition` | `sample_count(W_flap) >= n_flap_min` | Sliding window `W_flap` |

---

# 4. Parameter yang Harus Ada di Config Eksperimen

```yaml
thresholds:
  dns_latency_threshold_ms_internal: <hasil P99 baseline>
  dns_latency_threshold_ms_external: <hasil P99 baseline>
  dns_fail_count_threshold_internal: <hasil sweep>
  dns_fail_count_threshold_external: <hasil sweep>
  dns_window_sec: <hasil desain/sweep>
  loss_threshold_pct: <hasil P99 baseline atau sweep>
  loss_window_sec: <hasil desain/sweep>
  rtt_threshold_ms: <hasil P99 baseline>
  rtt_loss_upper_bound_pct: <hasil P99 baseline>
  http_dns_threshold_ms_by_url: <hasil P99 baseline per URL>
  http_total_threshold_ms_by_url: <hasil P99 baseline per URL>
  http_ttfb_threshold_ms_by_url: <hasil P99 baseline per URL>
  flap_transition_threshold: <hasil sweep>
  flap_window_sec: <hasil sweep>

detector.events:
  DNS_DEGRADED:
    confirm_consecutive: <hasil sweep N=1..4>
    recovery_consecutive: <hasil sweep/ditentukan>
    minimum_success_ratio: 1.0

  DNS_TIMEOUT_BURST:
    recovery_consecutive: <hasil sweep/ditentukan>

  LOSS_BURST:
    minimum_samples: 20
    recovery_consecutive: <hasil sweep/ditentukan>

  HIGH_RTT:
    confirm_consecutive: <hasil sweep N=1..4>
    recovery_consecutive: <hasil sweep/ditentukan>

  HTTP_SLOW:
    confirm_consecutive: <hasil sweep N=1..3>
    recovery_consecutive: <hasil sweep/ditentukan>

  CONNECTIVITY_FLAP:
    recovery_consecutive: 1
```

---

# 5. Catatan Implementasi terhadap Kode Saat Ini

Bagian ini menjelaskan perbedaan antara spesifikasi final di dokumen ini dan kode yang ada sekarang.

## S1

Status:

```text
Sebagian besar sudah sesuai.
```

Perlu perbaikan:

```text
Threshold static masih global dan manual.
Perlu kalibrasi P99.
Jika ingin threshold per scope, config dan detector perlu mendukung threshold internal/external.
```

## S2

Status:

```text
Belum sesuai.
```

Perlu perbaikan:

```text
Kode saat ini menghitung DNS fail ratio dari satu sample, bukan sliding window temporal.
Perlu ditambahkan dns_history dan perhitungan dns_fail_count dalam W_dns.
```

## S3

Status:

```text
Logika sudah mendekati spesifikasi.
```

Perlu perbaikan:

```text
Default fast_interval_sec, loss_window_sec, dan minimum_samples belum konsisten.
Gunakan fast_interval_sec 1–2 detik atau sesuaikan window agar minimum sample tercapai.
```

## S4

Status:

```text
Logika dasar sudah sesuai.
```

Perlu perbaikan:

```text
loss_pct harus wajib tersedia untuk pure HIGH_RTT.
Threshold perlu hasil P99.
Telemetry interval harus disesuaikan agar MTTD tidak terlalu tinggi.
```

## S5

Status:

```text
Belum sesuai.
```

Perlu perbaikan:

```text
curl_rc == 6 harus diarahkan ke DNS failure, bukan HTTP_SLOW.
Perlu exclusion untuk DNS degraded, high RTT, dan loss burst.
Perlu threshold HTTP per URL.
```

## S6

Status:

```text
Sebagian besar sesuai.
```

Perlu perbaikan:

```text
Definisi connectivity_ok harus diputuskan.
Jika tetap memakai wifi_up AND ping_success AND dns_all_ok, maka DNS-layer flap dapat masuk S6.
Tambahkan minimum sample count dalam W_flap.
```
