# README Skema Fault Injection Micro-UXI

Dokumen ini menjelaskan skema fault injection untuk mengevaluasi sistem Micro-UXI sebagai *network experience black-box event recorder*. Fokus dokumen ini adalah enam skenario utama, yaitu S1–S6:

1. S1 — `DNS_DEGRADED`
2. S2 — `DNS_TIMEOUT_BURST`
3. S3 — `LOSS_BURST`
4. S4 — `HIGH_RTT`
5. S5 — `HTTP_SLOW`
6. S6 — `CONNECTIVITY_FLAP`

Setiap skema berisi tiga bagian utama:

- `Description`: deskripsi event dan batasan klasifikasinya.
- `User Impact`: dampak yang dirasakan dari sisi pengguna.
- `Trigger Logic`: aturan deteksi event, terdiri dari primary trigger dan supporting trigger.

## Prinsip Umum Threshold dan Parameter Trigger

Untuk baseline monitoring statis, threshold numerik diambil dari data normal pada baseline phase. Secara umum:

```text
T_metric = P99(metric_normal)
```

Penentuan threshold menggunakan P99 dilakukan agar nilai threshold merepresentasikan batas atas kondisi normal jaringan. Dengan demikian, nilai di atas threshold dapat dianggap abnormal terhadap kondisi jaringan uji, bukan berdasarkan angka universal.

Untuk metrik numerik seperti DNS latency, RTT, HTTP total time, dan HTTP TTFB, P99 dihitung dari minimal 10.000 sampel data normal jika memungkinkan. Jika keterbatasan waktu atau resource membuat 10.000 sampel tidak tercapai, minimal 1.000 sampel dapat digunakan sebagai batas bawah awal, tetapi hasilnya perlu dinyatakan sebagai baseline awal yang kurang stabil dibanding 10.000 sampel.

Untuk parameter `confirm_consecutive`, nilai N tidak ditentukan secara arbitrer. Kandidat nilai seperti `N = 1, 2, 3, 4` diuji pada data normal dan data fault injection. FAR dihitung dari data normal tanpa fault, sedangkan MTTD dihitung dari data fault injection. Nilai akhir dipilih sebagai nilai terkecil yang menghasilkan FAR rendah dan MTTD tetap rendah.

Untuk metrik berbasis window seperti failure ratio, packet loss ratio, dan state transition count, data mentah diolah terlebih dahulu dalam sliding window. Jumlah sampel dalam window harus cukup agar rasio tidak terlalu kasar. Secara praktis, minimal 10 sampel digunakan untuk failure ratio, sedangkan packet loss disarankan menggunakan 20 sampel atau lebih agar resolusi loss lebih halus.

---

# S1 - DNS_DEGRADED

## Description

`DNS_DEGRADED` adalah kondisi ketika resolusi DNS masih berhasil, tetapi waktu resolusinya meningkat secara abnormal dibanding kondisi normal jaringan. Event ini bukan DNS outage penuh. Ciri utamanya adalah DNS query tetap sukses, tetapi lambat.

## User Impact

Dari sisi user, koneksi terlihat masih normal: Wi-Fi aktif, ping masih bisa sukses, dan internet tidak sepenuhnya mati. Namun, proses membuka website atau aplikasi terasa lambat, terutama pada fase awal akses. Pengguna dapat merasakan halaman web “lama mulai terbuka”, aplikasi lambat saat login, atau layanan yang sering melakukan DNS lookup terasa tidak responsif. Koneksi yang sudah terbentuk sebelumnya bisa tetap berjalan normal karena tidak selalu membutuhkan DNS lookup baru.

## Trigger Logic

### Primary Trigger

```text
Trigger DNS_DEGRADED jika:
  dns_success == true
  dns_latency_ms >= T_dns_latency
  confirm_consecutive == N_dns
```

- `dns_success == true` diperlukan karena event ini secara definisi adalah DNS lambat, bukan DNS gagal. Kalau DNS query timeout atau gagal, event harus diarahkan ke S2.
- `T_dns_latency` adalah threshold DNS latency. Untuk baseline monitoring statis, nilai ini diambil dari baseline phase:

```text
T_dns_latency = P99(dns_latency_ms normal | dns_success == true)
```

Penentuan threshold untuk `dns_latency_ms` diambil menggunakan P99 dari minimal 10.000 sampel data jaringan.

