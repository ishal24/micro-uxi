### 4.2 Hasil Pengujian

Bagian ini menyajikan data dan analisis hasil pengujian yang diperoleh dari rangkaian eksperimen detektor Micro-UXI. Hasil pengujian dibagi menjadi empat subbab utama: (1) hasil uji pendahuluan (*preliminary test*) untuk kalibrasi threshold, (2) perbandingan performansi deteksi antara Metode Baseline dan Metode Event-Driven, (3) analisis beban kerja sistem (*overhead*), serta (4) struktur dan hasil analisis dari modul berkas bukti (*evidence bundle*).

---

#### 4.2.1 Hasil Uji Pendahuluan (*Preliminary Test*)

Uji pendahuluan dilakukan dengan menjalankan pemantauan secara kontinu pada kondisi jaringan normal tanpa gangguan selama minimal 5,6 jam. Fast Probe berhasil mengumpulkan data metrik dasar sebanyak lebih dari 10.000 sampel, sementara Telemetry Probe mengumpulkan 1.000 sampel sukses. Berdasarkan data kondisi normal tersebut, batas ambang batas statis ditentukan dengan mengambil nilai persentil ke-99 ($P_{99}$) dari masing-masing distribusi metrik jaringan.

##### 4.2.1.1 Hasil Kalibrasi Threshold Persentil ke-99 (P99)
Hasil perhitungan P99 untuk metrik latensi DNS, latensi RTT ping, serta durasi HTTP transaksi dirinci pada Tabel 4.6. Nilai-nilai ini selanjutnya disimpan di dalam file konfigurasi `monitor_config.json` sebagai nilai $T_{static}$ untuk detektor Baseline.

**Tabel 4.6** Hasil Perhitungan Threshold $P_{99}$ dari Uji Pendahuluan
| Metrik Pengukuran | Target Evaluasi | Nilai Threshold ($P_{99}$) | Nilai Recovery (80% Threshold) | Deskripsi Metrik |
|:---|:---|:---:|:---:|:---|
| Latensi DNS | `google.com` | 243 ms | - | Waktu resolusi kueri nama domain |
| Latensi RTT | `8.8.8.8` | 279 ms | 224 ms | Rata-rata RTT ICMP (*ping*) |
| HTTP Total Duration | `testfile_1mb.bin` | 1.535 ms | 1.228 ms | Waktu total unduh file 1 MB |
| HTTP TTFB | `testfile_1mb.bin` | 88 ms | 71 ms | Waktu tunggu respon awal HTTP |
| Paket Loss Ratio | `8.8.8.8` | 20% | 0% | Rasio paket hilang dalam jendela geser |

Nilai threshold recovery dihitung secara otomatis sebesar 80% dari batas threshold utama (khusus untuk metrik RTT dan HTTP) guna memberikan batas toleransi (*hysteresis*) sebelum alarm dinilai pulih sepenuhnya. Hal ini bertujuan mencegah detektor mengalami fluktuasi alarm (*flapping*) di sekitar garis threshold.

---

#### 4.2.2 Hasil Perbandingan Performa Pengujian (Baseline vs Event-Driven)

Pengujian utama dilakukan dengan menyuntikkan 30 kali iterasi gangguan untuk masing-masing skenario (S1–S6). Kinerja pendeteksian diukur berdasarkan metrik Precision, Recall, F1-Score, dan *Mean Time to Detect* (MTTD).

##### 4.2.2.1 Rekapitulasi Hasil Deteksi
Tabel 4.7 menyajikan ringkasan hasil perbandingan performa deteksi antara Metode Baseline (Statis) dan Metode Event-Driven (Dinamis EWMA) untuk seluruh skenario gangguan.

