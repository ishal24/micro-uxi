# Skema Fault Injection Micro-UXI S1–S6

Dokumen ini mendefinisikan enam skema fault injection utama untuk evaluasi Micro-UXI:

1. S1 — `DNS_DEGRADED`
2. S2 — `DNS_TIMEOUT_BURST`
3. S3 — `LOSS_BURST`
4. S4 — `HIGH_RTT`
5. S5 — `HTTP_SLOW`
6. S6 — `CONNECTIVITY_FLAP`

Dokumen ini hanya membahas definisi event, dampak ke pengguna, dan trigger logic. Pembahasan evidence bundle tidak dimasukkan di dokumen ini.

---

# 0. Definisi Istilah

## 0.1 Primary Trigger

`Primary Trigger` adalah kondisi utama yang secara langsung mendefinisikan bahwa sebuah event terjadi.

Contoh:

```text
dns_latency_ms >= T_dns_latency
```

Artinya, DNS latency melewati threshold yang sudah ditentukan dari preliminary test.

## 0.2 Supporting Trigger

`Supporting Trigger` adalah kondisi tambahan untuk memastikan event tidak salah klasifikasi. Supporting trigger harus tetap bersifat implementable di code, sehingga bentuknya harus berupa boolean, threshold, count, atau assignment yang jelas.

Contoh:

```text
wifi_up == true
ping.success == true
```

Artinya, event DNS tidak boleh diklasifikasikan sebagai DNS problem kalau Wi-Fi atau IP reachability sedang mati.

Classification seperti `affected_scope` atau `suspected_layer` juga masuk ke supporting trigger karena ia membantu menjelaskan cakupan atau layer event.

## 0.3 Threshold

`Threshold` adalah batas numerik yang digunakan untuk menentukan apakah suatu metrik sudah keluar dari kondisi normal.

Contoh:

```text
T_dns_latency
T_rtt
T_http_total
T_http_ttfb
```

Threshold untuk baseline monitoring statis diperoleh dari preliminary test dengan mengambil P99 dari data normal.

## 0.4 Confirm Consecutive

`confirm_consecutive` adalah jumlah sampel berturut-turut yang harus memenuhi primary trigger sebelum event dinyatakan aktif.

Contoh:

```text
confirm_consecutive == N_dns
```

Jika `N_dns = 3`, maka DNS latency harus melewati threshold pada 3 sampel DNS berturut-turut sebelum event `DNS_DEGRADED` dinyatakan aktif.

`confirm_consecutive` digunakan untuk event berbasis threshold numerik yang dinilai per sampel, seperti:

- S1 `DNS_DEGRADED`
- S4 `HIGH_RTT`
- S5 `HTTP_SLOW`

## 0.5 Sliding Window

`Sliding window` adalah kumpulan sampel terbaru dalam jumlah tertentu atau rentang waktu tertentu. Window ini bergerak setiap kali sampel baru masuk.

Contoh sample-based window:

```text
n = 10 sampel

t=10 -> pakai sampel t=1 sampai t=10
t=11 -> pakai sampel t=2 sampai t=11
t=12 -> pakai sampel t=3 sampai t=12
```

Contoh time-based window:

```text
W = 10 detik

pada waktu sekarang t:
  ambil semua sampel dengan timestamp >= t - 10 detik
```

Sliding window digunakan untuk event berbasis count atau ratio, seperti:

- S2 `DNS_TIMEOUT_BURST`
- S3 `LOSS_BURST`
- S6 `CONNECTIVITY_FLAP`

## 0.6 m-of-n Rule

`m-of-n rule` adalah aturan trigger berbasis jumlah kejadian dalam window.

Contoh:

```text
dns_fail_count >= m_dns dalam n_dns sampel
```

Jika:

```text
n_dns = 10
m_dns = 3
```

maka event aktif jika terdapat minimal 3 DNS failure dalam 10 sampel terakhir.

`m-of-n rule` berbeda dari `confirm_consecutive`.

- `confirm_consecutive` mensyaratkan kondisi abnormal terjadi berturut-turut.
- `m-of-n rule` tidak mensyaratkan berturut-turut; yang penting jumlah failure dalam window mencapai batas minimum.

Contoh:

```text
Sequence:
OK, FAIL, OK, FAIL, FAIL, OK, OK, OK, OK, OK

confirm_consecutive = 3:
  tidak trigger, karena tidak ada 3 FAIL berturut-turut

m-of-n dengan m=3, n=10:
  trigger, karena ada 3 FAIL dalam 10 sampel
```