- `N_dns` adalah jumlah sampel berturut-turut yang harus melewati threshold. Nilai `N_dns` ditentukan dari hasil uji kandidat `N_dns = 1, 2, 3, 4`, lalu dipilih nilai terkecil yang menghasilkan FAR (False Alarm Rate) rendah pada data normal dan MTTD (Mean Time To Detect) rendah pada fault injection S1.

### Supporting Trigger

```text
wifi_up == true
ping.success == true
affected_scope = internal | external | all
```

- `wifi_up == true` memastikan event bukan akibat Wi-Fi disconnect.
- `ping.success == true` memastikan IP reachability masih hidup.
- `affected_scope` digunakan untuk membedakan apakah degradasi DNS hanya terjadi pada target internal, eksternal, atau seluruh target.

---

# S2 - DNS_TIMEOUT_BURST

## Description

`DNS_TIMEOUT_BURST` adalah kondisi ketika query DNS gagal atau mengalami timeout secara beruntun dalam jendela waktu pendek. Event ini berbeda dari `DNS_DEGRADED` karena masalah utamanya bukan DNS yang lambat, tetapi DNS yang tidak berhasil memberikan respons. Event ini dianggap DNS-specific apabila Wi-Fi masih aktif dan konektivitas IP masih tersedia, tetapi proses resolusi nama gagal.

## User Impact

Dari sisi user, perangkat masih terlihat tersambung ke Wi-Fi dan beberapa koneksi yang sudah terbentuk sebelumnya mungkin tetap berjalan. Namun, layanan baru yang membutuhkan DNS lookup dapat gagal dibuka. Browser bisa menampilkan DNS error, aplikasi gagal login, dan layanan berbasis domain tidak dapat diakses. Gejala ini dapat terlihat tidak konsisten karena beberapa domain mungkin masih bisa diakses jika hasil DNS sebelumnya masih tersimpan di cache.

## Trigger Logic

### Primary Trigger

```text
Trigger DNS_TIMEOUT_BURST jika:
  dns_success == false
  dns_fail_count >= m_dns dalam n_dns sampel
```

atau dalam bentuk rasio:

```text
Trigger DNS_TIMEOUT_BURST jika:
  dns_fail_ratio >= T_dns_fail_ratio
```

- `dns_success == false` diperlukan karena event ini secara definisi adalah DNS gagal atau timeout, bukan DNS lambat. Jika DNS masih sukses tetapi lambat, event harus diarahkan ke S1.
- `dns_fail_count` adalah jumlah query DNS yang gagal dalam sliding window. Parameter ini digunakan agar satu DNS failure tunggal tidak langsung dianggap sebagai event.
- `n_dns` adalah jumlah sampel DNS dalam window. Nilai minimal yang digunakan adalah 10 sampel agar rasio kegagalan tidak terlalu kasar. Jika `n_dns = 10`, maka 1 DNS failure setara 10%. Jika `n_dns = 20`, maka 1 DNS failure setara 5%.
- `m_dns` adalah jumlah minimum DNS failure yang diperlukan untuk memicu event. Nilai `m_dns` ditentukan dari hasil pengujian kandidat, misalnya `m_dns = 2, 3, 4`, lalu dipilih nilai yang menghasilkan FAR rendah pada data normal dan MTTD rendah pada fault injection S2.
- `T_dns_fail_ratio` adalah threshold rasio kegagalan DNS. Untuk baseline monitoring statis, nilai ini diambil dari baseline phase:

```text
T_dns_fail_ratio = P99(dns_fail_ratio normal)
```

Penentuan threshold untuk `dns_fail_ratio` diambil menggunakan P99 dari data normal berbasis sliding window. Data mentah `dns_success` tidak langsung dipakai satu per satu, tetapi diolah terlebih dahulu menjadi rasio kegagalan dalam window.

### Supporting Trigger

```text
wifi_up == true
ping.success == true
affected_scope = internal | external | all
```

- `wifi_up == true` memastikan event bukan akibat Wi-Fi disconnect.
- `ping.success == true` memastikan konektivitas IP masih tersedia. Jika ping juga gagal, maka masalahnya kemungkinan bukan DNS-specific, melainkan packet loss, upstream outage, atau connectivity flap.
- `affected_scope` digunakan untuk membedakan apakah DNS timeout terjadi pada target internal, eksternal, atau seluruh target.

---

# S3 - LOSS_BURST

## Description