**Tabel 4.7** Perbandingan Performa Deteksi Metode Baseline vs Event-Driven
| Skenario | Metode Deteksi | True Positive (TP) | False Negative (FN) | False Positive (FP) | Precision | Recall | F1-Score | MTTD (Detik) |
|:---:|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **S1** | Baseline | 30 | 0 | 0 | 100.0% | 100.0% | 1,000 | 3,77 s |
| (DNS Degraded) | Event-Driven | 30 | 0 | 10 | 75,0% | 100,0% | 0,857 | 3,33 s |
| **S2** | Baseline | 28 | 2 | 0 | 100.0% | 93,3% | 0,966 | 19,39 s |
| (DNS Timeout Burst) | Event-Driven | 24 | 6 | 0 | 100.0% | 80,0% | 0,889 | 19,50 s |
| **S3** | Baseline | 24 | 6 | 0 | 100.0% | 80,0% | 0,889 | 21,04 s |
| (Loss Burst) | Event-Driven | 27 | 3 | 3 | 90,0% | 90,0% | 0,900 | 24,30 s |
| **S4** | Baseline | 29 | 1 | 0 | 100.0% | 96,7% | 0,983 | 29,59 s |
| (High RTT) | Event-Driven | 24 | 6 | 2 | 92,3% | 80,0% | 0,857 | 22,46 s |
| **S5** | Baseline | 30 | 0 | 0 | 100.0% | 100.0% | 1,000 | 35,70 s |
| (HTTP Slow) | Event-Driven | 25 | 5 | 2 | 92,6% | 83,3% | 0,877 | 23,56 s |
| **S6** | Baseline | 30 | 0 | 0 | 100.0% | 100.0% | 1,000 | 21,47 s |
| (Connectivity Flap) | Event-Driven | 29 | 1 | 1 | 96,7% | 96,7% | 0,967 | 22,31 s |
| **Rata-rata** | Baseline | 28,5 | 1,5 | 0,0 | 100,0% | 95,0% | 0,973 | 21,83 s |
| | Event-Driven | 26,5 | 3,5 | 3,0 | 91,1% | 88,3% | 0,891 | 19,24 s |

##### 4.2.2.2 Analisis Karakteristik Performa Deteksi
1.  **Analisis Sensitivitas S1 (DNS Degraded):**
    Metode Event-Driven memiliki keunggulan kecepatan respon deteksi dengan MTTD 3,33 detik dibanding Baseline (3,77 detik). Namun, metode Event-Driven menghasilkan 10 *False Positives* yang menurunkan nilai Precision menjadi 75,0% (dengan F1-Score 0,857). Hal ini terjadi karena fluktuasi latensi DNS normal yang relatif kecil menyebabkan rata-rata bergerak EWMA bergeser sangat rendah pada beberapa kondisi, sehingga variasi latensi kecil di luar gangguan langsung memicu alarm palsu. Sebaliknya, Baseline memiliki toleransi yang sangat baik (0 FP, Precision 100,0%, F1-Score 1,000) karena threshold statis (243 ms) ditempatkan cukup jauh di atas rata-rata normal.
2.  **Analisis Jendela Geser S2 dan S3 (DNS Timeout & Loss Burst):**
    Pada S2, Baseline mengungguli Event-Driven dengan F1-Score 0,966 vs 0,889. Hal ini membuktikan aturan 3-of-10 pada window geser 20 detik berkinerja optimal ketika dipadukan dengan status kegagalan diskrit biner. Pada S3, Event-Driven mencatat Recall lebih tinggi (90,0% vs 80,0%) dengan F1-Score 0,900. Ini membuktikan threshold dinamis lebih responsif dalam mengenali pola kehilangan paket acak (*random packet loss*) 40% di lingkungan nirkabel.
3.  **Analisis Efisiensi Latensi S4 (High RTT):**
    Pada skenario peningkatan RTT, metode Event-Driven berhasil mendeteksi gangguan lebih cepat dengan MTTD sebesar 22,46 detik dibandingkan dengan Metode Baseline yang membutuhkan waktu 29,59 detik (peningkatan kecepatan deteksi sebesar ~24%). Namun, sensitivitas adaptif ini menyebabkan munculnya 2 *False Positives* dan Recall yang turun ke 80,0% akibat baseline dinamis yang ikut naik menyesuaikan diri ketika RTT meningkat secara bertahap.
4.  **Analisis Transaksi S5 (HTTP Slow):**
    Event-Driven berhasil mempercepat MTTD secara signifikan dari 35,70 detik menjadi 23,56 detik (peningkatan kecepatan deteksi sebesar 34%). Namun, hal ini dibayar dengan penurunan Recall menjadi 83,3% (5 kali gagal mendeteksi gangguan) dan munculnya 2 alarm palsu (FP).

