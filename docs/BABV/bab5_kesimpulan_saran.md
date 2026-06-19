# BAB V
## KESIMPULAN DAN SARAN

### 5.1 Kesimpulan

Berdasarkan hasil pengujian, analisis performansi deteksi, pengukuran beban kerja (*overhead*), serta evaluasi modul berkas bukti (*evidence bundle*) yang telah dilakukan pada sistem detektor Micro-UXI, dapat ditarik beberapa kesimpulan sebagai berikut:

1.  **Perbandingan Performansi Deteksi:**
    *   **Metode Baseline (Threshold Statis):** Memiliki akurasi deteksi yang tinggi dengan rata-rata *Precision* mencapai **100,0%**, *Recall* **95,0%**, dan *F1-Score* **0,973**. Threshold statis persentil ke-99 ($P_{99}$) efektif dalam meminimalkan alarm palsu (*False Positive = 0*), namun membutuhkan waktu respon deteksi lebih lambat dengan rata-rata *Mean Time to Detect* (MTTD) selama **21,83 detik**.
    *   **Metode Event-Driven (Threshold Dinamis EWMA):** Mendeteksi gangguan lebih cepat dengan rata-rata MTTD **19,24 detik** (lebih cepat sekitar 12% secara umum, serta mencapai peningkatan kecepatan 24% pada skenario *High RTT* dan 34% pada *HTTP Slow*). Namun, sensitivitas threshold dinamis menyebabkan munculnya alarm palsu pada metrik dengan varians rendah (seperti pada S1 *DNS Degraded* dengan 10 FP), sehingga menurunkan rata-rata *Precision* menjadi **91,1%**, *Recall* **88,3%**, dan *F1-Score* **0,891**.

2.  **Kelayakan Kerja Perangkat (*Resource Feasibility*):**
    *   Kedua metode deteksi layak diimplementasikan pada perangkat dengan keterbatasan komputasi (*resource-constrained client*). Penggunaan CPU rata-rata hanya sebesar **4,62%** (Baseline) dan **4,80%** (Event-Driven), dengan selisih overhead komputasi EWMA yang minimal yaitu **0,18%**.
    *   Penggunaan memori RAM stabil pada kisaran **28,96%** (Baseline) dan **30,47%** (Event-Driven). Tambahan alokasi memori sebesar **1,51%** pada metode Event-Driven disebabkan oleh penggunaan antrean geser (*sliding queue*) untuk kalkulasi statistik rata-rata dan varians bergerak secara *real-time*.
    *   Konsumsi bandwidth pemantauan nirkabel berjalan efisien (di bawah 3 KB/s TX dan 12 KB/s RX pada kondisi normal), sehingga tidak memengaruhi trafik data utama pada jaringan klien.

3.  **Efektivitas Berkas Bukti (*Evidence Bundle*):**
    *   Mekanisme perekaman bukti berbasis kejadian (*Passive-Triggered Diagnostic Snapshot*) berhasil mengumpulkan data diagnostik secara lengkap (mencakup 8 elemen: *pre-event, event, post-event windows*, status Wi-Fi, konfigurasi IP, rute data, resolver DNS, dan bukti spesifik gangguan) untuk seluruh skenario pengujian S1 hingga S6.
    *   Pendekatan snapshot ini efisien dengan ukuran berkas berkisar antara **20–25 KB per kejadian**, sehingga dapat dijadikan alternatif diagnosis akar masalah (*Root Cause Analysis* / RCA) yang hemat ruang penyimpanan dibandingkan dengan metode perekaman paket penuh (*packet capture* / PCAP).

---

### 5.2 Saran

Untuk pengembangan sistem detektor Micro-UXI di masa mendatang, disarankan beberapa saran perbaikan sebagai berikut:

1.  **Penerapan *Variance Floor* pada Algoritma EWMA:**
    Untuk meminimalkan alarm palsu pada metrik dengan variabilitas normal rendah (seperti latensi DNS pada S1), perlu ditambahkan batas bawah standar deviasi (*variance floor*). Batas ini akan mencegah threshold dinamis menyusut terlalu rapat ketika varians normal metrik bernilai kecil.
2.  **Implementasi Metode Deteksi Hibrida (*Hybrid Detection*):**
    Menggabungkan keunggulan respon cepat threshold dinamis EWMA sebagai alarm pemicu awal, dengan filter threshold statis $P_{99}$ sebagai pengonfirmasi akhir guna memastikan keandalan alarm sebelum dikirim ke server.
3.  **Adaptasi Interval Probing Dinamis:**
    Mengonfigurasi detektor agar secara otomatis meningkatkan frekuensi *probing* (*fast mode*) saat terdeteksi indikasi awal deviasi performa jaringan, dan kembali ke mode normal (*slow mode*) pada kondisi normal untuk menghemat daya baterai dan bandwidth.
4.  **Pengujian pada Lingkungan Topologi yang Lebih Kompleks:**
    Melakukan uji coba sistem detektor pada lingkungan jaringan nirkabel yang lebih padat pengguna (*high-density Wi-Fi*) atau topologi dengan mobilitas tinggi (*mobility/roaming scenarios*), untuk menguji ketahanan baseline dinamis terhadap interferensi eksternal.