---

# 1. Preliminary Test

Preliminary test adalah pengujian kondisi normal jaringan sebelum fault injection dilakukan. Tujuannya adalah memperoleh data awal yang digunakan untuk menentukan baseline threshold dan parameter trigger.

Preliminary test harus dilakukan pada kondisi jaringan yang dianggap normal, tanpa fault injection. Konfigurasi preliminary test harus sama dengan konfigurasi eksperimen utama, meliputi:

- SSID atau access point yang digunakan
- DNS target
- HTTP target
- ping target
- interval sampling
- device dan interface jaringan
- lokasi pengujian
- resolver DNS yang digunakan

Jika konfigurasi berubah, preliminary test harus diulang karena distribusi metrik jaringan juga dapat berubah.

---

## 1.1 Threshold

Threshold diperlukan karena nilai normal setiap jaringan tidak sama. DNS latency, RTT, packet loss, dan HTTP timing dapat berbeda antara jaringan kampus, rumah, hotspot, lab, atau access point yang berbeda. Karena itu, threshold tidak ditentukan menggunakan angka universal, tetapi dihitung dari data normal jaringan uji.

Metrik numerik yang dihitung threshold-nya dari preliminary test adalah:

```text
dns_latency_ms
rtt_avg_ms
http_total_ms
http_ttfb_ms
```

Jika digunakan sebagai supporting trigger, threshold tambahan berikut juga dihitung:

```text
loss_pct_window
dns_fail_count atau dns_fail_ratio
ping_fail_count atau ping_loss_pct_window
state_transition_count
```

### Proses Penentuan Threshold Numerik

Untuk metrik numerik, prosesnya adalah:

```text
1. Jalankan preliminary test pada kondisi jaringan normal.
2. Kumpulkan sampel valid untuk setiap metrik dan target.
3. Kelompokkan data per target atau per scope.
4. Hitung P99 dari data normal.
5. Simpan nilai P99 sebagai threshold baseline monitoring statis.
```

Rumus umum:

```text
T_metric = P99(metric_normal)
```

Contoh untuk DNS latency:

```text
T_dns_latency(target) = P99(dns_latency_ms normal untuk target tersebut | dns_success == true)
```

Contoh untuk RTT:

```text
T_rtt(target) = P99(rtt_avg_ms normal untuk target tersebut)
```

Contoh untuk HTTP:

```text
T_http_total(url) = P99(http_total_ms normal untuk URL tersebut | curl_rc == 0 dan http_status in EXPECTED_HTTP_STATUS)

T_http_ttfb(url) = P99(http_ttfb_ms normal untuk URL tersebut | curl_rc == 0 dan http_status in EXPECTED_HTTP_STATUS)
```

### Data Valid

Tidak semua sampel boleh dipakai untuk menghitung threshold.

Untuk DNS latency:

```text
pakai hanya sampel dengan dns_success == true
```

Sampel DNS yang gagal tidak dipakai untuk menghitung `T_dns_latency`, karena DNS failure adalah event berbeda, yaitu S2 `DNS_TIMEOUT_BURST`.

Untuk HTTP timing:

```text
pakai hanya sampel dengan:
  curl_rc == 0
  http_status in EXPECTED_HTTP_STATUS
```

HTTP request yang timeout atau error tidak dipakai untuk menghitung threshold normal karena dapat membuat threshold menjadi terlalu tinggi.

Untuk RTT:

```text
pakai hanya sampel RTT yang valid
```

Jika ping batch gagal total atau tidak menghasilkan `rtt_avg_ms`, sampel tersebut tidak dipakai untuk menghitung `T_rtt`.

### Jumlah Sampel

Target ideal preliminary test adalah:

```text
minimal 10.000 sampel valid per metrik dan per target
```

Alasannya, P99 adalah metrik tail. Dengan 10.000 sampel, bagian 1% teratas berisi sekitar 100 sampel, sehingga estimasi P99 lebih stabil.

Jika 10.000 sampel tidak tercapai, batas bawah yang masih dapat digunakan untuk baseline awal adalah:

```text
minimal 1.000 sampel valid per metrik dan per target
```

Namun, jika hanya menggunakan 1.000 sampel, P99 hanya berada pada sekitar 10 sampel tertinggi. Hasilnya harus diperlakukan sebagai baseline awal dan perlu divalidasi lagi pada eksperimen.

