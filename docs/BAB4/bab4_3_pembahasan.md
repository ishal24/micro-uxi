### 4.3 Pembahasan

Bagian ini menyajikan analisis mendalam (*discussion*) mengenai temuan-temuan penting yang diperoleh dari hasil pengujian sistem deteksi Micro-UXI. Pembahasan dibagi menjadi tiga fokus utama: (1) evaluasi perbandingan performa deteksi antara Metode Baseline dan Metode Event-Driven beserta *trade-off* yang terjadi, (2) kelayakan operasional sistem berdasarkan karakteristik beban kerja (*overhead*) perangkat, serta (3) signifikansi dan kelengkapan informasi berkas bukti (*evidence bundle*) untuk mendukung analisis akar masalah (*root cause analysis*).

---

#### 4.3.1 Analisis Perbandingan Performa Deteksi

Berdasarkan hasil rekapitulasi performa pada Tabel 4.7, terdapat perbedaan karakteristik yang signifikan antara Metode Baseline (Threshold Statis) dan Metode Event-Driven (Threshold Dinamis EWMA). Secara umum, kedua metode menunjukkan keunggulan yang kontras pada dimensi akurasi deteksi (*precision/recall*) versus kecepatan respon (*MTTD*).

##### 1. Trade-off Akurasi vs. Kecepatan Deteksi
Metode Baseline mencatat performa akurasi yang hampir sempurna dengan rata-rata Precision **100,0%**, Recall **95,0%**, dan F1-Score **0,973**. Keunggulan ini disebabkan oleh penentuan nilai threshold statis ($T_{static}$) menggunakan persentil ke-99 ($P_{99}$) dari data empiris uji pendahuluan yang stabil. Ambang batas yang ditempatkan cukup tinggi di atas rata-rata fluktuasi normal ini berhasil mengeliminasi munculnya alarm palsu (*False Positive = 0*). Namun, ketahanan terhadap alarm palsu ini harus dibayar dengan keterlambatan respon deteksi, di mana rata-rata MTTD Baseline mencapai **21,83 detik**.

Sebaliknya, Metode Event-Driven dirancang untuk mendeteksi deviasi secara adaptif dan terbukti berhasil memangkas waktu deteksi secara signifikan dengan rata-rata MTTD **19,24 detik** (lebih cepat ~12% secara akumulatif, bahkan pada skenario S4 dan S5 terjadi peningkatan kecepatan deteksi masing-masing sebesar 24% dan 34%). Kecepatan ini diperoleh karena algoritma EWMA secara kontinu memperbarui rata-rata bergerak ($\mu_t$) dan standar deviasi ($s_t$), membuat batas deteksi dinamis ($T_{dynamic}$) berada sangat dekat dengan pola metrik terkini. Imbasnya, deviasi kecil sekalipun akibat injeksi gangguan langsung memicu alarm tanpa harus menunggu metrik menembus batas ekstrem $P_{99}$.

##### 2. Fenomena False Positive pada Event-Driven (Kasus S1)
Meskipun responsif, Metode Event-Driven mengalami kerentanan terhadap alarm palsu pada metrik yang memiliki varians normal sangat rendah. Kasus paling menonjol terjadi pada skenario **S1 (DNS Degraded)**, di mana metode Event-Driven mencatat **10 kali False Positive**, yang menurunkan nilai Precision menjadi **75,0%** dan F1-Score menjadi **0,857**. 

Secara teknis, latensi DNS pada kondisi normal sangat stabil dengan rata-rata sekitar 90–100 ms dan standar deviasi yang sangat kecil. Ketika standar deviasi ($s_t$) bernilai sangat rendah, batas deteksi dinamis EWMA ($T_{dynamic} = \mu_{t-1} + 3 \cdot s_{t-1}$) akan bergeser sangat rendah mendekati rata-rata (misalnya di kisaran 120 ms). Akibatnya, lonjakan latensi kueri tunggal yang wajar (seperti 130 ms akibat antrean pemrosesan server resolver lokal yang bersifat sesaat) akan langsung dianggap sebagai anomali oleh detektor. Sebaliknya, metode Baseline terbebas dari masalah ini karena threshold statisnya tetap terkunci pada 243 ms. Hal ini menunjukkan perlunya penerapan *variance floor* (batas standar deviasi minimum) pada implementasi EWMA di masa depan untuk mencegah threshold dinamis menyusut terlalu ekstrem.

