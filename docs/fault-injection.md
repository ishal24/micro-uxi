# Fault Injection Micro-UXI

Dokumen ini menjelaskan implementasi fault injection yang dipakai saat ini untuk validasi `monitoring` Micro-UXI. Fokus dokumen ini adalah skema `S1` sampai `S6` yang dijalankan dari folder [fault-injection/fi-scripts](../fault-injection/fi-scripts/README.md).

Dokumen ini sengaja membahas implementasi aktual testbed, bukan hanya definisi event konseptual. Definisi event dan trigger detection tetap mengacu ke [event.md](./event.md).

## 1. Scope dan Source of Truth

Source of truth untuk fault injection saat ini adalah:

- [fault-injection/fi-scripts/fault_common.sh](../fault-injection/fi-scripts/fault_common.sh)
- [fault-injection/fi-scripts/fault_dns_delay.sh](../fault-injection/fi-scripts/fault_dns_delay.sh)
- [fault-injection/fi-scripts/fault_dns_outage.sh](../fault-injection/fi-scripts/fault_dns_outage.sh)
- [fault-injection/fi-scripts/fault_loss.sh](../fault-injection/fi-scripts/fault_loss.sh)
- [fault-injection/fi-scripts/fault_rtt.sh](../fault-injection/fi-scripts/fault_rtt.sh)
- [fault-injection/fi-scripts/fault_throttle.sh](../fault-injection/fi-scripts/fault_throttle.sh)
- [fault-injection/fi-scripts/fault_flap.sh](../fault-injection/fi-scripts/fault_flap.sh)
- [fault-injection/fi-scripts/run_all_faults.sh](../fault-injection/fi-scripts/run_all_faults.sh)
- [fault-injection/fi-scripts/setup_http_server.sh](../fault-injection/fi-scripts/setup_http_server.sh)
- [fault-injection/fi-scripts/rollback_all_faults.sh](../fault-injection/fi-scripts/rollback_all_faults.sh)

Folder lama `fault-injection/scripts` dan file `fault-injection/S2.md` tidak dipakai lagi untuk skema aktif.

## 2. Topologi Uji

Topologi yang diasumsikan:

- Laptop memiliki dua adapter Wi-Fi.
- Adapter Wi-Fi internal menjadi hotspot/AP untuk device Uno Q.
- Adapter USB Wi-Fi menjadi jalur upstream ke internet atau ke jaringan luar.
- Uno Q terhubung ke hotspot laptop, lalu seluruh trafiknya diteruskan ke upstream lewat laptop.

Secara logis:

```text
Uno Q -> hotspot laptop -> upstream laptop -> internet / target
```

Pemetaan interface di script:

- `HOTSPOT_IF`: interface hotspot/AP tempat Uno Q terhubung
- `UPSTREAM_IF`: interface yang terhubung ke internet/jaringan upstream
- `CLIENT_SUBNET`: subnet klien di belakang hotspot

Default helper saat ini:

```bash
HOTSPOT_IF=ap0
UPSTREAM_IF=wlxd037456b1bc8
CLIENT_SUBNET=192.168.12.0/24
```

Kalau nama interface berbeda, override saat menjalankan script:

```bash
sudo HOTSPOT_IF=wlp0s20f3 UPSTREAM_IF=wlx123456789abc CLIENT_SUBNET=192.168.137.0/24 ./run_all_faults.sh
```

## 3. Prinsip Umum Fault Injection

### 3.1 Tujuan

Fault injection dipakai untuk menghasilkan gangguan yang cukup terkontrol sehingga:

- gejala event bisa diamati oleh `monitoring`
- timeline fault dapat dicatat sebagai ground truth
- hasil deteksi dapat dibandingkan dengan definisi skenario di `event.md`

### 3.2 Batasan

Skema yang ada sekarang lebih ditujukan untuk validasi deteksi event daripada meniru seluruh root cause dunia nyata secara sempurna. Artinya:

