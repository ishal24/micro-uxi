# Alur Kerja Sistem Pemantauan Event-Driven Micro-UXI

Dokumen ini mendokumentasikan secara rinci namun ringkas alur kerja sistem deteksi gangguan jaringan (*fault detection*) berorientasi kejadian (*event-driven*) pada Micro-UXI, mulai dari pemantauan aktif, evaluasi ambang batas dinamis, penyimpanan buffer melingkar (*ring buffer*), perekaman bukti kejadian (*evidence recording*), hingga pengukuran overhead sistem.

---

## 1. Diagram Alur Kerja Sistem

```mermaid
flowchart TD
    subgraph Orchestration [Orkestrasi Monitor Master]
        MStart[monitor_master.py] -->|subprocess.Popen| P1[test_sX_*.py]
        MStart -->|subprocess.Popen| P2[tester_overhead.py]
    end

    subgraph Monitoring [1. Pemantauan & Buffer]
        P1 -->|Fast & Telemetry Probes| A[Mengukur latensi, loss, RTT, HTTP]
        A --> B[Ring Buffer / pre_buffer Deque]
    end

    subgraph Detection [2. Deteksi & Ambang Batas]
        A --> C{Threshold Mode?}
        C -->|Static| D[Bandingkan dengan P99]
        C -->|Dynamic EWMA| E{Apakah Terjadi Alarm?}
        E -->|Tidak| F[Update Mean & Varians EWMA]
        E -->|Ya| G[Tunda Update Baseline]
        D & E --> H{Evaluasi Aturan Pemicu}
        H -->|confirm_consecutive / m-of-n| I{Status Berubah?}
    end

    subgraph Recording [3. Perekaman Bukti & Snapshot]
        I -->|NORMAL -> ALARM| J[Pindah Fase: event]
        J --> K[Tulis Metadata & Dump pre_buffer ke Timeline]
        K --> L[Ambil Snapshot Diagnosis Awal 'alarm']
        I -->|ALARM -> RECOVERY| M[Pindah Fase: post_event]
        M --> N[Ambil Snapshot Akhir 'recovery']
        N --> O[Tunggu durasi post_event_sec]
        O --> P[Ambil Snapshot Final 'post_event_complete']
        P --> Q[Tulis evidence_closed & Kembali Pasif]
    end

    subgraph Overhead [4. Pemantauan Sumber Daya (Paralel)]
        P2 -->|Mulai secara independen & non-blocking| R[Ukur CPU, RAM, I/O berkala]
        R -->|Tulis ke| S[overhead_log.jsonl]
    end
```

---

## 2. Rincian Alur Kerja Sistem