### Kenapa P99

P99 dipilih karena:

```text
1. P99 merepresentasikan batas atas kondisi normal.
2. Secara empiris, sekitar 99% sampel normal berada di bawah threshold.
3. P99 lebih konservatif daripada P95 karena tidak terlalu mudah memicu false alarm.
4. P99 lebih stabil daripada P99.9 untuk jumlah sampel yang terbatas.
```

P95 dapat digunakan sebagai warning level, tetapi untuk event threshold baseline monitoring, P99 lebih sesuai karena event sebaiknya tidak terlalu mudah aktif akibat variasi normal.

---

## 1.2 Confirm Consecutive

`confirm_consecutive` digunakan untuk event berbasis threshold numerik yang dievaluasi per sampel. Event tidak langsung aktif hanya karena satu sampel melewati threshold.

Contoh:

```text
dns_latency_ms >= T_dns_latency
```

Jika hanya satu sampel melewati threshold, kondisi itu bisa saja spike sesaat. Karena itu diperlukan `confirm_consecutive`.

### Cara Menentukan N

Nilai N tidak ditentukan secara manual. Nilai N ditentukan dengan pengujian kandidat:

```text
N = 1, 2, 3, 4
```

Untuk setiap kandidat N:

```text
1. Jalankan detector pada data normal dari preliminary test.
2. Hitung False Alarm Rate (FAR).
3. Jalankan detector pada data fault injection.
4. Hitung Mean Time To Detect (MTTD), recall, dan F1.
5. Pilih nilai N terkecil yang menghasilkan FAR rendah dan MTTD tetap rendah.
```

Prinsip pemilihannya:

```text
N kecil:
  deteksi lebih cepat
  false alarm lebih tinggi

N besar:
  false alarm lebih rendah
  deteksi lebih lambat
```

Hubungan N dengan delay deteksi:

```text
confirmation_delay ≈ N × sampling_interval
```

Contoh:

```text
sampling_interval = 2 detik
N = 3

confirmation_delay ≈ 6 detik
```

Jika sampling interval lebih besar, nilai N harus lebih hati-hati karena delay deteksi akan ikut membesar.

---

## 1.3 Minimum Sample dan Sliding Window

Sliding window digunakan untuk event yang tidak cocok dinilai dari satu sampel tunggal. Event seperti DNS timeout burst, packet loss burst, dan connectivity flap membutuhkan pola dalam beberapa sampel.

Event yang menggunakan sliding window:

```text
S2 DNS_TIMEOUT_BURST
S3 LOSS_BURST
S6 CONNECTIVITY_FLAP
```

### Cara Menentukan n

`n` adalah jumlah sampel dalam window.

Nilai `n` ditentukan dari resolusi rasio yang dibutuhkan dan interval sampling.

Resolusi rasio:

```text
resolution = 1 / n
```

Contoh:

```text
n = 10  -> 1 failure = 10%
n = 20  -> 1 failure = 5%
n = 40  -> 1 failure = 2.5%
```

Untuk DNS failure ratio, resolusi 10% masih cukup sebagai batas awal karena DNS timeout biasanya bersifat jelas, yaitu success atau fail.

Karena itu:

```text
n_dns minimal = 10 sampel
```

Untuk packet loss, resolusi perlu lebih halus karena loss 5%, 10%, 15%, dan 20% memiliki dampak yang berbeda.

Karena itu:

```text
n_ping minimal = 20 sampel
```

Untuk connectivity flap, window ditentukan dari durasi pola flap yang ingin dideteksi. Jika pola fault injection memiliki down/up duration 2–10 detik, maka satu siklus putus-pulih dapat berlangsung 4–20 detik. Karena itu window kandidat yang masuk akal adalah 20–30 detik, dengan syarat jumlah sampel di dalamnya cukup.

Hubungan window waktu dan jumlah sampel:

```text
W = n × sampling_interval
```

Jika sampling interval tidak stabil, gunakan time-based window:

```text
ambil semua sampel dengan timestamp >= current_time - W
```

Namun tetap tetapkan minimum sample agar window tidak dihitung dari sampel yang terlalu sedikit:

```text
sample_count_in_window >= n_min
```

### Cara Menentukan m

`m` adalah jumlah minimum failure atau transition dalam window.

Nilai `m` tidak ditentukan secara manual. Nilai `m` ditentukan dengan pengujian kandidat pada data normal dan data fault injection.