- fault yang diinjeksikan sudah cukup representatif untuk memicu metrik yang benar
- tetapi belum selalu merepresentasikan semua penyebab nyata di lapangan

Contoh:

- `S3_LOSS_BURST` saat ini mewakili loss di jalur upstream, bukan loss karena radio Wi-Fi lemah
- `S5_HTTP_SLOW` saat ini mewakili HTTP transaction slowdown lewat shaping response path tertentu, bukan semua kemungkinan penyebab aplikasi lambat

### 3.3 Aturan Operasional

1. Jalankan satu fault pada satu waktu.
2. Jalankan semua script dengan `sudo`.
3. Lakukan rollback sebelum berpindah skenario:

```bash
sudo ./rollback_all_faults.sh
```

4. Untuk `S5_HTTP_SLOW`, target HTTP monitoring dan target fault injection harus selaras.

## 4. Mapping Skenario ke Monitoring

Mapping fault injector ke event monitoring:

| Skenario | Event Monitoring | Script Injector |
| --- | --- | --- |
| S1 | `DNS_DEGRADED` | `fault_dns_delay.sh` |
| S2 | `DNS_TIMEOUT_BURST` | `fault_dns_outage.sh` |
| S3 | `LOSS_BURST` | `fault_loss.sh` |
| S4 | `HIGH_RTT` | `fault_rtt.sh` |
| S5 | `HTTP_SLOW` | `fault_throttle.sh` |
| S6 | `CONNECTIVITY_FLAP` | `fault_flap.sh` |

Catatan:

- `fault_throttle.sh` namanya masih memakai istilah throttle, tetapi secara semantic dipakai untuk `S5_HTTP_SLOW`.
- `A1_BANDWIDTH_THROTTLE` masih ada di `monitoring`, tetapi belum memiliki injector khusus di `fi-scripts`.

## 5. Shared Mechanism

### 5.1 `tc`

Sebagian besar fault memakai Linux traffic control:

- `netem delay` untuk menambah delay
- `netem loss` untuk menambah packet loss
- `prio` untuk memisahkan class traffic
- `tbf` untuk rate limiting pada skenario HTTP slow

### 5.2 `nft`

Fault DNS memakai `nftables`, bukan `iptables`.

Tabel yang dipakai:

- table `ip fi_fault`

Chain yang dipakai:

- `FI_FORWARD` untuk DNS outage
- `FI_MANGLE` untuk DNS mark

### 5.3 Helper Umum

File [fault_common.sh](../fault-injection/fi-scripts/fault_common.sh) menyediakan:

- validasi root
- validasi interface
- rollback qdisc dan `nft`
- helper untuk membaca target HTTP dari `monitoring/default_config.json`
- helper untuk mendeteksi port HTTP target S5

## 6. Skema Fault Injection per Event

## 6.1 S1 - DNS_DEGRADED

### Tujuan

Mensimulasikan kondisi resolusi DNS yang lambat, tetapi tidak sepenuhnya gagal.

### Script

- [fault_dns_delay.sh](../fault-injection/fi-scripts/fault_dns_delay.sh)

### Mekanisme

Langkah implementasi:

1. Trafik DNS dari klien hotspot ditandai dengan `meta mark 53` menggunakan `nft`.
2. Root qdisc `prio` dipasang pada `UPSTREAM_IF`.
3. Paket yang bertanda `53` diarahkan ke band yang diberi `netem delay`.
4. Trafik selain DNS dibiarkan lewat tanpa modifikasi khusus.

Secara efek, request DNS dari Uno Q menjadi lebih lambat, tetapi tidak otomatis gagal.

### Parameter

- `delay_ms`
- `jitter_ms` opsional

### Contoh

```bash
sudo ./fault_dns_delay.sh start 400
sudo ./fault_dns_delay.sh start 400 50
sudo ./fault_dns_delay.sh stop
```

### Gejala yang Diharapkan

