# Panduan Pengujian Fault Injection & Monitoring Micro-UXI

Dokumen ini adalah panduan untuk menjalankan eksperimen evaluasi detektor Micro-UXI (S1 - S6). Pengujian ini dirancang berjalan secara **otomatis berulang kali (looping)** untuk menghasilkan dataset yang besar dan valid guna mengukur metrik seperti *Precision, Recall, FAR, MTTD*, dan *Overhead Sistem*.

---

## 1. Prasyarat & Persiapan

Karena eksperimen melibatkan dua perangkat fisik yang berbeda (Arduino sebagai *Monitor* dan Laptop sebagai *Injector*), **sangat krusial** untuk memastikan hal berikut sebelum memulai:

1. **Sinkronisasi Waktu (NTP):** 
   Pastikan jam di Laptop dan jam di Arduino Uno Q selaras hingga ke hitungan detik. Perbedaan waktu yang terlalu jauh akan merusak kalkulasi MTTD dan akurasi *Ground Truth*.
2. **Konektivitas & Setup Hotspot:** 
   Pastikan Arduino Uno Q sudah terhubung ke antarmuka Hotspot (`HOTSPOT_IF`) yang dipancarkan oleh Laptop. 
   *(Panduan setup menggunakan aplikasi linux-wifi-hotspot):*
   - Pastikan adapter Wi-Fi bawaan laptop **tidak sedang terhubung** ke jaringan Wi-Fi mana pun.
   - Download aplikasi ini terlebih dahulu dan install https://github.com/lakinduakash/linux-wifi-hotspot/releases/tag/v4.7.2
   - Buka aplikasi `linux-wifi-hotspot`. 
   - Pada opsi **WiFi interface**, pilih adapter Wi-Fi bawaan laptop (berfungsi sebagai pemancar hotspot).
   - Pada opsi **Internet interface**, pilih adapter USB Wi-Fi / TP-Link (berfungsi sebagai penerima internet).
   - Klik **Create Hotspot**, lalu pastikan Arduino berhasil terkoneksi ke jaringan tersebut.
   - Pastikan Arduino UNO Q terkoneksi ke hotspot tersebut.
3. **Threshold Valid:** 
   Pastikan Anda sudah memasukkan nilai *Threshold P99* hasil *Preliminary Test* ke dalam file `fault-tester/monitor_config.json`.

---

## 2. Cara Eksekusi Eksperimen

Eksperimen harus dieksekusi di dua terminal terpisah (satu di Arduino, satu di Laptop). **Selalu nyalakan Monitor lebih dulu sebelum Injector.**

Dalam contoh ini, kita akan menjalankan skenario **S3 (Loss Burst)**. Untuk event lain (S1, S2, S4, dst), cukup ganti parameter `--event` dan `--run-id`.

### Langkah A: Jalankan Monitoring (Di Arduino Uno Q)
Buka terminal SSH ke Arduino, masuk ke folder `fault-tester`, dan jalankan Master Monitor.


```bash
cd ~/micro-uxi/fault-injection/fault-tester/
python3 monitor_master.py --event S3 --run-id TEST_S3_01
```

*Apa yang terjadi?*
- Script akan *standby* memantau kondisi jaringan tanpa henti.
- Script otomatis menjalankan perekaman *overhead* CPU, RAM, & Network ke `overhead_log.jsonl` di *background*.
- Semua log akan dialokasikan secara otomatis ke dalam folder `out/test_S3/`.

### Langkah B: Jalankan Fault Injection (Di Laptop)
Buka terminal di Laptop, masuk ke folder `fi-scripts`, dan jalankan Master Injector. Pastikan menggunakan `sudo`.

```bash
cd ~/micro-uxi/fault-injection/fi-scripts/
sudo python3 fault_master.py --event S3 --run-id TEST_S3_01
```

*Apa yang terjadi?*
- Sesuai pengaturan di `fault_config.json`, skrip ini akan otomatis melakukan siksaan jaringan (misal: 30x iterasi).
- Tiap iterasi, skrip akan menyuntikkan *fault*, merekam waktunya ke `ground_truth.jsonl`, lalu melakukan *rollback* (menormalkan jaringan) selama *Grace Period* (misal: 60 detik).
- Tunggu hingga laptop selesai mengeksekusi ke-30 iterasi tersebut.