Untuk setiap kandidat `n`, uji beberapa kandidat `m`.

Contoh untuk DNS:

```text
n_dns = 10
m_dns = 1, 2, 3, 4, 5
```

Contoh untuk packet loss:

```text
n_ping = 20
m_ping = 1, 2, 3, 4, 5
```

Prosedur pemilihannya:

```text
1. Hitung count dalam sliding window pada data normal.
2. Uji setiap kandidat m.
3. Hitung FAR pada data normal.
4. Jalankan kandidat yang sama pada data fault injection.
5. Hitung MTTD, recall, dan F1.
6. Pilih m terkecil yang menghasilkan FAR rendah dan tetap mendeteksi fault dengan MTTD rendah.
```

Untuk menghindari trigger dari satu sampel gagal, gunakan batas semantik minimum:

```text
m_dns >= 2
m_ping >= 2
m_transition >= 2
```

Makna batas minimum:

```text
m_dns >= 2:
  satu DNS timeout saja belum cukup disebut DNS_TIMEOUT_BURST

m_ping >= 2:
  satu ping gagal saja belum cukup disebut LOSS_BURST

m_transition >= 2:
  satu transisi true -> false hanya berarti mulai outage
  dua transisi true -> false -> true berarti satu siklus putus-pulih
```

---

## 1.4 Durasi Fault Injection

Durasi fault injection harus cukup lama agar event dapat terdeteksi oleh trigger yang digunakan. Durasi tidak boleh lebih pendek dari waktu observasi minimum detector.

### Untuk Event Berbasis Confirm Consecutive

Event berbasis confirm consecutive:

```text
S1 DNS_DEGRADED
S4 HIGH_RTT
S5 HTTP_SLOW
```

Durasi minimum fault harus memungkinkan sistem mengamati N sampel abnormal.

Rumus praktis:

```text
D_fault_min >= N × sampling_interval
```

Untuk menghindari fault selesai tepat sebelum sampel berikutnya, gunakan margin minimal satu interval:

```text
D_fault_min >= (N + 1) × sampling_interval
```

Contoh:

```text
sampling_interval = 5 detik
N = 2

D_fault_min >= (2 + 1) × 5
D_fault_min >= 15 detik
```

Jika ingin hasil MTTD lebih stabil, fault injection sebaiknya dibuat lebih lama daripada minimum matematis agar ada cukup sampel event.

### Untuk Event Berbasis m-of-n Window

Event berbasis m-of-n:

```text
S2 DNS_TIMEOUT_BURST
S3 LOSS_BURST
```

Durasi fault harus cukup untuk menghasilkan minimal `m` failure dalam window.

Jika fault membuat semua probe gagal, seperti DNS drop total:

```text
D_fault_min >= m × sampling_interval
```

Namun untuk pengujian yang lebih stabil, fault sebaiknya berlangsung minimal sepanjang window:

```text
D_fault_min >= W
```

Untuk packet loss, fault tidak selalu membuat semua sampel gagal. Jika injected loss rate adalah `p_fault`, maka jumlah sampel yang dibutuhkan untuk memperoleh `m` failure secara ekspektasi adalah:

```text
required_samples ≈ m / p_fault
```

Maka:

```text
D_fault_min >= required_samples × sampling_interval
```

Contoh:

```text
m_ping = 4
p_fault = 0.20
sampling_interval = 1 detik

required_samples ≈ 4 / 0.20 = 20 sampel
D_fault_min >= 20 detik
```

### Untuk Connectivity Flap

Untuk S6, durasi fault ditentukan oleh jumlah transisi yang ingin diamati.

Satu siklus putus-pulih:

```text
true -> false -> true
```

menghasilkan 2 transisi.

Jika:

```text
m_transition = 2
```

maka dibutuhkan minimal 1 siklus putus-pulih.

Jika:

```text
m_transition = 4
```

maka dibutuhkan minimal 2 siklus putus-pulih.

Dengan parameter fault injection:

```text
down_duration
up_duration
repeat_count
```

durasi fault adalah:

```text
D_fault = repeat_count × (down_duration + up_duration)
```

Jumlah transisi yang dihasilkan kira-kira:

```text
transition_count ≈ 2 × repeat_count
```

Karena itu:

```text
repeat_count >= ceil(m_transition / 2)
```

---

# S1 - DNS_DEGRADED