- `dns_latency_ms` meningkat
- `dns_success` tetap banyak yang berhasil
- `ping.success` tetap normal
- Wi-Fi tetap connected

### Kesesuaian terhadap Event

Skema ini cukup representatif untuk `DNS_DEGRADED` karena fokus event memang pada kenaikan latensi DNS. Namun skema ini lebih merepresentasikan delay di jalur DNS daripada masalah resolver yang selektif, overload resolver, atau isu DNS aplikasi tertentu.

### Hal yang Perlu Dijaga

- Jangan jalankan bersamaan dengan `S4`, karena keduanya sama-sama memakai root qdisc di `UPSTREAM_IF`.
- Target DNS internal dan external di monitoring sebaiknya sama-sama aktif agar `affected_scope` bisa dibedakan.

## 6.2 S2 - DNS_TIMEOUT_BURST

### Tujuan

Mensimulasikan kondisi DNS timeout atau outage secara burst.

### Script

- [fault_dns_outage.sh](../fault-injection/fi-scripts/fault_dns_outage.sh)

### Mekanisme

Langkah implementasi:

1. Script membuat chain `FI_FORWARD` pada `nft`.
2. Chain di-hook ke `forward` dengan priority lebih awal.
3. Trafik UDP/TCP port `53` dari `HOTSPOT_IF` dan `CLIENT_SUBNET` di-drop.
4. Outage dapat dijalankan manual atau berulang menggunakan mode burst.

### Parameter

- `count` untuk jumlah burst
- `outage_seconds`
- `gap_seconds`

### Contoh

```bash
sudo ./fault_dns_outage.sh start
sudo ./fault_dns_outage.sh stop
sudo ./fault_dns_outage.sh burst 3 8 5
```

### Gejala yang Diharapkan

- `dns_success` turun drastis atau gagal total
- `dns_fail_ratio` tinggi
- Ping dan link Wi-Fi bisa tetap normal
- HTTP kemungkinan ikut gagal jika bergantung pada resolusi DNS

### Kesesuaian terhadap Event

Skema ini sangat cocok untuk memvalidasi `DNS_TIMEOUT_BURST` karena pattern gejalanya jelas. Kekurangannya, implementasi sekarang cenderung all-or-nothing, jadi belum mewakili kasus partial DNS failure yang lebih realistis.

### Hal yang Perlu Dijaga

- Pastikan monitoring benar-benar melakukan DNS query saat burst aktif.
- Untuk validasi burst, interval `fast_probe` sebaiknya cukup rapat agar ada cukup sampel selama phase ON dan OFF.

## 6.3 S3 - LOSS_BURST

### Tujuan

Mensimulasikan packet loss pada jalur upstream.

### Script

- [fault_loss.sh](../fault-injection/fi-scripts/fault_loss.sh)

### Mekanisme

Langkah implementasi:

1. Root qdisc lama pada `UPSTREAM_IF` dihapus.
2. `tc netem loss` dipasang pada `UPSTREAM_IF`.
3. Semua trafik yang keluar melalui upstream mengalami loss sesuai persentase yang ditentukan.

### Parameter

- `loss_percent`

### Contoh

```bash
sudo ./fault_loss.sh start 15
sudo ./fault_loss.sh stop
```

Untuk membuat burst sederhana:

```bash
sudo ./fault_loss.sh start 15
sleep 10
sudo ./fault_loss.sh stop
```

### Gejala yang Diharapkan

- `ping.success` lebih sering gagal
- `loss_pct` meningkat
- RTT dapat menjadi tidak stabil
- DNS dan HTTP bisa ikut terpengaruh sebagai efek sekunder

### Kesesuaian terhadap Event

Skema ini cukup akurat untuk `LOSS_BURST` karena metrik loss memang akan naik. Namun ini lebih mewakili loss di jalur forwarding/upstream daripada loss akibat interferensi radio, weak signal, roaming, atau masalah access point.

### Hal yang Perlu Dijaga

