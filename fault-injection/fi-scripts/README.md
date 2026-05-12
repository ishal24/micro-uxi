# Fault Injection Scripts for Micro-UXI

Folder ini berisi fault injector yang dipakai untuk skema `S1` sampai `S6`.
Mapping ke schema monitoring sekarang adalah:

- `fault_dns_delay.sh` -> `S1_DNS_DEGRADED`
- `fault_dns_outage.sh` -> `S2_DNS_TIMEOUT_BURST`
- `fault_loss.sh` -> `S3_LOSS_BURST`
- `fault_rtt.sh` -> `S4_HIGH_RTT`
- `fault_throttle.sh` -> `S5_HTTP_SLOW`
- `fault_flap.sh` -> `S6_CONNECTIVITY_FLAP`

`A1_BANDWIDTH_THROTTLE` masih tetap ada di `monitoring`, tapi belum punya injector khusus di folder ini. Script `fault_throttle.sh` dipakai untuk S5, bukan untuk A1.

## Topologi yang diasumsikan

Laptop punya dua adapter Wi-Fi:

- adapter internal -> jadi hotspot/AP untuk Uno Q
- adapter USB Wi-Fi -> konek ke Wi-Fi/internet upstream

Di script:

- `HOTSPOT_IF` = interface hotspot/AP
- `UPSTREAM_IF` = interface upstream/internet
- `CLIENT_SUBNET` = subnet Uno Q di belakang hotspot

Default helper masih:

```bash
HOTSPOT_IF=ap0
UPSTREAM_IF=wlxd037456b1bc8
CLIENT_SUBNET=192.168.12.0/24
```

Kalau nama interface di laptop kamu beda, override saat menjalankan script:

```bash
sudo HOTSPOT_IF=wlp0s20f3 UPSTREAM_IF=wlx123456789abc CLIENT_SUBNET=192.168.137.0/24 ./run_all_faults.sh
```

## Isi folder

- `fault_common.sh` -> helper shared, env var, parser config monitoring
- `fault_dns_delay.sh` -> injeksi DNS delay untuk S1
- `fault_dns_outage.sh` -> injeksi DNS outage burst untuk S2
- `fault_loss.sh` -> injeksi packet loss burst untuk S3
- `fault_rtt.sh` -> injeksi RTT increase untuk S4
- `fault_throttle.sh` -> injeksi HTTP slow untuk S5
- `fault_flap.sh` -> injeksi connectivity flap untuk S6
- `setup_http_server.sh` -> local HTTP target untuk eksperimen S5
- `run_all_faults.sh` -> runner berurutan S1-S6 + output ground truth
- `rollback_all_faults.sh` -> bersihkan semua qdisc/rule

## Rule penting

1. Jalankan satu fault pada satu waktu.
   Beberapa fault sama-sama memakai root qdisc, jadi jangan ditumpuk dulu.

2. Jalankan dengan `sudo`.

3. Sebelum pindah fault, rollback:

```bash
sudo ./rollback_all_faults.sh
```

## Sinkronisasi dengan monitoring

### S1, S2, S3, S4, S6

Kelima skenario ini langsung mempengaruhi metrik yang dibaca `monitoring`.

### S5 / HTTP_SLOW

S5 sekarang diperlakukan sebagai `HTTP_SLOW`, bukan `BANDWIDTH_THROTTLE`.
Injector-nya tetap bernama `fault_throttle.sh` karena mekanismenya membatasi trafik
HTTP tertentu agar transaksi HTTP menjadi lambat.

Untuk hasil yang paling stabil, pakai target HTTP lokal di hotspot:

1. jalankan `setup_http_server.sh`
2. masukkan URL hasil server itu ke `monitoring/default_config.json`
3. pastikan `telemetry_probe.http_targets` mengarah ke URL yang sama

Contoh target yang direkomendasikan:

```text
http://<hotspot-ip>:8080/testfile_1mb.bin
```

Script `run_all_faults.sh` akan mencoba membaca target HTTP pertama dari
`monitoring/default_config.json` supaya check S5 tetap selaras dengan monitoring.

## Ground truth output

`run_all_faults.sh` sekarang menghasilkan dua artefak:

- `fault_timeline_<ts>.csv`
  Timeline aksi detail: baseline start/end, fault start/stop, burst on/off, flap down/up.
- `ground_truth_<ts>.jsonl`
  Satu record ringkas per skenario fault yang berisi:
  - `scenario_id`
  - `event_type`
  - `fault_start_ts`
  - `fault_end_ts`
  - parameter injeksi
  - target scope / target URL bila relevan

File `ground_truth_*.jsonl` ini yang nantinya paling cocok dipakai untuk align ke
`event_meta.json` dan `ground_truth_ref.json` di output `monitoring`.

## Cara pakai cepat

### S1 - DNS degraded

```bash
sudo ./fault_dns_delay.sh start 400
sudo ./fault_dns_delay.sh stop
```

### S2 - DNS timeout burst

```bash
sudo ./fault_dns_outage.sh burst 3 8 5
```

### S3 - Loss burst

```bash
sudo ./fault_loss.sh start 15
sudo ./fault_loss.sh stop
```

### S4 - High RTT

```bash
sudo ./fault_rtt.sh start 200
sudo ./fault_rtt.sh stop
```

### S5 - HTTP slow

Rekomendasi:

```bash
bash ./setup_http_server.sh
sudo ./fault_throttle.sh start 1mbit
sudo ./fault_throttle.sh stop
```

Kalau mau target port selain `8080`, override:

```bash
sudo HTTP_SLOW_PORTS=443 ./fault_throttle.sh start 1mbit
```

### S6 - Connectivity flap

```bash
sudo ./fault_flap.sh once 5
sudo ./fault_flap.sh repeat 3 5 10
```

## Cek fault aktif

### `tc`

```bash
sudo tc qdisc show dev "$UPSTREAM_IF"
sudo tc qdisc show dev "$HOTSPOT_IF"
sudo tc filter show dev "$UPSTREAM_IF"
sudo tc filter show dev "$HOTSPOT_IF"
```

### `nft`

```bash
sudo nft list table ip fi_fault
```

## Rollback total

```bash
sudo ./rollback_all_faults.sh
```