## Description

`DNS_DEGRADED` adalah kondisi ketika resolusi DNS masih berhasil, tetapi waktu resolusinya meningkat secara abnormal dibanding kondisi normal jaringan. Event ini bukan DNS outage penuh. Ciri utamanya adalah DNS query tetap sukses, tetapi lambat.

## User Impact

Dari sisi user, koneksi terlihat masih normal: Wi-Fi aktif, ping masih bisa sukses, dan internet tidak sepenuhnya mati. Namun, proses membuka website atau aplikasi terasa lambat, terutama pada fase awal akses. Pengguna dapat merasakan halaman web lama mulai terbuka, aplikasi lambat saat login, atau layanan yang sering melakukan DNS lookup terasa tidak responsif. Koneksi yang sudah terbentuk sebelumnya bisa tetap berjalan normal karena tidak selalu membutuhkan DNS lookup baru.

## Trigger Logic

### Primary Trigger

```text
Trigger DNS_DEGRADED jika:
  dns_success(target) == true
  dns_latency_ms(target) >= T_dns_latency(target)
  confirm_consecutive == N_dns
```

- `dns_success(target) == true` diperlukan karena event ini secara definisi adalah DNS lambat, bukan DNS gagal. Kalau DNS query timeout atau gagal, event diarahkan ke S2.
- `T_dns_latency(target)` adalah threshold DNS latency untuk target tersebut. Threshold diambil dari preliminary test:

```text
T_dns_latency(target) = P99(dns_latency_ms normal untuk target tersebut | dns_success == true)
```

- `N_dns` adalah jumlah sampel berturut-turut yang harus melewati threshold. Nilai `N_dns` ditentukan dari hasil uji kandidat `N_dns = 1, 2, 3, 4`, lalu dipilih nilai terkecil yang menghasilkan FAR rendah pada data normal dan MTTD rendah pada fault injection S1.

### Supporting Trigger

```text
wifi_up == true
ping.success == true
affected_scope = internal | external | all
```

- `wifi_up == true` memastikan event bukan akibat Wi-Fi disconnect.
- `ping.success == true` memastikan IP reachability masih hidup.
- `affected_scope` ditentukan berdasarkan target yang memenuhi primary trigger:

```text
jika hanya target internal memenuhi primary trigger:
  affected_scope = internal

jika hanya target external memenuhi primary trigger:
  affected_scope = external

jika target internal dan external sama-sama memenuhi primary trigger:
  affected_scope = all
```

---

# S2 - DNS_TIMEOUT_BURST

## Description

`DNS_TIMEOUT_BURST` adalah kondisi ketika query DNS gagal atau mengalami timeout beberapa kali dalam sliding window. Event ini berbeda dari `DNS_DEGRADED` karena masalah utamanya bukan DNS yang lambat, tetapi DNS yang tidak berhasil memberikan respons.

Event ini dianggap DNS-specific jika Wi-Fi masih aktif dan IP reachability masih tersedia.

## User Impact

Dari sisi user, perangkat masih terlihat tersambung ke Wi-Fi dan beberapa koneksi yang sudah terbentuk sebelumnya mungkin tetap berjalan. Namun, layanan baru yang membutuhkan DNS lookup dapat gagal dibuka. Browser dapat menampilkan DNS error, aplikasi gagal login, dan layanan berbasis domain tidak dapat diakses. Gejala ini dapat terlihat tidak konsisten karena sebagian domain mungkin masih bisa diakses jika hasil DNS sebelumnya masih tersimpan di cache.

## Trigger Logic

### Primary Trigger

```text
Hitung dalam sliding window W_dns:
  dns_sample_count(scope) >= n_dns
  dns_fail_count(scope) = jumlah dns_success == false

Trigger DNS_TIMEOUT_BURST jika:
  dns_fail_count(scope) >= m_dns
```

- `dns_sample_count(scope) >= n_dns` memastikan jumlah sampel dalam window cukup untuk dihitung.
- `dns_fail_count(scope)` adalah jumlah DNS query yang gagal dalam window.
- `n_dns` adalah jumlah minimum sampel DNS dalam window. Nilai awal yang digunakan adalah minimal 10 sampel agar rasio failure tidak terlalu kasar.
- `m_dns` adalah jumlah minimum DNS failure dalam window. Nilai `m_dns` ditentukan dari pengujian kandidat pada data normal dan fault injection S2.

Penentuan `m_dns`:

```text
1. Pilih kandidat n_dns, misalnya 10, 15, 20.
2. Untuk setiap n_dns, uji kandidat m_dns.
3. Hitung FAR pada data normal.
4. Hitung MTTD dan recall pada fault injection S2.
5. Pilih m_dns terkecil yang menghasilkan FAR rendah dan MTTD rendah.
```

Batas minimum:

```text
m_dns >= 2
```

Satu DNS failure tidak langsung dianggap sebagai `DNS_TIMEOUT_BURST`.

### Supporting Trigger

```text
wifi_up == true
ping.success == true
affected_scope = internal | external | all
```

- `wifi_up == true` memastikan event bukan akibat Wi-Fi disconnect.
- `ping.success == true` memastikan IP reachability masih tersedia. Jika ping juga gagal, maka masalahnya tidak diklasifikasikan sebagai DNS-specific timeout.
- `affected_scope` ditentukan berdasarkan target DNS yang gagal dalam window:

```text
jika hanya target internal memenuhi primary trigger:
  affected_scope = internal

jika hanya target external memenuhi primary trigger:
  affected_scope = external

jika target internal dan external sama-sama memenuhi primary trigger:
  affected_scope = all
```

---

# S3 - LOSS_BURST

## Description

`LOSS_BURST` adalah kondisi ketika packet loss meningkat dalam sliding window saat Wi-Fi masih aktif. Event ini merepresentasikan degradasi konektivitas transien, bukan kondisi disconnect permanen.

Ciri utamanya adalah sebagian ping berhasil, tetapi sebagian lainnya gagal dalam window yang sama.

## User Impact

Dari sisi user, koneksi terasa tidak stabil. Sebagian request berhasil, sebagian gagal. Pengguna dapat mengalami halaman web yang berhenti di tengah proses loading, video call freeze sesaat, audio putus-putus, aplikasi melakukan retry, atau game dan remote session terasa patah-patah. Masalah ini sering dirasakan sebagai internet yang kadang jalan dan kadang tidak.

## Trigger Logic

### Primary Trigger

```text
Hitung dalam sliding window W_ping:
  ping_sample_count >= n_ping
  ping_fail_count = jumlah ping.success == false

Trigger LOSS_BURST jika:
  ping_fail_count >= m_ping
```

- `ping_sample_count >= n_ping` memastikan jumlah sampel ping dalam window cukup untuk dihitung.
- `ping_fail_count` adalah jumlah ping yang gagal dalam window.
- `n_ping` adalah jumlah minimum sampel ping dalam window. Nilai awal yang digunakan adalah minimal 20 sampel agar resolusi loss mencapai 5%.
- `m_ping` adalah jumlah minimum ping failure dalam window. Nilai `m_ping` ditentukan dari pengujian kandidat pada data normal dan fault injection S3.

Penentuan `m_ping`:

```text
1. Pilih kandidat n_ping, misalnya 20, 30, 40.
2. Untuk setiap n_ping, uji kandidat m_ping.
3. Hitung FAR pada data normal.
4. Hitung MTTD dan recall pada fault injection S3.
5. Pilih m_ping terkecil yang menghasilkan FAR rendah dan MTTD rendah.
```

Batas minimum:

```text
m_ping >= 2
```

Satu ping gagal tidak langsung dianggap sebagai `LOSS_BURST`.

### Supporting Trigger

```text
wifi_up == true
wifi_up_count(W_ping) == ping_sample_count
```

- `wifi_up == true` memastikan perangkat sedang terhubung secara interface-level.
- `wifi_up_count(W_ping) == ping_sample_count` memastikan Wi-Fi tetap up sepanjang window. Jika Wi-Fi ikut down dalam window, event lebih tepat diarahkan ke S6 `CONNECTIVITY_FLAP`.

---

# S4 - HIGH_RTT

## Description

`HIGH_RTT` adalah kondisi ketika round-trip time meningkat secara abnormal dibanding kondisi normal jaringan, sementara packet loss tetap rendah. Event ini merepresentasikan degradasi latency, bukan outage atau packet loss burst.

Ciri utamanya adalah koneksi masih tersedia, tetapi waktu respons jaringan meningkat.

## User Impact