- Threshold loss di monitoring harus cukup rendah untuk menangkap injeksi yang dipilih.
- Jangan terlalu kecil durasi burst jika `loss_window_sec` di monitoring cukup panjang.

## 6.4 S4 - HIGH_RTT

### Tujuan

Mensimulasikan latency umum pada jalur network tanpa membuat DNS ikut tampak lambat.

### Script

- [fault_rtt.sh](../fault-injection/fi-scripts/fault_rtt.sh)

### Mekanisme

Langkah implementasi:

1. Trafik DNS dari klien ditandai dengan `mark 53`.
2. Root qdisc `prio` dipasang di `UPSTREAM_IF` dengan dua band.
3. Band default diberi `netem delay`.
4. Paket DNS diarahkan ke band tanpa delay.

Akibatnya:

- ping dan HTTP melambat
- DNS relatif tetap cepat

### Parameter

- `delay_ms`
- `jitter_ms` opsional

### Contoh

```bash
sudo ./fault_rtt.sh start 200
sudo ./fault_rtt.sh start 200 50
sudo ./fault_rtt.sh stop
```

### Gejala yang Diharapkan

- `rtt_avg_ms` meningkat
- `loss_pct` tidak perlu naik
- DNS tetap sehat
- HTTP bisa ikut melambat sebagai efek sekunder

### Kesesuaian terhadap Event

Skema ini bagus untuk memvalidasi `HIGH_RTT` karena membantu membedakan latency umum dari `DNS_DEGRADED`. Dibanding kondisi nyata, implementasi sekarang masih lebih bersih karena belum selalu menambahkan jitter atau loss kecil yang sering muncul bersama latency tinggi.

### Hal yang Perlu Dijaga

- Durasi S4 sebaiknya cukup panjang agar minimal ada dua cycle telemetry.
- Jika ingin realism lebih tinggi, delay dapat dipadukan dengan jitter kecil di iterasi berikutnya.

## 6.5 S5 - HTTP_SLOW

### Tujuan

Mensimulasikan perlambatan transaksi HTTP/application-layer tanpa harus menjatuhkan seluruh konektivitas.

### Script

- [fault_throttle.sh](../fault-injection/fi-scripts/fault_throttle.sh)
- [setup_http_server.sh](../fault-injection/fi-scripts/setup_http_server.sh) untuk target lokal yang direkomendasikan

### Mekanisme

Implementasi S5 saat ini bekerja seperti ini:

1. Root qdisc `prio` dipasang pada `HOTSPOT_IF`.
2. Band default dibiarkan tidak dibatasi.
3. Band kedua diberi `tbf rate`.
4. Hanya traffic response TCP dengan `sport` pada port HTTP target yang diarahkan ke band terbatas.

Artinya, script ini tidak men-throttle semua network traffic. Script ini secara sengaja men-slow down flow HTTP tertentu agar gejala utama yang terlihat adalah `HTTP_SLOW`, bukan `LOSS_BURST` atau `DNS_DEGRADED`.

### Parameter

- `rate`
- `HTTP_SLOW_PORTS` sebagai env var

### Contoh

```bash
bash ./setup_http_server.sh
sudo ./fault_throttle.sh start 1mbit
sudo ./fault_throttle.sh stop
```

Contoh dengan port lain:

```bash
sudo HTTP_SLOW_PORTS=443 ./fault_throttle.sh start 2mbit
```

### Target yang Direkomendasikan

Target paling stabil untuk S5 adalah server HTTP lokal di hotspot laptop:

```text
http://<hotspot-ip>:8080/testfile_1mb.bin
```

Alasan:

- target bisa dikontrol
- path lebih pendek dan konsisten
- port shaping bisa diarahkan dengan jelas
- hasil lebih repeatable dibanding target web publik

### Gejala yang Diharapkan