`LOSS_BURST` adalah kondisi ketika packet loss meningkat secara signifikan dalam interval pendek saat koneksi Wi-Fi masih aktif. Event ini merepresentasikan degradasi konektivitas yang bersifat transien, bukan kondisi disconnect permanen. Ciri utamanya adalah sebagian paket berhasil dikirim, tetapi sebagian lainnya gagal dalam waktu berdekatan.

## User Impact

Dari sisi user, koneksi terasa tidak stabil. Sebagian request berhasil, sebagian gagal. Pengguna dapat mengalami halaman web yang berhenti di tengah proses loading, video call yang freeze sesaat, audio yang putus-putus, aplikasi yang melakukan retry, atau game dan remote session yang terasa patah-patah. Masalah ini sering dirasakan sebagai internet yang “kadang jalan, kadang tidak”.

## Trigger Logic

### Primary Trigger

```text
Trigger LOSS_BURST jika:
  ping_loss_pct_window >= T_loss
```

atau dalam bentuk count:

```text
Trigger LOSS_BURST jika:
  ping_fail_count >= m_ping dalam n_ping sampel
```

- `ping_loss_pct_window` adalah persentase packet loss dalam sliding window. Parameter ini diperlukan karena satu ping gagal tidak cukup untuk menyatakan adanya packet loss burst.
- `ping_fail_count` adalah jumlah ping yang gagal dalam window.
- `n_ping` adalah jumlah sampel ping dalam window. Untuk packet loss, nilai awal yang lebih disarankan adalah 20 sampel karena memberikan resolusi 5%. Jika `n_ping = 20`, maka 1 ping gagal setara 5%, 2 ping gagal setara 10%, dan 4 ping gagal setara 20%.
- `m_ping` adalah jumlah minimum ping failure yang diperlukan untuk memicu event. Nilai ini ditentukan dari hasil pengujian kandidat, misalnya `m_ping = 2, 3, 4`, lalu dipilih berdasarkan FAR pada data normal dan MTTD pada fault injection S3.
- `T_loss` adalah threshold packet loss. Untuk baseline monitoring statis, nilai ini diambil dari baseline phase:

```text
T_loss = P99(ping_loss_pct_window normal)
```

Penentuan threshold untuk `ping_loss_pct_window` diambil menggunakan P99 dari data normal berbasis sliding window. Threshold tidak diambil dari satu sampel ping, tetapi dari distribusi packet loss dalam window.

### Supporting Trigger

```text
wifi_up == true
dns_success dipantau
http_total_ms / curl_rc dipantau
```

- `wifi_up == true` memastikan event bukan akibat perangkat disconnect dari Wi-Fi.
- `dns_success` dipantau untuk membedakan packet loss dari DNS-specific failure. Jika DNS gagal tetapi ping tetap normal, event lebih mungkin mengarah ke S2.
- `http_total_ms` dan `curl_rc` dipantau untuk melihat apakah packet loss berdampak sampai ke layer aplikasi.

---

# S4 - HIGH_RTT

## Description

`HIGH_RTT` adalah kondisi ketika round-trip time meningkat secara abnormal dibanding kondisi normal jaringan, sementara packet loss tetap rendah. Event ini merepresentasikan degradasi latency, bukan outage atau packet loss burst. Ciri utamanya adalah koneksi masih tersedia, tetapi waktu respons jaringan meningkat.

## User Impact

Dari sisi user, koneksi masih berjalan tetapi terasa lambat. Halaman web membutuhkan waktu lebih lama untuk merespons, login aplikasi terasa tertunda, video call mengalami delay, remote desktop terasa berat, dan aplikasi interaktif menjadi kurang responsif. Berbeda dengan `LOSS_BURST`, gejala utama pada `HIGH_RTT` bukan request gagal, tetapi respons yang terlambat.

## Trigger Logic

### Primary Trigger

```text
Trigger HIGH_RTT jika:
  rtt_avg_ms >= T_rtt
  loss_pct < T_loss_guard
  confirm_consecutive == N_rtt
```

- `rtt_avg_ms >= T_rtt` diperlukan karena event ini berfokus pada kenaikan latency. Untuk baseline monitoring statis, nilai threshold diambil dari baseline phase:

```text
T_rtt = P99(rtt_avg_ms normal)
```

Penentuan threshold untuk `rtt_avg_ms` diambil menggunakan P99 dari minimal 10.000 sampel data jaringan. Threshold sebaiknya dihitung per target, misalnya gateway, target internal, dan target eksternal, karena masing-masing memiliki karakteristik RTT normal yang berbeda.

