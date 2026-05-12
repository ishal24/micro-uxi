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

### 3.4 Hubungan Fault Injection dengan Interval Monitoring

Parameter fault injection yang ideal tidak bisa dipilih secara terpisah dari konfigurasi `monitoring`. Durasi injeksi harus cukup panjang agar probe sempat mengambil sampel, detector sempat memenuhi `confirm_consecutive`, dan recovery sempat terlihat.

Dengan default monitoring saat ini:

- `fast_interval_sec = 5`
- `telemetry_interval_sec = 30`
- `throughput_interval_sec = 900`

rule praktis yang aman adalah:

- event berbasis `fast_probe` sebaiknya aktif minimal `3 x fast_interval`
- event berbasis `telemetry_probe` sebaiknya aktif minimal `3 x telemetry_interval`
- baseline sebelum fault sebaiknya minimal `30-60s`
- untuk mode `dynamic`, warm-up baseline harus lebih panjang daripada mode `static`

Ringkasan parameter waktu yang aman:

| Event | Probe Utama | Kondisi Aman Awal |
| --- | --- | --- |
| `S1_DNS_DEGRADED` | fast | delay aktif `30-60s` |
| `S2_DNS_TIMEOUT_BURST` | fast | tiap burst aktif `>=15s` |
| `S3_LOSS_BURST` | fast | butuh sinkronisasi khusus dengan `loss_window_sec` |
| `S4_HIGH_RTT` | telemetry | delay aktif `90-120s` |
| `S5_HTTP_SLOW` | telemetry | slow aktif `90-180s` |
| `S6_CONNECTIVITY_FLAP` | fast | down duration `10-15s`, repeat `3x` |

Catatan penting untuk mode `dynamic`:

- baseline DNS butuh minimal `5` healthy fast samples, jadi secara praktis siapkan `60-120s` kondisi normal
- baseline RTT dan HTTP butuh minimal `5` healthy telemetry samples, jadi secara praktis siapkan `180-300s` kondisi normal

Catatan penting untuk `S3_LOSS_BURST`:

- dengan default `fast_interval_sec = 5`, `loss_window_sec = 10`, dan `minimum_samples = 5`, detector `LOSS_BURST` tidak punya cukup sampel untuk memutuskan event secara andal
- supaya `S3` ideal, gunakan salah satu dari dua opsi ini:
  - kecilkan `fast_interval_sec` menjadi `2s`
  - atau naikkan `loss_window_sec` menjadi `25-30s`

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

Langkah implementasi detail di script:

1. Bersihkan qdisc lama pada interface upstream supaya tidak bentrok dengan fault lain:

```bash
tc qdisc del dev "${UPSTREAM_IF}" root
```

2. Buat table `nft` khusus fault injection jika belum ada:

```bash
nft add table ip fi_fault
```

3. Buat chain `FI_MANGLE` yang di-hook ke `prerouting` dengan priority `-150`, lalu kosongkan isi chain agar state selalu konsisten:

```bash
nft add chain ip fi_fault FI_MANGLE '{ type filter hook prerouting priority -150; policy accept; }'
nft flush chain ip fi_fault FI_MANGLE
```

4. Tandai trafik DNS dari Uno Q dengan `mark 53`. Yang ditandai hanya paket dari `HOTSPOT_IF` dan `CLIENT_SUBNET`, jadi trafik lain milik laptop tidak ikut terpengaruh:

```bash
nft add rule ip fi_fault FI_MANGLE iifname "${HOTSPOT_IF}" ip saddr "${CLIENT_SUBNET}" udp dport 53 meta mark set 53
nft add rule ip fi_fault FI_MANGLE iifname "${HOTSPOT_IF}" ip saddr "${CLIENT_SUBNET}" tcp dport 53 meta mark set 53
```

5. Pasang root qdisc `prio` pada `UPSTREAM_IF`:

```bash
tc qdisc add dev "${UPSTREAM_IF}" root handle 1: prio
```

6. Pasang `netem delay` hanya pada band `1:1`. Delay inilah yang menjadi fault utama:

```bash
tc qdisc add dev "${UPSTREAM_IF}" parent 1:1 handle 10: netem delay "${delay_ms}ms"
```

Jika memakai jitter:

```bash
tc qdisc add dev "${UPSTREAM_IF}" parent 1:1 handle 10: netem delay "${delay_ms}ms" "${jitter_ms}ms"
```

7. Arahkan hanya paket yang sudah diberi `mark 53` ke band `1:1`:

```bash
tc filter add dev "${UPSTREAM_IF}" parent 1: protocol ip prio 1 handle 53 fw flowid 1:1
```

Secara efek:

- DNS dari Uno Q menjadi lambat
- ping, HTTP, dan trafik lain tidak sengaja dilambatkan oleh fault ini
- detektor S1 bisa melihat kenaikan `dns_latency_ms` tanpa harus melihat banyak packet loss

Perintah stop yang dilakukan script:

```bash
tc qdisc del dev "${UPSTREAM_IF}" root
nft flush chain ip fi_fault FI_MANGLE
nft delete chain ip fi_fault FI_MANGLE
```

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

### Kondisi Ideal Awal

Parameter awal yang direkomendasikan:

- `delay_ms = 400-600`
- `jitter_ms = 0-50`
- durasi fault `30-60s`
- baseline sebelum fault `30-60s`

Alasan:

- threshold static DNS saat ini `300ms`, jadi injeksi `400ms` sudah cukup jelas melewati threshold
- dengan `fast_interval_sec = 5` dan `confirm_consecutive = 2`, durasi `15s` sebenarnya sudah bisa memicu event, tetapi `30-60s` lebih aman dan memberi cukup sampel untuk evidence
- jitter tidak wajib; nilai `0-50ms` cukup untuk membuat delay lebih natural tanpa mengaburkan gejala utama

Mode uji yang disarankan:

- untuk validasi dasar detector, mulai dari `400ms` selama `45s`
- untuk uji yang lebih agresif, gunakan `600ms` selama `60s`
- untuk mode `dynamic`, siapkan warm-up DNS normal minimal `60s`, idealnya `120s`

### Hal yang Perlu Dijaga

- Jangan jalankan bersamaan dengan `S4`, karena keduanya sama-sama memakai root qdisc di `UPSTREAM_IF`.
- Target DNS internal dan external di monitoring sebaiknya sama-sama aktif agar `affected_scope` bisa dibedakan.

## 6.2 S2 - DNS_TIMEOUT_BURST

### Tujuan

Mensimulasikan kondisi DNS timeout atau outage secara burst.

### Script

- [fault_dns_outage.sh](../fault-injection/fi-scripts/fault_dns_outage.sh)

### Mekanisme

Langkah implementasi detail di script:

1. Buat table `nft` fault injection bila belum ada:

```bash
nft add table ip fi_fault
```

2. Buat chain `FI_FORWARD` yang di-hook ke jalur `forward` dengan priority `-1`, lalu kosongkan isi chain:

```bash
nft add chain ip fi_fault FI_FORWARD '{ type filter hook forward priority -1; policy accept; }'
nft flush chain ip fi_fault FI_FORWARD
```

3. Tambahkan rule `drop` untuk trafik DNS dari klien hotspot:

```bash
nft add rule ip fi_fault FI_FORWARD iifname "${HOTSPOT_IF}" ip saddr "${CLIENT_SUBNET}" udp dport 53 drop
nft add rule ip fi_fault FI_FORWARD iifname "${HOTSPOT_IF}" ip saddr "${CLIENT_SUBNET}" tcp dport 53 drop
```

4. Jika mode yang dipakai adalah `burst`, script menjalankan pola berikut:

```bash
start -> sleep "${outage_seconds}" -> stop -> sleep "${gap_seconds}" -> ulangi
```

Secara efek:

- DNS query dari Uno Q tidak mendapat jawaban
- ping ke target ICMP bisa tetap normal
- masalah tampak jelas sebagai fault DNS, bukan fault link total

Perintah stop yang dilakukan script:

```bash
nft flush chain ip fi_fault FI_FORWARD
nft delete table ip fi_fault
```

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

### Kondisi Ideal Awal

Parameter awal yang direkomendasikan:

- `burst_count = 2-3`
- `outage_seconds = 15s`
- `gap_seconds = 5-8s` jika ingin satu episode outage yang tetap terasa menyambung
- `gap_seconds = 20-30s` jika ingin tiap burst lebih berpeluang terbaca sebagai episode yang terpisah