- `http_total_ms` meningkat
- `http_ttfb_ms` dapat meningkat
- `curl_rc` bisa gagal jika rate terlalu agresif atau timeout
- ping dan DNS dapat tetap normal

### Kesesuaian terhadap Event

Skema ini cukup cocok untuk `HTTP_SLOW` selama target monitoring selaras dengan target fault injection. Namun penting dipahami bahwa implementasi sekarang lebih dekat ke response shaping pada flow HTTP tertentu, bukan model umum untuk semua penyebab aplikasi lambat. Jadi ini sangat baik untuk validasi detector, tetapi belum mewakili semua root cause aplikasi slow.

### Hal yang Perlu Dijaga

1. URL di `monitoring/default_config.json` harus cocok dengan target yang benar-benar diperlambat.
2. Port di `HTTP_SLOW_PORTS` harus sesuai dengan port target HTTP.
3. Jangan menggunakan target publik acak jika ingin hasil stabil dan repeatable.

## 6.6 S6 - CONNECTIVITY_FLAP

### Tujuan

Mensimulasikan konektivitas yang naik-turun berulang dalam jendela waktu singkat.

### Script

- [fault_flap.sh](../fault-injection/fi-scripts/fault_flap.sh)

### Mekanisme

Langkah implementasi:

1. `UPSTREAM_IF` diturunkan dengan `ip link set down`.
2. Setelah beberapa detik, interface dinaikkan lagi.
3. Proses bisa dilakukan satu kali atau berulang.

Hotspot dapat tetap aktif, tetapi jalur ke luar menjadi putus-nyambung.

### Parameter

- `down_seconds`
- `count`
- `up_gap_seconds`

### Contoh

```bash
sudo ./fault_flap.sh once 5
sudo ./fault_flap.sh repeat 3 5 10
sudo ./fault_flap.sh down
sudo ./fault_flap.sh up
```

### Gejala yang Diharapkan

- `connectivity_ok` berubah berulang
- `ping.success` berubah antara berhasil dan gagal
- DNS dan HTTP ikut terdampak sebagai efek lanjutan
- Wi-Fi hotspot tidak harus putus

### Kesesuaian terhadap Event

Skema ini cukup akurat untuk `CONNECTIVITY_FLAP` pada layer upstream. Kekurangannya, ia belum mewakili flap pada sisi Wi-Fi association klien atau access point. Jadi event yang divalidasi di sini lebih tepat dibaca sebagai upstream connectivity flap.

### Hal yang Perlu Dijaga

- `fast_probe` harus cukup rapat agar jumlah transisi tertangkap.
- `flap_window_sec` dan `flap_transition_threshold` di monitoring harus sesuai dengan pola flap yang diinjeksikan.

## 7. Orkestrasi Berurutan dengan `run_all_faults.sh`

File [run_all_faults.sh](../fault-injection/fi-scripts/run_all_faults.sh) menjalankan:

1. baseline
2. S1
3. baseline
4. S2
5. baseline
6. S3
7. baseline
8. S4
9. baseline
10. S5
11. baseline
12. S6
13. cooldown

Parameter yang bisa dioverride lewat environment variable:

```bash
BASELINE_SEC=30
S1_DELAY_MS=400
S1_DURATION=45
S2_BURSTS=3
S2_OUTAGE_SEC=15
S2_GAP_SEC=8
S3_LOSS_PCT=60
S3_DURATION=30
S4_DELAY_MS=200
S4_DURATION=90
S5_RATE=1mbit
S5_DURATION=120
S5_TEST_URL=http://192.168.12.1:8080/testfile_1mb.bin
S5_TARGET_SCOPE=internal
S5_TARGET_PORTS=8080
S6_FLAPS=3
S6_DOWN_SEC=15
S6_GAP_SEC=10
OUTPUT_DIR=./fi-output
ALIGNMENT_DELTA_SEC=5
```

Contoh:

```bash
sudo HOTSPOT_IF=ap0 UPSTREAM_IF=wlx123456789abc CLIENT_SUBNET=192.168.12.0/24 ./run_all_faults.sh
```