##### 3. Efektivitas Deteksi Pola Transisi (S2, S3, dan S6)
*   **Pada S2 (DNS Timeout Burst)** dan **S3 (Loss Burst)**, sistem mengandalkan aturan logika *m-of-n* pada jendela geser. Pada S2, Baseline lebih unggul karena kegagalan resolusi bersifat biner mutlak (sukses/gagal), sehingga aturan 3-of-10 bekerja optimal dengan threshold statis. Namun pada S3, Event-Driven mencatat Recall lebih tinggi (90,0% vs 80,0%) karena threshold dinamis mampu beradaptasi mendeteksi pola kehilangan paket 40% yang bercampur dengan *background packet loss* jaringan Wi-Fi lokal.
*   **Pada S6 (Connectivity Flap)**, performa kedua metode sangat berimbang (F1-Score 1,000 pada Baseline dan 0,967 pada Event-Driven). Hal ini menunjukkan bahwa untuk gangguan yang bersifat terputus total secara intermiten (*hard link failure*), perubahan status operasional antarmuka Wi-Fi (`operstate` bernilai `down`) dan kegagalan ping secara berulang merupakan indikator yang sangat tegas, sehingga baik threshold statis maupun dinamis mampu memberikan hasil deteksi yang andal.

---

#### 4.3.2 Analisis Karakteristik Overhead Sistem

Pengukuran beban kerja perangkat pada Tabel 4.8 memverifikasi kelayakan implementasi detektor Micro-UXI pada perangkat dengan sumber daya terbatas (*resource-constrained devices*), seperti klien berbasis sistem *embedded* atau perangkat IoT.

##### 1. Efisiensi Komputasi CPU
Utilisasi CPU rata-rata untuk keseluruhan aktivitas pemantauan dan deteksi berada pada tingkat yang sangat rendah, yaitu **4,62%** untuk Metode Baseline dan **4,80%** untuk Metode Event-Driven. Selisih peningkatan CPU yang disebabkan oleh kalkulasi aljabar pemulusan eksponensial (EWMA) pada threshold dinamis hanya sebesar **0,18%**. Angka ini membuktikan bahwa rumus rekursif EWMA:
$$\mu_t = \alpha x_t + (1-\alpha)\mu_{t-1}$$
sangat efisien secara komputasi karena tidak memerlukan penyimpanan seluruh riwayat data mentah secara berulang di setiap iterasi, melainkan hanya membutuhkan nilai ringkasan dari langkah sebelumnya ($\mu_{t-1}$).

##### 2. Stabilitas Penggunaan Memori RAM
Penggunaan memori RAM sangat stabil di sepanjang pengujian dengan rata-rata **28,96%** (Baseline) dan **30,47%** (Event-Driven). Selisih penggunaan RAM sebesar **1,51%** pada Event-Driven merupakan dampak dari alokasi struktur data antrean dua arah (*double-ended queue* / `deque`) di dalam memori. Antrean ini digunakan untuk menampung riwayat sampel metrik guna menghitung varians rata-rata bergerak secara dinamis. Nilai overhead memori ini tergolong sangat aman dan tidak menunjukkan adanya gejala kebocoran memori (*memory leak*) selama durasi pengujian.

##### 3. Trafik Bandwidth Pemantauan
Trafik jaringan yang dihasilkan oleh aktivitas monitoring (Active Probing) rata-rata berada di bawah **3 KB/s** untuk pengiriman (TX) dan di bawah **12 KB/s** untuk penerimaan (RX) pada kondisi normal. Pengecualian terjadi pada skenario **S5 (HTTP Slow)** yang membutuhkan bandwidth RX rata-rata **57,41 KB/s** (Baseline) dan **54,21 KB/s** (Event-Driven). Kenaikan ini terjadi karena Telemetry Probe secara berkala mengunduh berkas uji berukuran 1 MB untuk mengukur throughput jaringan. Meskipun konsumsi bandwidth S5 lebih tinggi, frekuensi pengukuran yang diatur per 20 detik berhasil menekan akumulasi penggunaan bandwidth global agar tidak mengganggu trafik aplikasi utama klien.

---

#### 4.3.3 Evaluasi dan Signifikansi Berkas Bukti (Evidence Bundle)

Mekanisme *Evidence Bundle* pada Micro-UXI merupakan inovasi penting untuk mengatasi keterbatasan proses diagnosis jaringan tradisional. Pada sistem konvensional, pelacakan akar penyebab gangguan (*Root Cause Analysis* / RCA) sering kali menuntut perekaman trafik secara utuh (*packet capture* / PCAP) secara kontinu. Metode PCAP tersebut tidak layak diterapkan pada perangkat klien *embedded* karena membutuhkan ruang penyimpanan yang sangat besar, membebani siklus tulis media penyimpanan (*storage write endurance*), dan meningkatkan utilisasi CPU secara drastis.

Micro-UXI memecahkan masalah ini dengan menerapkan metode **Passive-Triggered Diagnostic Snapshot**. Sistem hanya akan merekam kondisi sistem operasi dan log performansi dalam jendela waktu yang ringkas di sekitar waktu terjadinya event gangguan (*alarm* dan *recovery*).