Alasan:

- dengan `fast_interval_sec = 5` dan `confirm_consecutive = 2`, outage `15s` memberi cukup waktu untuk minimal dua sampel gagal
- gap pendek cenderung membuat beberapa burst tergabung sebagai satu event yang sama
- gap panjang lebih cocok jika tujuan eksperimen adalah melihat apakah detector bisa membuka dan menutup event berkali-kali

Mode uji yang disarankan:

- validasi default: `3 burst`, `15s outage`, `8s gap`
- validasi per-burst terpisah: `3 burst`, `15s outage`, `25s gap`

### Hal yang Perlu Dijaga

- Pastikan monitoring benar-benar melakukan DNS query saat burst aktif.
- Untuk validasi burst, interval `fast_probe` sebaiknya cukup rapat agar ada cukup sampel selama phase ON dan OFF.

## 6.3 S3 - LOSS_BURST

### Tujuan

Mensimulasikan packet loss pada jalur upstream.

### Script

- [fault_loss.sh](../fault-injection/fi-scripts/fault_loss.sh)

### Mekanisme

Langkah implementasi detail di script:

1. Bersihkan root qdisc lama pada `UPSTREAM_IF`:

```bash
tc qdisc del dev "${UPSTREAM_IF}" root
```

2. Pasang `netem loss` langsung sebagai root qdisc:

```bash
tc qdisc add dev "${UPSTREAM_IF}" root netem loss "${loss_percent}%"
```

3. Selama fault aktif, seluruh trafik yang keluar lewat `UPSTREAM_IF` akan mengalami probabilistic packet loss sesuai parameter.

Secara efek:

- ping dari Uno Q menjadi sering gagal
- sample loss pada telemetry meningkat
- DNS dan HTTP bisa ikut rusak sebagai dampak turunan

Perintah stop yang dilakukan script:

```bash
tc qdisc del dev "${UPSTREAM_IF}" root
```

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

### Kondisi Ideal Awal

Parameter awal yang direkomendasikan untuk fault injection:

- `loss_percent = 40-60%` untuk validasi yang jelas
- `loss_percent = 20-30%` untuk uji dekat threshold
- durasi fault `20-30s` jika monitoring sudah selaras

Tetapi ada syarat penting di sisi monitoring:

- default saat ini adalah `fast_interval_sec = 5`
- default saat ini juga `loss_window_sec = 10`
- default `minimum_samples = 5`

Dengan kombinasi itu, `S3` tidak ideal karena window `10s` terlalu pendek untuk mengumpulkan `5` sampel fast jika intervalnya `5s`.

Supaya `S3` benar-benar bisa diuji dengan baik, pilih salah satu:

- ubah `fast_interval_sec` menjadi `2s`
- atau ubah `loss_window_sec` menjadi `25-30s`

Profil uji yang disarankan:

- jika `fast_interval_sec = 2s`, pakai `loss_percent = 40%` selama `20s`
- jika `fast_interval_sec = 5s`, pakai `loss_percent = 40-60%` dan naikkan `loss_window_sec` menjadi `25-30s`

### Hal yang Perlu Dijaga

- Threshold loss di monitoring harus cukup rendah untuk menangkap injeksi yang dipilih.
- Jangan terlalu kecil durasi burst jika `loss_window_sec` di monitoring cukup panjang.

## 6.4 S4 - HIGH_RTT

### Tujuan

Mensimulasikan latency umum pada jalur network tanpa membuat DNS ikut tampak lambat.

### Script

- [fault_rtt.sh](../fault-injection/fi-scripts/fault_rtt.sh)

### Mekanisme

Langkah implementasi detail di script:

1. Bersihkan qdisc lama pada `UPSTREAM_IF`:

```bash
tc qdisc del dev "${UPSTREAM_IF}" root
```

2. Buat chain `FI_MANGLE` pada `nft`, lalu tandai hanya trafik DNS dari Uno Q dengan `mark 53`:

```bash
nft add table ip fi_fault
nft add chain ip fi_fault FI_MANGLE '{ type filter hook prerouting priority -150; policy accept; }'
nft flush chain ip fi_fault FI_MANGLE
nft add rule ip fi_fault FI_MANGLE iifname "${HOTSPOT_IF}" ip saddr "${CLIENT_SUBNET}" udp dport 53 meta mark set 53
nft add rule ip fi_fault FI_MANGLE iifname "${HOTSPOT_IF}" ip saddr "${CLIENT_SUBNET}" tcp dport 53 meta mark set 53
```