## 8. Ground Truth Output

`run_all_faults.sh` menghasilkan:

- `fault_timeline_<ts>.csv`
- `ground_truth_<ts>.jsonl`
- `fault_timeline_<ts>.log`

### 8.1 Timeline CSV

CSV ini mencatat aksi detail, misalnya:

- `BASELINE_START`
- `BASELINE_END`
- `FAULT_START`
- `FAULT_STOP`
- `BURST_ON`
- `BURST_OFF`
- `FLAP_DOWN`
- `FLAP_UP`

### 8.2 Ground Truth JSONL

Setiap record berisi minimal:

```json
{
  "run_id": "fi-20260513T120000Z",
  "scenario_id": "S5_HTTP_SLOW",
  "event_type": "HTTP_SLOW",
  "fault_type": "http_slow",
  "fault_start_ts": "2026-05-13T12:00:00Z",
  "fault_end_ts": "2026-05-13T12:02:00Z",
  "target_scope": "internal",
  "target_urls": [
    "http://192.168.12.1:8080/testfile_1mb.bin"
  ],
  "parameters": {
    "rate_limit": "1mbit",
    "duration_sec": 120,
    "applied_ports": "8080",
    "affected_phase": "total"
  },
  "alignment_delta_sec": 5,
  "alignment_strategy": "first-match"
}
```

Output ini disiapkan agar lebih mudah di-align dengan `event_meta.json` dan `ground_truth_ref.json` yang dihasilkan `monitoring`.

## 9. Rollback dan Diagnostik

Untuk membersihkan seluruh state fault:

```bash
sudo ./rollback_all_faults.sh
```

Script rollback akan:

- menghapus root qdisc pada `UPSTREAM_IF`
- menghapus root qdisc pada `HOTSPOT_IF`
- menghapus `nft table ip fi_fault`
- memastikan `UPSTREAM_IF` kembali `up`

Diagnostik manual:

```bash
sudo tc qdisc show dev "$UPSTREAM_IF"
sudo tc qdisc show dev "$HOTSPOT_IF"
sudo tc filter show dev "$UPSTREAM_IF"
sudo tc filter show dev "$HOTSPOT_IF"
sudo nft list table ip fi_fault
```

## 10. Keterwakilan Terhadap Event

Ringkasan tingkat keterwakilan:

| Skenario | Representatif untuk Deteksi | Catatan |
| --- | --- | --- |
| S1 | baik | kuat untuk DNS slow, belum mencakup semua variasi resolver issue |
| S2 | sangat baik | kuat untuk DNS timeout burst, masih all-or-nothing |
| S3 | baik | kuat untuk upstream loss, bukan radio loss |
| S4 | baik | kuat untuk RTT increase yang terisolasi dari DNS |
| S5 | cukup baik | sangat tergantung keselarasan target HTTP dan port shaping |
| S6 | baik | kuat untuk upstream flap, bukan Wi-Fi association flap |

Kesimpulan praktis:

- testbed saat ini sudah layak untuk validasi `monitoring` S1-S6
- testbed belum bisa dianggap mewakili seluruh root cause nyata secara penuh
- jika realism ingin ditingkatkan, perbaikan pertama yang paling penting biasanya ada di `S5_HTTP_SLOW`

## 11. Catatan Lanjutan

- `A1_BANDWIDTH_THROTTLE` belum punya injector khusus di `fi-scripts`.
- Jika nanti A1 ingin diuji, sebaiknya dibuat injector terpisah yang benar-benar menurunkan throughput test target, bukan memakai mekanisme S5.
- Jika diperlukan realism lebih tinggi, iterasi berikutnya bisa menambah:
  - jitter pada S4
  - partial DNS failure pada S2
  - varian Wi-Fi flap pada S6
  - server HTTP yang bisa menginjeksi delay spesifik di fase `TTFB` untuk S5