### Langkah C: Hentikan Eksperimen
1. Di **Laptop**, `fault_master.py` akan otomatis berhenti sendiri setelah iterasi loop selesai (atau Anda bisa menghentikannya lebih awal dengan `Ctrl+C`).
2. Di **Arduino**, setelah melihat injeksi di laptop selesai, tekan **`Ctrl+C`** di terminal `monitor_master.py` untuk mengakhiri perekaman secara aman.

---

## 3. Lokasi File Output

Semua hasil log eksperimen Anda sudah dikelompokkan secara rapi dan otomatis ke dalam folder sesuai nama event (misal: `out/test_S3/`).

**Di Folder Laptop (`fi-scripts/out/test_S3/`):**
- 📄 `ground_truth.jsonl` *(Fakta absolut kapan jaringan dirusak dan dipulihkan)*

**Di Folder Arduino (`fault-tester/out/test_S3/`):**
- 📄 `detection_log.jsonl` *(Catatan detik Arduino deteksi `[ALARM]` dan `[RECOVERY]`)*
- 📄 `overhead_log.jsonl` *(Catatan beban CPU, Memori, dan Bandwidth per 2 detik)*
- 📄 `raw_monitor.log` *(Terminal mentah dari proses monitoring untuk keperluan debugging)*

---

## 4. Cara Analisis Data dengan Cepat

Untuk mempermudah validasi tanpa harus *coding* Python Pandas dari nol setiap saat, Anda dapat menggunakan Visualizer Dasbor Interaktif yang sudah disediakan.

1. Buka *File Explorer* atau *Finder* di laptop Anda, navigasikan ke folder `fault-injection`.
2. Klik ganda (buka) file **`analyzer.html`** pada `~/micro-uxi/fault-injection/`. Layar dasbor akan terbuka di *Browser* (Chrome/Edge/dll).
3. Pada bagian **Upload Dataset**, masukkan 4 file hasil dari direktori `out/test_S.../` tadi (pindahkan dulu file dari Arduino ke Laptop jika diperlukan).
4. Klik **Load & Parse Data**.
5. Pilih Run ID dari *dropdown* yang tersedia (misal: `TEST_S3_01`), lalu klik **Analisis Skenario**.

**Yang Akan Ditampilkan Analyzer:**
- **Kinerja Deteksi:** Hitungan akurat persentase akurasi *Precision*, *Recall*, dan *F1-Score*.
- **MTTD & FAR:** Waktu tunda deteksi rata-rata (dalam detik) dan identifikasi *False Alarm*.
- **Tabel Komparasi:** Selisih beban *Overhead* antara kondisi saat Normal vs saat Event.
- **Grafik Interaktif:** Visualisasi *Timeline*, CPU, RAM, dan I/O Jaringan lengkap dengan *overlay* arsiran saat Alarm menyala.

---

## 5. Fault Config & Tester Config

Untuk mengubah parameter eksperimen, Anda akan berinteraksi dengan konfigurasi berikut:

**1. `fault_config.json` (Laptop / Injector)**
File ini mengatur bagaimana jaringan dirusak. Parameter kuncinya:
- `repeat`: Jumlah perulangan eksperimen.
- `grace_period_sec`: Durasi jeda pemulihan (jaringan normal) antar iterasi.
- `events`: Mengatur durasi injeksi (`duration_sec`) dan intensitas masalah (seperti `loss_pct` atau `delay_ms`).

**2. `monitor_config.json` / `tester_config.json` (Arduino / Monitor)**
File ini mengatur sensitivitas detektor dalam menyadari masalah. Parameter kuncinya:
- `scheduler`: Kecepatan interval probe saat memantau.
- `thresholds`: Batas toleransi maksimal (P99) yang diambil dari hasil *preliminary test*.
- `rules`: Syarat konfirmasi alarm, seperti harus berurutan (`confirm_consecutive`) atau dari akumulasi sampel terburuk (`m_dns` dari `n_dns`).