##### 1. Komponen Berkas Bukti (Evidence Bundle)
Berdasarkan verifikasi pada direktori hasil pengujian (`fault-tester/out/test_S[X]/run_id_[YY]_event/evidence/`), berkas bukti yang dihasilkan secara konsisten memuat delapan elemen diagnostik utama:
1.  **Pre-event window:** Rekaman sampel metrik aktif (latensi DNS, ping RTT, status koneksi) selama 30 detik sebelum alarm dipicu, memberikan data pembanding kondisi tepat sebelum degradasi.
2.  **Event window:** Catatan performansi metrik real-time sejak alarm aktif hingga sistem dinyatakan pulih (*recovery*).
3.  **Post-event window:** Rekaman sampel metrik selama 30 sec pasca-pemulihan untuk memverifikasi kestabilan jaringan.
4.  **WiFi diagnostics:** Informasi detail status tautan nirkabel dari perintah `iw dev {iface} link` (mencakup SSID, BSSID, kekuatan sinyal RSSI, dan bitrate).
5.  **IP configuration:** Konfigurasi alamat IP antarmuka dan gateway default klien dari perintah `ip -j addr` dan `ip -j route show default`.
6.  **Routing:** Tabel routing lengkap dari perintah `ip -j route` dan kebijakan perutean dari `ip rule`.
7.  **DNS resolver:** Konfigurasi resolver dari file `/etc/resolv.conf` dan status service systemd-resolved.
8.  **Event-specific evidence:** Metrik khusus yang berkorelasi langsung dengan skenario gangguan (seperti nilai latensi DNS pada S1, kode respon HTTP pada S5, atau transisi status konektivitas pada S6).

##### 2. Matriks Keberadaan Elemen Diagnostik S1 - S6
Hasil pengecekan langsung terhadap berkas bukti di seluruh direktori skenario gangguan (S1 - S6) dirangkum pada Tabel 4.9.

**Tabel 4.9** Matriks Keberadaan Elemen Berkas Bukti (*Evidence Bundle*) Skenario S1 - S6
| Skenario Gangguan | Pre-Event Window | Event Window | Post-Event Window | WiFi Diagnostics | IP Config | Routing Table | DNS Resolver | Event-Specific Evidence |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **S1** (DNS Degraded) | $\checkmark$ | $\checkmark$ | $\checkmark$ | $\checkmark$ | $\checkmark$ | $\checkmark$ | $\checkmark$ | $\checkmark$ (Latensi DNS `dig`) |
| **S2** (DNS Timeout) | $\checkmark$ | $\checkmark$ | $\checkmark$ | $\checkmark$ | $\checkmark$ | $\checkmark$ | $\checkmark$ | $\checkmark$ (Status Gagal DNS) |
| **S3** (Loss Burst) | $\checkmark$ | $\checkmark$ | $\checkmark$ | $\checkmark$ | $\checkmark$ | $\checkmark$ | $\checkmark$ | $\checkmark$ (Rasio Packet Loss) |
| **S4** (High RTT) | $\checkmark$ | $\checkmark$ | $\checkmark$ | $\checkmark$ | $\checkmark$ | $\checkmark$ | $\checkmark$ | $\checkmark$ (RTT Ping Batch) |
| **S5** (HTTP Slow) | $\checkmark$ | $\checkmark$ | $\checkmark$ | $\checkmark$ | $\checkmark$ | $\checkmark$ | $\checkmark$ | $\checkmark$ (HTTP TTFB/Total) |
| **S6** (Conn Flap) | $\checkmark$ | $\checkmark$ | $\checkmark$ | $\checkmark$ | $\checkmark$ | $\checkmark$ | $\checkmark$ | $\checkmark$ (Transisi `operstate`) |

##### 3. Analisis Pola Diagnosis Akar Masalah (RCA)
Keberadaan delapan elemen di atas memungkinkan administrator jaringan membedakan sumber masalah secara deterministik tanpa menganalisis paket mentah:
*   Jika gangguan terdeteksi pada S1/S2 dan data *Evidence Bundle* menunjukkan status kueri DNS gagal namun *WiFi diagnostics* (RSSI bagus) dan *IP Config* (IP normal) dalam kondisi baik, maka akar masalah dapat disimpulkan berada pada kegagalan server DNS resolver.
*   Jika gangguan terdeteksi pada S6 dan berkas bukti menunjukkan data `operstate` Wi-Fi bernilai `down` dengan IP address kosong, maka masalah dapat langsung diidentifikasi sebagai kegagalan pada lapisan tautan fisik/nirkabel (*physical link failure*).
*   Jika gangguan terdeteksi pada S4/S5 namun seluruh konfigurasi IP, rute, dan DNS normal, administrator dapat mengarahkan investigasi ke arah kongesti trafik di jalur *backhaul* atau pembatasan bandwidth (*traffic shaping*) oleh penyedia layanan internet.

Secara keseluruhan, pemanfaatan berkas bukti ini memberikan efisiensi penyimpanan yang sangat tinggi karena ukuran berkas kompresi snapshot diagnostik hanya berkisar antara 20–25 KB per kejadian, menjadikannya solusi RCA yang sangat ideal untuk arsitektur Micro-UXI.