3. Pasang root qdisc `prio` dengan dua band pada `UPSTREAM_IF`. Semua trafik default diarahkan ke band `1:2` yang nanti akan diberi delay:

```bash
tc qdisc add dev "${UPSTREAM_IF}" root handle 1: prio bands 2 \
  priomap 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1
```

4. Pasang `netem delay` pada band `1:2`:

```bash
tc qdisc add dev "${UPSTREAM_IF}" parent 1:2 handle 20: netem delay "${delay_ms}ms"
```

Jika memakai jitter:

```bash
tc qdisc add dev "${UPSTREAM_IF}" parent 1:2 handle 20: netem delay "${delay_ms}ms" "${jitter_ms}ms"
```

5. Arahkan paket DNS yang sudah diberi `mark 53` ke band `1:1`, yaitu band tanpa delay:

```bash
tc filter add dev "${UPSTREAM_IF}" parent 1: protocol ip prio 1 handle 53 fw flowid 1:1
```

Akibatnya:

- ping dan HTTP melambat
- DNS relatif tetap cepat
- S4 bisa dibedakan dari S1 karena fault utamanya bukan pada DNS

Perintah stop yang dilakukan script:

```bash
tc qdisc del dev "${UPSTREAM_IF}" root
nft flush chain ip fi_fault FI_MANGLE
nft delete chain ip fi_fault FI_MANGLE
```

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

### Kondisi Ideal Awal

Parameter awal yang direkomendasikan:

- `delay_ms = 200-300`
- `jitter_ms = 0-30`
- durasi fault `90-120s`
- baseline sebelum fault `60s` untuk static, `180-300s` untuk dynamic

Alasan:

- threshold static RTT saat ini `150ms`, jadi injeksi `200ms` sudah cukup jelas
- event S4 dievaluasi dari `telemetry_probe` dengan interval `30s` dan `confirm_consecutive = 2`, jadi durasi `90s` adalah titik aman agar minimal ada tiga sampel telemetry selama fault
- jitter kecil membantu realism, tetapi tidak wajib untuk validasi awal

Mode uji yang disarankan:

- validasi dasar: `200ms` selama `90s`
- validasi lebih tegas: `250-300ms` selama `120s`
- jika ingin isolasi S4 yang bersih, jangan kombinasikan dengan loss atau DNS fault lain

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

1. Siapkan target HTTP lebih dulu. Untuk mode yang paling stabil, jalankan server lokal:

```bash
ip -4 addr show "${HOTSPOT_IF}" | awk '/inet / {print $2}' | cut -d/ -f1 | head -n 1
dd if=/dev/urandom of="testfile_1mb.bin" bs=1M count=1 status=none
python3 -m http.server 8080 --bind "${LAPTOP_IP}"
```

Dalam script [setup_http_server.sh](../fault-injection/fi-scripts/setup_http_server.sh), langkah ini dibungkus otomatis dan file uji default adalah `testfile_1mb.bin`.

2. Sebelum menjalankan fault, `run_all_faults.sh` mencoba memastikan target HTTP benar-benar bisa diakses:

```bash
curl -sf --max-time 10 -o /dev/null "${S5_TEST_URL}"
```

3. Bersihkan qdisc lama pada `HOTSPOT_IF`:

```bash
tc qdisc del dev "${HOTSPOT_IF}" root
```

4. Pasang root qdisc `prio` dengan dua band. Semua trafik default tetap lewat band `1:1` tanpa rate limit:

```bash
tc qdisc add dev "${HOTSPOT_IF}" root handle 1: prio bands 2 \
  priomap 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0
```

5. Pasang `tbf` pada band `1:2` sebagai limiter:

```bash
tc qdisc add dev "${HOTSPOT_IF}" parent 1:2 handle 20: \
  tbf rate "${rate}" burst 15000 latency 200ms
```

6. Arahkan hanya response TCP yang keluar dari port target HTTP ke band terbatas tersebut:

```bash
tc filter add dev "${HOTSPOT_IF}" parent 1:0 protocol ip prio 1 \
  u32 match ip protocol 6 0xff match ip sport "${port}" 0xffff flowid 1:2
```