Dari sisi user, koneksi masih berjalan tetapi terasa lambat. Halaman web membutuhkan waktu lebih lama untuk merespons, login aplikasi terasa tertunda, video call mengalami delay, remote desktop terasa berat, dan aplikasi interaktif menjadi kurang responsif. Berbeda dengan `LOSS_BURST`, gejala utama pada `HIGH_RTT` bukan request gagal, tetapi respons yang terlambat.

## Trigger Logic

### Primary Trigger

```text
Trigger HIGH_RTT jika:
  rtt_avg_ms(target) >= T_rtt(target)
  confirm_consecutive == N_rtt
```

- `rtt_avg_ms(target)` adalah rata-rata RTT ke target tertentu.
- `T_rtt(target)` adalah threshold RTT untuk target tersebut. Threshold diambil dari preliminary test:

```text
T_rtt(target) = P99(rtt_avg_ms normal untuk target tersebut)
```

- `N_rtt` adalah jumlah sampel berturut-turut yang harus melewati threshold. Nilai `N_rtt` ditentukan dari hasil uji kandidat `N_rtt = 1, 2, 3, 4`, lalu dipilih nilai terkecil yang menghasilkan FAR rendah pada data normal dan MTTD rendah pada fault injection S4.

### Supporting Trigger

```text
wifi_up == true
ping_fail_count(W_ping) < m_ping
```

- `wifi_up == true` memastikan event bukan akibat Wi-Fi disconnect.
- `ping_fail_count(W_ping) < m_ping` memastikan kondisi ini bukan packet loss burst. Jika `ping_fail_count(W_ping) >= m_ping`, maka event lebih tepat diarahkan ke S3 `LOSS_BURST`.

---

# S5 - HTTP_SLOW

## Description

`HTTP_SLOW` adalah kondisi ketika transaksi HTTP menjadi lambat atau gagal pada layer aplikasi, sementara konektivitas dasar, DNS, RTT umum, dan packet loss masih berada dalam kondisi normal.

Event ini berfokus pada pengalaman akses aplikasi, bukan bandwidth mentah dan bukan gangguan DNS/RTT/loss yang berdampak ke HTTP.

## User Impact

Dari sisi user, aplikasi atau website terasa lambat meskipun koneksi terlihat aktif. Halaman web lama menampilkan konten pertama, login aplikasi tertunda, request API lambat, atau layanan tertentu mengalami timeout. Masalah ini bisa terjadi hanya pada target tertentu, misalnya layanan internal lambat sementara layanan eksternal tetap normal.

## Trigger Logic

### Primary Trigger

```text
Trigger HTTP_SLOW jika salah satu kondisi berikut terpenuhi:
  http_total_ms(url) >= T_http_total(url)
  atau http_ttfb_ms(url) >= T_http_ttfb(url)
  atau curl_rc != 0 dan curl_rc != 6
  atau http_status not in EXPECTED_HTTP_STATUS(url)

  confirm_consecutive == N_http
```

- `http_total_ms(url)` adalah total durasi transaksi HTTP ke URL target.
- `T_http_total(url)` adalah threshold HTTP total time untuk URL tersebut:

```text
T_http_total(url) = P99(http_total_ms normal untuk URL tersebut | curl_rc == 0 dan http_status in EXPECTED_HTTP_STATUS)
```

- `http_ttfb_ms(url)` adalah waktu hingga byte pertama diterima.
- `T_http_ttfb(url)` adalah threshold TTFB untuk URL tersebut:

```text
T_http_ttfb(url) = P99(http_ttfb_ms normal untuk URL tersebut | curl_rc == 0 dan http_status in EXPECTED_HTTP_STATUS)
```

- `curl_rc != 0 dan curl_rc != 6` digunakan untuk mendeteksi HTTP check yang gagal, tetapi bukan karena DNS resolution failure. `curl_rc == 6` diarahkan ke DNS problem, bukan `HTTP_SLOW`.
- `http_status not in EXPECTED_HTTP_STATUS(url)` digunakan jika server mengembalikan status di luar status yang diharapkan. `EXPECTED_HTTP_STATUS(url)` harus dikonfigurasi per URL.
- `N_http` adalah jumlah HTTP check berturut-turut yang harus memenuhi primary trigger. Nilai `N_http` ditentukan dari hasil uji kandidat `N_http = 1, 2, 3`, lalu dipilih nilai terkecil yang menghasilkan FAR rendah pada data normal dan MTTD rendah pada fault injection S5.

### Supporting Trigger