### A. Tahap 1: Pemantauan Aktif (*Active Probing* & *Ring Buffer*)
Sebelum pemantauan berjalan, sistem melakukan persiapan konfigurasi:
1.  **Dinamika Konfigurasi Decoupling:** [monitor_master.py](file:///d:/1.%20College/0.%20SKRIPSI/new/micro-uxi/fault-injection/fault-tester/monitor_master.py) membaca file konfigurasi induk [monitor_config.json](file:///d:/1.%20College/0.%20SKRIPSI/new/micro-uxi/fault-injection/fault-tester/monitor_config.json), mengekstrak objek `tester_config`, lalu menulisnya sebagai file perantara `tester_config.json`. Langkah decoupling ini memungkinkan skrip probe independen mengambil parameter terbaru tanpa ketergantungan langsung ke konfigurasi master.
2.  **Jadwal Probe:** Pemantauan dilakukan berkala oleh subproses probe menggunakan parameter dari `tester_config.json` melalui dua jenis *probe*:
    *   **Fast Probe** (latensi DNS, ping/RTT): Dijalankan dengan interval pendek (default: 2 detik).
    *   **Telemetry Probe** (transaksi HTTP total/TTFB): Dijalankan dengan interval menengah (default: 20 detik).

Setiap kali sampel pemantauan didapatkan:
1.  Hasil probe dicatat ke dalam log mentah monitor.
2.  Hasil probe dimasukkan ke dalam **`pre_buffer`** (sebuah struktur data `deque` dalam memori yang diatur oleh [evidence_recorder.py](file:///d:/1.%20College/0.%20SKRIPSI/new/micro-uxi/fault-injection/fault-tester/evidence_recorder.py)).
3.  `pre_buffer` bertindak sebagai *sliding window* atau *ring buffer* berbasis waktu yang secara pasif menyimpan log probe selama durasi tertentu sebelum kejadian alarm (misal: 30 detik terakhir). Sampel di luar jendela waktu akan otomatis dihapus (*trimmed*) untuk menghemat memori.

---

### B. Tahap 2: Evaluasi Ambang Batas (*Detection Logic*)
Detektor membandingkan nilai sampel dengan ambang batas (*threshold*) menggunakan dua mode evaluasi:
1.  **Ambang Batas Statis:** Menggunakan batas mutlak (persentil P99) yang diperoleh dari pengujian awal (*preliminary test*).
2.  **Ambang Batas Dinamis (EWMA):** Dihitung secara dinamis oleh [dynamic_threshold.py](file:///d:/1.%20College/0.%20SKRIPSI/new/micro-uxi/fault-injection/fault-tester/dynamic_threshold.py) dengan rumus:
    *   **Rata-rata Bergerak ($\mu_t$):**  
        $$\mu_t = \alpha \cdot x_t + (1 - \alpha) \cdot \mu_{t-1}$$
    *   **Varians Bergerak ($v_t$):**  
        $$v_t = \beta \cdot (x_t - \mu_{t-1})^2 + (1 - \beta) \cdot v_{t-1}$$
    *   **Ambang Batas Dinamis ($T_{dyn}$):**  
        $$T_{dyn} = \mu_t + k \cdot \sqrt{v_t}$$
    
    *Aturan Pembaruan Dinamis (Anti-Poisoning):*
    Untuk menghindari kerusakan atau pergeseran baseline ambang batas oleh data anomali saat gangguan sedang terjadi (*baseline/threshold poisoning*), sistem menerapkan perlindungan **dua lapis**:
    *   **Warmup Period:** Selama jumlah sampel kurang dari `warmup_samples` (misal: 60 sampel), ambang batas diatur ke tak terhingga (`inf`) sehingga detektor tidak akan memicu alarm palsu sebelum baseline stabil.
    *   **Lapis 1 (Evaluator Level):** Di tingkat logika kalkulasi [dynamic_threshold.py](file:///d:/1.%20College/0.%20SKRIPSI/new/micro-uxi/fault-injection/fault-tester/dynamic_threshold.py), parameter EWMA ($\mu_t$ dan $v_t$) hanya diperbarui apabila nilai sampel yang diobservasi **tidak melampaui** ambang batas aktif (`exceeded == False`). Jika nilai metrik terdeteksi anomali, metrik tersebut dibuang dan tidak dimasukkan ke dalam perhitungan baseline.
    *   **Lapis 2 (Script/Monitor Level):** Di tingkat skrip pemantauan (seperti [test_s1_dns_degraded.py](file:///d:/1.%20College/0.%20SKRIPSI/new/micro-uxi/fault-injection/fault-tester/test_s1_dns_degraded.py)), ketika status alarm sedang aktif (`is_active == True`), skrip memanggil evaluasi EWMA dengan parameter `update=False`. Hal ini menghentikan total pembaruan baseline selama gangguan berlangsung, bahkan jika ada sampel fluktuatif yang kebetulan berada di bawah threshold.

#### Penentuan Alarm & Pemulihan:
Detektor memverifikasi apakah gangguan valid menggunakan aturan pemicu:
*   `confirm_consecutive`: Membutuhkan sejumlah $N$ sampel berurutan yang melampaui batas (misal: 2 kali berturut-turut untuk S1, S4, S5).
*   `m-of-n`: Membutuhkan minimal $M$ kegagalan dalam jendela $N$ sampel terakhir (misal: 3 kegagalan dari 10 sampel DNS terakhir untuk S2; 4 kegagalan dari 20 sampel ping terakhir untuk S3).
*   `transitions`: Membutuhkan $M$ perubahan kondisi Wi-Fi dalam jendela waktu tertentu (untuk S6).

---

### C. Tahap 3: Perekaman Bukti & Diagnosis (*Evidence Recording*)
Ketika terjadi transisi status deteksi (terbaca dari pencocokan regex `EVENT_RE` di stdout subproses oleh master monitor), [evidence_recorder.py](file:///d:/1.%20College/0.%20SKRIPSI/new/micro-uxi/fault-injection/fault-tester/evidence_recorder.py) memindahkan siklus hidup perekaman bukti melalui 3 fase:

#### 1. Fase `pre_event` (Saat Transisi `NORMAL -> ALARM`)
*   Perekam aktif membuat dua file log unik berdasarkan run ID dan timestamp kejadian:
    *   `*_evidence_timeline.jsonl` (menyimpan kronologi data per-baris JSON).
    *   `*_diagnostic_snapshot.json` (dokumen JSON terstruktur berisi snapshot detail).
*   **Replay Ring Buffer:** Mengambil semua sampel historis yang tersimpan di `pre_buffer` (ring buffer) lalu menyalinnya secara berurutan ke dalam file timeline dengan label `pre_event_sample` dan penanda fase `"pre_event"`. Ini memberikan konteks metrik sebelum anomali terdeteksi.

#### 2. Fase `event` (Saat Alarm Aktif)
*   **Snapshot Awal (`alarm`):** Segera mengambil potret status jaringan sistem operasi secara mendalam (status interface nirkabel, tabel IP Address, routing IP, nameserver dari `/etc/resolv.conf`, serta keluaran perintah diagnostik) dan menyimpannya di objek array `snapshots` pada file snapshot.
*   Setiap baris log probe baru dari stdout subproses ditulis secara real-time langsung ke file timeline dengan label `probe_sample` dan penanda fase `"event"`.

#### 3. Fase `post_event` (Saat Transisi `ALARM -> RECOVERY`)
*   **Snapshot Pemulihan (`recovery`):** Merekam potret diagnostik sistem untuk menangkap kondisi pemulihan.
*   Perekaman tidak langsung berhenti. Status perekaman dialihkan ke `"post_event"`, dan sampel probe baru terus ditulis ke timeline selama masa tunggu (ditentukan `post_event_sec`, misal: 30 detik).
*   Setelah masa tunggu selesai, perekam mengambil snapshot final (`post_event_complete`), menulis baris penutup `evidence_closed` (dengan alasan `"post_event_window_complete"` atau `"monitor_stop"` jika program dihentikan), lalu mengosongkan status `current_event` untuk kembali ke kondisi pasif (pre-alarm).

---

### D. Tahap 4: Pengukuran Overhead Sistem (*Asynchronous Overhead Monitoring*)
Untuk memastikan pemantauan dinamis dan perekaman bukti tidak membebani perangkat monitor, pengukuran overhead dilakukan secara **paralel dan non-blocking (asinkron)**:
1.  **Orkestrasi Multiprocessing:** Saat [monitor_master.py](file:///d:/1.%20College/0.%20SKRIPSI/new/micro-uxi/fault-injection/fault-tester/monitor_master.py) dijalankan, skrip ini menggunakan `subprocess.Popen` untuk meluncurkan dua proses OS terpisah di latar belakang secara bersamaan:
    *   **Proses Probe Utama:** Skrip monitoring spesifik skenario (`test_sX_*.py`).
    *   **Proses Overhead Recorder:** Skrip [tester_overhead.py](file:///d:/1.%20College/0.%20SKRIPSI/new/micro-uxi/fault-injection/fault-tester/tester_overhead.py).
2.  **Eksekusi Konkuren (Non-blocking):** 
    *   Kedua proses ini berjalan secara independen dan paralel di tingkat sistem operasi.
    *   Proses overhead merekam metrik penggunaan sumber daya (utilitas CPU %, penggunaan RAM %, disk %, dan bandwidth TX/RX) setiap interval yang dikonfigurasi (default: 2 detik) dan menulisnya ke `overhead_log.jsonl`.
    *   Sementara itu, thread utama `monitor_master.py` memproses *pipe* stdout dari proses probe secara asinkron untuk mendeteksi event `ALARM` dan `RECOVERY` tanpa menginterupsi perekaman overhead.
3.  **Terminasi Terkoordinasi & Cleanup:** Saat monitor dihentikan paksa (SIGINT / `Ctrl+C`):
    *   `monitor_master.py` menangkap `KeyboardInterrupt` lalu mengirimkan sinyal `SIGINT` ke subproses probe (`proc`), menunggu hingga 5 detik agar berhenti secara normal, sebelum mengirim sinyal paksa `SIGTERM`/`SIGKILL`.
    *   Blok `finally` menjamin pembersihan total berjalan: memanggil `evidence_recorder.close()` untuk menutup timeline aktif secara aman (menulis penutup `evidence_closed` dan mengambil snapshot `monitor_stop`), serta menghentikan `tester_overhead.py` (`overhead_proc.terminate()`) agar tidak ada proses yang tertinggal (*zombie processes*).
4.  **Analisis Data:** Data overhead di `overhead_log.jsonl` nantinya dibandingkan secara otomatis oleh [analyzer.html](file:///d:/1.%20College/0.%20SKRIPSI/new/micro-uxi/fault-injection/analyzer.html) untuk membandingkan beban sistem saat Normal vs saat Alarm aktif.