---

#### 4.2.3 Hasil Analisis Overhead Sistem

Beban sumber daya sistem diukur pada perangkat monitor (klien) untuk memastikan detektor dapat berjalan secara efisien pada perangkat dengan keterbatasan komputasi. Parameter yang diukur meliputi utilitas CPU (%), memori RAM (%), serta beban trafik pengiriman (TX) dan penerimaan (RX) data nirkabel dalam satuan kilobyte per detik (KB/s).

##### 4.2.3.1 Beban Sumber Daya pada Kondisi Jaringan Normal vs Event Gangguan
Tabel 4.8 menyajikan detail beban rata-rata sumber daya sistem selama periode kondisi jaringan normal dibandingkan dengan periode saat event gangguan sedang berlangsung (status ALARM aktif).

**Tabel 4.8** Beban Penggunaan Sumber Daya Sistem Klien (Normal vs Event)
| Skenario | Metode Deteksi | CPU Normal (%) | CPU Event (%) | RAM Normal (%) | RAM Event (%) | Bandwidth TX (KB/s) | Bandwidth RX (KB/s) |
|:---:|:---|:---:|:---:|:---:|:---:|:---:|:---:|
| **S1** | Baseline | 5,25% | 5,17% | 26,82% | 26,85% | 0,94 (Normal) / 9,33 (Event) | 5,11 (Normal) / 2,92 (Event) |
| | Event-Driven | 5,61% | 5,50% | 28,90% | 28,96% | 0,88 (Normal) / 0,82 (Event) | 3,05 (Normal) / 2,17 (Event) |
| **S2** | Baseline | 5,00% | 5,12% | 27,36% | 27,21% | 0,87 (Normal) / 0,87 (Event) | 2,18 (Normal) / 2,24 (Event) |
| | Event-Driven | 5,22% | 5,35% | 30,55% | 30,50% | 0,89 (Normal) / 0,80 (Event) | 2,16 (Normal) / 2,07 (Event) |
| **S3** | Baseline | 4,27% | 4,40% | 27,26% | 27,25% | 3,89 (Normal) / 2,28 (Event) | 5,29 (Normal) / 1,83 (Event) |
| | Event-Driven | 4,39% | 4,59% | 30,73% | 30,73% | 0,86 (Normal) / 3,83 (Event) | 2,24 (Normal) / 2,83 (Event) |
| **S4** | Baseline | 4,23% | 4,11% | 31,27% | 31,26% | 4,32 (Normal) / 0,75 (Event) | 2,65 (Normal) / 1,76 (Event) |
| | Event-Driven | 4,32% | 4,43% | 32,92% | 32,69% | 0,82 (Normal) / 0,74 (Event) | 2,08 (Normal) / 2,09 (Event) |
| **S5** | Baseline | 4,59% | 4,63% | 31,02% | 31,04% | 4,17 (Normal) / 2,26 (Event) | 57,41 (Normal) / 52,05 (Event) |
| | Event-Driven | 4,81% | 4,80% | 29,64% | 29,67% | 4,39 (Normal) / 4,62 (Event) | 54,21 (Normal) / 60,95 (Event) |
| **S6** | Baseline | 4,35% | 4,43% | 30,01% | 30,00% | 2,11 (Normal) / 0,78 (Event) | 2,15 (Normal) / 1,89 (Event) |
| | Event-Driven | 4,45% | 4,53% | 30,09% | 30,04% | 2,41 (Normal) / 0,74 (Event) | 3,09 (Normal) / 1,89 (Event) |
| **Rata-rata** | Baseline | 4,62% | 4,64% | 28,96% | 28,94% | 2,72 (Normal) / 2,71 (Event) | 12,47 (Normal) / 10,45 (Event) |
| | Event-Driven | 4,80% | 4,87% | 30,47% | 30,43% | 1,71 (Normal) / 1,93 (Event) | 11,14 (Normal) / 12,00 (Event) |