- `loss_pct < T_loss_guard` diperlukan untuk memastikan event ini bukan packet-loss-dominated event. Jika RTT tinggi tetapi packet loss juga tinggi, maka event lebih tepat diarahkan ke S3 atau mixed event.
- `T_loss_guard` adalah batas maksimum packet loss agar event masih dapat dikategorikan sebagai `HIGH_RTT`. Nilainya dapat diambil dari baseline phase:

```text
T_loss_guard = P99(loss_pct_window normal)
```

atau ditentukan sebagai batas operasional, misalnya loss harus tetap rendah agar event dianggap pure latency issue.

- `N_rtt` adalah jumlah sampel berturut-turut yang harus melewati threshold. Nilai `N_rtt` ditentukan dari hasil uji kandidat `N_rtt = 1, 2, 3, 4`, lalu dipilih nilai terkecil yang menghasilkan FAR rendah pada data normal dan MTTD rendah pada fault injection S4.

### Supporting Trigger

```text
rtt_mdev_ms
http_ttfb_ms
wifi_rssi_dbm
wifi_bssid
```

- `rtt_mdev_ms` digunakan untuk melihat variasi RTT atau jitter.
- `http_ttfb_ms` digunakan untuk melihat apakah kenaikan RTT berdampak ke layer aplikasi.
- `wifi_rssi_dbm` digunakan untuk membantu diagnosis apakah latency tinggi berkaitan dengan kualitas sinyal Wi-Fi.
- `wifi_bssid` dapat membantu melihat apakah terjadi roaming atau perpindahan access point yang memengaruhi latency.

---

# S5 - HTTP_SLOW

## Description

`HTTP_SLOW` adalah kondisi ketika transaksi HTTP menjadi lambat atau gagal. Event ini diamati dari metrik application-layer seperti `http_total_ms`, `http_ttfb_ms`, `curl_rc`, dan `http_status`. Fokus event ini adalah pengalaman akses aplikasi, bukan bandwidth mentah. Sebuah layanan dapat mengalami HTTP slow meskipun Wi-Fi, ping, dan DNS terlihat normal.

## User Impact

Dari sisi user, aplikasi atau website terasa lambat meskipun koneksi terlihat aktif. Halaman web lama menampilkan konten pertama, login aplikasi tertunda, request API lambat, atau layanan tertentu mengalami timeout. Masalah ini bisa terjadi hanya pada target tertentu, misalnya layanan internal lambat sementara layanan eksternal tetap normal.

## Trigger Logic

### Primary Trigger

```text
Trigger HTTP_SLOW jika salah satu kondisi berikut terpenuhi:
  http_total_ms >= T_http_total
  atau http_ttfb_ms >= T_http_ttfb
  atau curl_rc != 0
  atau http_status di luar expected range

  confirm_consecutive == N_http
```

- `http_total_ms >= T_http_total` digunakan untuk mendeteksi transaksi HTTP yang total durasinya lebih lambat dari kondisi normal. Untuk baseline monitoring statis, threshold diambil dari baseline phase:

```text
T_http_total = P99(http_total_ms normal)
```

Penentuan threshold untuk `http_total_ms` diambil menggunakan P99 dari minimal 10.000 sampel data jaringan untuk masing-masing URL target.

- `http_ttfb_ms >= T_http_ttfb` digunakan untuk mendeteksi keterlambatan hingga byte pertama diterima. Ini membantu mengidentifikasi kelambatan pada response server atau aplikasi. Threshold diambil dari baseline phase:

```text
T_http_ttfb = P99(http_ttfb_ms normal)
```

- `curl_rc != 0` adalah categorical trigger yang menunjukkan HTTP check gagal, misalnya karena timeout, connection refused, atau TLS failure.
- `http_status di luar expected range` adalah categorical trigger yang menunjukkan response HTTP tidak sesuai harapan. Expected range biasanya 2xx atau 3xx, tergantung target uji.
- `N_http` adalah jumlah HTTP check berturut-turut yang harus memenuhi kondisi trigger. Nilai `N_http` ditentukan dari hasil uji kandidat `N_http = 1, 2, 3`, lalu dipilih berdasarkan FAR pada data normal dan MTTD pada fault injection S5. Kandidat `N_http` tidak perlu terlalu besar karena HTTP check biasanya memiliki interval sampling lebih lambat dibanding ping atau DNS.