Contoh jika target lokal memakai port `8080`:

```bash
tc filter add dev "${HOTSPOT_IF}" parent 1:0 protocol ip prio 1 \
  u32 match ip protocol 6 0xff match ip sport 8080 0xffff flowid 1:2
```

Contoh jika target HTTPS external memakai port `443`:

```bash
tc filter add dev "${HOTSPOT_IF}" parent 1:0 protocol ip prio 1 \
  u32 match ip protocol 6 0xff match ip sport 443 0xffff flowid 1:2
```

Artinya, script ini tidak men-throttle semua network traffic. Script ini sengaja hanya memperlambat flow HTTP tertentu agar gejala utama yang terlihat adalah `HTTP_SLOW`, bukan `LOSS_BURST` atau `DNS_DEGRADED`.

Perintah stop yang dilakukan script:

```bash
tc qdisc del dev "${HOTSPOT_IF}" root
```

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

### Kondisi Ideal Awal

Parameter awal yang direkomendasikan:

- target HTTP: server lokal hotspot, port `8080`
- file uji: `1MB`
- `rate = 1mbit` untuk validasi yang jelas tetapi masih relatif aman
- durasi fault `90-180s`
- baseline sebelum fault `60s` untuk static, `180-300s` untuk dynamic

Alasan:

- threshold static HTTP total saat ini `2000ms`, jadi file `1MB` dengan limiter `1mbit` secara kasar memberi waktu transfer sekitar `8s`, cukup jauh di atas threshold
- `telemetry_probe` berjalan tiap `30s` dan butuh `2` sampel berturut-turut, jadi `90s` adalah durasi aman
- `1mbit` biasanya masih membuat request terlihat sebagai slow response, bukan langsung timeout

Profil uji yang disarankan:

- validasi dasar: file `1MB`, port `8080`, `rate = 1mbit`, durasi `120s`
- uji dekat threshold: `rate = 2mbit`, durasi `90s`
- uji agresif: `rate = 500kbit`, tetapi ini bisa mendorong request mendekati timeout bila `http_max_time_sec` kecil

Catatan praktis penting:

- URL di `monitoring/default_config.json` harus sama dengan target yang diperlambat
- jika target memakai HTTPS publik, set `HTTP_SLOW_PORTS=443`
- untuk hasil paling repeatable, jangan mulai dari target web publik; mulai dari target lokal dulu

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

Langkah implementasi detail di script:

1. Untuk mode satu kali, script menurunkan interface upstream:

```bash
ip link set dev "${UPSTREAM_IF}" down
```

2. Script menunggu sesuai `down_seconds`:

```bash
sleep "${down_seconds}"
```

3. Script menaikkan lagi interface upstream:

```bash
ip link set dev "${UPSTREAM_IF}" up
```

4. Untuk mode `repeat`, pola di atas diulang:

```bash
down -> sleep "${down_seconds}" -> up -> sleep "${up_gap_seconds}" -> ulangi
```

Hotspot tetap dapat terlihat aktif, tetapi jalur dari laptop ke upstream menjadi putus-nyambung. Ini membuat event flap tampak sebagai perubahan berulang pada `connectivity_ok`, bukan sekadar satu kegagalan sesaat.

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

### Kondisi Ideal Awal

Parameter awal yang direkomendasikan:

- `repeat_count = 3`
- `down_seconds = 10-15`
- `up_gap_seconds = 5-10`
- baseline sebelum fault `30-60s`

Alasan:

- dengan `fast_interval_sec = 5`, durasi down yang lebih pendek dari `5s` berisiko tidak tertangkap
- `10-15s` memberi cukup waktu agar ada minimal satu sampai dua sampel gagal saat interface turun
- `3` flap biasanya cukup untuk menghasilkan lebih dari `2` transisi dalam `flap_window_sec = 30`

Mode uji yang disarankan:

- validasi dasar: `3x flap`, `down 15s`, `gap 10s`
- uji yang lebih cepat: `3x flap`, `down 10s`, `gap 5s`
- jika ingin tiap episode flap lebih mungkin tertutup dulu sebelum episode berikutnya, beri quiet gap yang jauh lebih panjang, misalnya `>40s`

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