```text
wifi_connected == true
dns_success(url_hostname) == true
dns_latency_ms(url_hostname) < T_dns_latency(url_hostname)
rtt_avg_ms(target) < T_rtt(target)
ping_fail_count(W_ping) < m_ping
affected_scope = internal | external | all
```

- `wifi_connected == true` memastikan event bukan akibat Wi-Fi disconnect.
- `dns_success(url_hostname) == true` memastikan hostname berhasil di-resolve. Jika DNS gagal, event diarahkan ke S2.
- `dns_latency_ms(url_hostname) < T_dns_latency(url_hostname)` memastikan HTTP slow bukan akibat DNS degraded. Jika DNS latency melewati threshold, event diarahkan ke S1.
- `rtt_avg_ms(target) < T_rtt(target)` memastikan HTTP slow bukan akibat latency umum. Jika RTT melewati threshold, event diarahkan ke S4.
- `ping_fail_count(W_ping) < m_ping` memastikan HTTP slow bukan akibat packet loss burst. Jika packet loss memenuhi trigger S3, event diarahkan ke S3.
- `affected_scope` ditentukan berdasarkan URL yang memenuhi primary trigger:

```text
jika hanya URL internal memenuhi primary trigger:
  affected_scope = internal

jika hanya URL external memenuhi primary trigger:
  affected_scope = external

jika URL internal dan external sama-sama memenuhi primary trigger:
  affected_scope = all
```

---

# S6 - CONNECTIVITY_FLAP

## Description

`CONNECTIVITY_FLAP` adalah kondisi ketika konektivitas Wi-Fi atau IP reachability berubah berulang antara reachable dan unreachable dalam window tertentu.

Pada dokumen ini, `CONNECTIVITY_FLAP` dibatasi untuk flap pada layer Wi-Fi atau IP reachability. DNS failure ditangani oleh S2, sedangkan HTTP intermittent failure ditangani oleh S5. Pembatasan ini dibuat agar event S6 tidak tumpang tindih dengan DNS dan HTTP event.

## User Impact

Dari sisi user, koneksi terasa putus-nyambung. Aplikasi berulang kali reconnect, sesi web gagal atau terputus, video call freeze lalu pulih, login aplikasi gagal secara intermittent, dan layanan real-time menjadi tidak stabil. Berbeda dari outage penuh, flap biasanya terasa sebagai gangguan yang muncul dan hilang dalam waktu singkat.

## Trigger Logic

### Primary Trigger

```text
Definisikan:
  connectivity_ok = wifi_up == true dan ping.success == true

Hitung dalam window W_flap:
  sample_count(W_flap) >= n_flap
  state_transition_count(connectivity_ok) = jumlah perubahan true/false

Trigger CONNECTIVITY_FLAP jika:
  state_transition_count(connectivity_ok) >= m_transition
```

- `connectivity_ok` adalah state utama untuk menentukan apakah konektivitas Wi-Fi/IP sedang tersedia.
- `state_transition_count(connectivity_ok)` adalah jumlah perubahan state dalam window.

Contoh:

```text
true -> false = 1 transition
false -> true = 1 transition
```

- `m_transition` adalah jumlah minimum transisi agar event dianggap flap.
- Batas minimum:

```text
m_transition >= 2
```

Dua transisi berarti satu siklus putus-pulih:

```text
true -> false -> true
```

Jika ingin definisi flap yang lebih ketat, kandidat `m_transition = 3` atau `4` dapat diuji.

Penentuan `m_transition`:

```text
1. Pilih kandidat W_flap, misalnya 20 detik dan 30 detik.
2. Pilih kandidat m_transition, misalnya 2, 3, 4.
3. Hitung FAR pada data normal.
4. Hitung MTTD dan recall pada fault injection S6.
5. Pilih kombinasi W_flap dan m_transition yang menghasilkan FAR rendah dan MTTD rendah.
```

### Supporting Trigger

```text
suspected_layer = wifi_link | upstream
```

`suspected_layer` ditentukan dari pola transisi:

```text
jika state_transition_count(wifi_up, W_flap) >= m_transition:
  suspected_layer = wifi_link

jika state_transition_count(wifi_up, W_flap) < m_transition
dan state_transition_count(ping.success, W_flap) >= m_transition:
  suspected_layer = upstream
```

- `suspected_layer = wifi_link` berarti flap terjadi pada status Wi-Fi.
- `suspected_layer = upstream` berarti Wi-Fi tetap stabil, tetapi IP reachability berubah-ubah.