### Supporting Trigger

```text
wifi_connected == true
dns_success dipantau
dns_latency_ms dipantau
rtt_avg_ms dipantau
loss_pct dipantau
affected_scope = internal | external | all
```

- `wifi_connected == true` memastikan event bukan akibat Wi-Fi disconnect.
- `dns_success` dan `dns_latency_ms` dipantau untuk membedakan HTTP slow dari DNS problem. Jika DNS lambat, event lebih tepat diarahkan ke S1.
- `rtt_avg_ms` dipantau untuk membedakan HTTP slow dari latency umum. Jika RTT umum tinggi, event lebih tepat diarahkan ke S4.
- `loss_pct` dipantau untuk membedakan HTTP slow dari packet loss. Jika loss tinggi, event lebih tepat diarahkan ke S3.
- `affected_scope` digunakan untuk membedakan apakah HTTP slow terjadi pada target internal, eksternal, atau seluruh target.

---

# S6 - CONNECTIVITY_FLAP

## Description

`CONNECTIVITY_FLAP` adalah kondisi ketika konektivitas berubah berulang antara reachable dan unreachable dalam jendela waktu pendek. Event ini tidak terbatas pada Wi-Fi disconnect. Wi-Fi link flap hanya salah satu kemungkinan penyebab; upstream connectivity flap, DNS-layer flap, atau application-layer flap juga dapat terjadi ketika Wi-Fi masih connected.

## User Impact

Dari sisi user, koneksi terasa putus-nyambung. Aplikasi berulang kali reconnect, sesi web gagal atau terputus, video call freeze lalu pulih, login aplikasi gagal secara intermittent, dan layanan real-time menjadi tidak stabil. Berbeda dari outage penuh, flap biasanya terasa sebagai gangguan yang muncul dan hilang dalam waktu singkat.

## Trigger Logic

### Primary Trigger

```text
Trigger CONNECTIVITY_FLAP jika:
  state_transition_count(connectivity_ok) >= T_transition
  dalam window W_flap
```

- `connectivity_ok` adalah state yang menunjukkan apakah konektivitas dianggap tersedia. State ini dapat dibentuk dari beberapa indikator, misalnya `wifi_up`, `ping.success`, `dns_success`, dan `http_status`.
- `state_transition_count(connectivity_ok)` adalah jumlah perubahan state dalam window. Contoh:

```text
true -> false = 1 transition
false -> true = 1 transition
```

- `T_transition` adalah jumlah minimum transisi agar event dianggap flap. Nilai minimum yang dapat digunakan adalah:

```text
T_transition = 2
```

Nilai ini merepresentasikan satu siklus putus-pulih, yaitu:

```text
true -> false -> true
```

Jika ingin definisi flap yang lebih ketat, dapat digunakan:

```text
T_transition = 4
```

Nilai ini merepresentasikan dua siklus putus-pulih penuh.

- `W_flap` adalah window waktu untuk menghitung jumlah transisi. Nilai ini ditentukan berdasarkan durasi pola flap yang ingin dideteksi. Jika fault injection menggunakan `down_duration = 2–10 detik` dan `up_duration = 2–10 detik`, maka satu siklus flap berlangsung sekitar 4–20 detik. Karena itu, window 20–30 detik dapat digunakan sebagai kandidat awal.
- Nilai final `T_transition` dan `W_flap` ditentukan dari hasil uji kandidat. FAR dihitung pada data normal, sedangkan MTTD dan recall dihitung pada fault injection S6.

### Supporting Trigger

```text
wifi_up
ping.success
dns_success
http_status / curl_rc
wifi_bssid
wifi_rssi_dbm
suspected_layer = wifi_link | upstream | dns | application
```

- `wifi_up` digunakan untuk melihat apakah flap terjadi pada layer Wi-Fi.
- `ping.success` digunakan untuk melihat apakah IP reachability ikut berubah.
- `dns_success` digunakan untuk melihat apakah flap hanya terjadi pada layer DNS.
- `http_status` dan `curl_rc` digunakan untuk melihat apakah flap berdampak ke application reachability.
- `wifi_bssid` digunakan untuk melihat kemungkinan roaming atau perpindahan access point.
- `wifi_rssi_dbm` digunakan untuk melihat apakah flap berkaitan dengan kualitas sinyal Wi-Fi.
- `suspected_layer` digunakan untuk mengklasifikasikan sumber flap berdasarkan pola metrik.