##### 4.2.3.2 Analisis Komparasi Overhead
1.  **Beban CPU:** Utilitas CPU monitor klien tergolong sangat rendah untuk kedua metode, berkisar antara **4,11% hingga 5,70%**. Komputasi EWMA pada Metode Event-Driven hanya meningkatkan penggunaan CPU rata-rata sebesar **0,1% hingga 0,3%** dibandingkan dengan Metode Baseline. Hal ini menunjukkan algoritma threshold dinamis yang dirancang sangat efisien untuk diimplementasikan pada perangkat *embedded* atau komputer papan tunggal (*single-board computer*).
2.  **Beban RAM:** Penggunaan RAM sangat stabil dengan deviasi yang sangat tipis antara kondisi normal dan event (kurang dari 0,3% perbedaan). Penggunaan memori berkisar antara **26,8% hingga 31,3%** dari total kapasitas perangkat. Metode Event-Driven memakan RAM sedikit lebih besar (selisih rata-rata **2% - 3%**) akibat alokasi memori tambahan untuk struktur data antrean geser (*double-ended queue*) yang menyimpan nilai historis observasi untuk perhitungan EWMA.
3.  **Trafik Jaringan (Bandwidth):** Trafik bandwidth TX/RX pada kondisi normal dan event secara umum sangat kecil (di bawah 10 KB/s), kecuali untuk skenario S5 (HTTP Slow) yang membutuhkan bandwidth RX hingga **57,41 KB/s** karena melakukan pengunduhan berkas biner secara periodik.

---

#### 4.2.4 Struktur dan Analisis Berkas Bukti (*Evidence Bundle*)

Sistem Micro-UXI dilengkapi dengan mekanisme pembuatan *evidence bundle* secara otomatis ketika terdeteksi perubahan status alarm jaringan. Modul ini bertujuan merekam kondisi diagnostik internal sistem operasi klien untuk mempermudah analisis akar penyebab gangguan (*root cause analysis* / RCA) pasca-kejadian.

##### 4.2.4.1 Layout dan Berkas Evidence Bundle
Setiap kali terjadi transisi status, detektor memicu pembuatan berkas bukti dalam format JSON (`*diagnostic_snapshot.json`) dan JSONL (`*evidence_timeline.jsonl`). Berkas disimpan di dalam direktori `/out/test_S[X]/run_id_[YY]_event/evidence/`. Struktur berkas bukti terdiri atas tiga label snapshot utama:
1.  `label: "alarm"`: Direkam tepat saat kondisi deteksi pertama kali dinyatakan aktif (`ALARM`).
2.  `label: "recovery"`: Direkam ketika sistem deteksi mendeteksi pemulihan kondisi jaringan (`RECOVERY`).
3.  `label: "interrupted_by_next_alarm"`: Direkam jika suatu gangguan baru muncul sebelum siklus pembersihan alarm sebelumnya selesai.

##### 4.2.4.2 Informasi Diagnostik yang Ditangkap
Setiap snapshot diagnostik secara otomatis mengeksekusi perintah sistem dan menyimpan variabel status internal sebagai berikut:
*   **Status Antarmuka Wi-Fi (`wifi`):** Menyimpan SSID, BSSID, kekuatan sinyal RSSI (`signal: -38 dBm` hingga `-34 dBm`), serta bit-rate operasional nirkabel melalui eksekusi perintah `iw dev wlan0 link`.
*   **Konfigurasi IP (`ip_configuration`):** Merekam alokasi alamat IP lokal (`192.168.12.224`), status operasional antarmuka (`UP`), dan alamat IP gateway default (`192.168.12.1`) menggunakan perintah `ip -j addr show` dan `ip -j route show default`.
*   **Tabel Routing (`routing`):** Merekam tabel routing lengkap sistem untuk mendeteksi anomali rute pengiriman paket.
*   **Konfigurasi DNS Resolver (`dns_resolver`):** Merekam daftar alamat server DNS aktif dari berkas `/etc/resolv.conf` (misalnya `nameserver 192.168.12.1`).

Dengan adanya informasi tersebut di dalam berkas bukti, administrator jaringan dapat mengidentifikasi secara presisi apakah gangguan jaringan disebabkan oleh degradasi sinyal Wi-Fi (dilihat dari RSSI), kegagalan alokasi IP (dilihat dari `ip_configuration`), kesalahan rute data (`routing`), atau gangguan pada server nama domain (`dns_resolver`), tanpa perlu melakukan penyadapan trafik (*packet capturing*) secara terus-menerus.
