# Fault Injection Scripts for Micro-UXI Testbed

Scripts ini dibuat untuk setup yang sudah kamu tunjukkan:
- Hotspot/AP interface: `wlp0s20f3`
- Upstream/internet interface: `wlxd037456b1bc8`

## Isi folder
- `fault_common.sh` → helper functions + variabel interface
- `fault_rtt.sh` → inject delay/RTT increase
- `fault_loss.sh` → inject packet loss burst
- `fault_throttle.sh` → inject bandwidth throttling
- `fault_flap.sh` → inject connectivity flap
- `fault_dns_outage.sh` → drop DNS packets (timeout/outage)
- `fault_dns_delay.sh` → delay DNS packets saja
- `rollback_all_faults.sh` → hapus semua rule/qdisc yang dipakai script-script ini

## Rule penting
1. Jalankan **satu fault pada satu waktu** dulu.
   - Alasannya: beberapa fault memakai `tc root qdisc` pada interface yang sama.
   - Kalau butuh kombinasi fault, itu bisa dibuat nanti, tapi jangan dulu.

2. Jalankan pakai `sudo`.
   Contoh:
   ```bash
   sudo ./fault_rtt.sh start 200
   sudo ./fault_rtt.sh stop
   ```

3. Sebelum pindah ke fault lain, lakukan rollback:
   ```bash
   sudo ./rollback_all_faults.sh
   ```

## Cara pakai cepat

### 1) RTT increase
Tambah delay 200 ms:
```bash
sudo ./fault_rtt.sh start 200
```

Stop:
```bash
sudo ./fault_rtt.sh stop
```

### 2) Packet loss
Loss 15%:
```bash
sudo ./fault_loss.sh start 15
```

Stop:
```bash
sudo ./fault_loss.sh stop
```

### 3) Bandwidth throttling
Batasi ke 2 mbit:
```bash
sudo ./fault_throttle.sh start 2mbit
```

Stop:
```bash
sudo ./fault_throttle.sh stop
```

### 4) Connectivity flap
Putus 5 detik, lalu balik nyala:
```bash
sudo ./fault_flap.sh once 5
```

Flap 3x, putus 5 detik, jeda 10 detik:
```bash
sudo ./fault_flap.sh repeat 3 5 10
```

### 5) DNS outage burst
Drop DNS dari client hotspot selama 10 detik:
```bash
sudo ./fault_dns_outage.sh start
sleep 10
sudo ./fault_dns_outage.sh stop
```

Atau burst otomatis 3 kali:
```bash
sudo ./fault_dns_outage.sh burst 3 8 5
```

### 6) DNS delay
Delay DNS 400 ms:
```bash
sudo ./fault_dns_delay.sh start 400
```

Stop:
```bash
sudo ./fault_dns_delay.sh stop
```

## Cara cek fault aktif atau tidak

### Cek qdisc `tc`
```bash
sudo tc qdisc show dev wlxd037456b1bc8
sudo tc filter show dev wlxd037456b1bc8
```

### Cek rules iptables yang dipakai fault DNS
```bash
sudo iptables -S FI_DNS_OUTAGE
sudo iptables -t mangle -S FI_DNS_MARK
```

## Rollback total
Kalau habis eksperimen ada yang nyangkut, langsung:
```bash
sudo ./rollback_all_faults.sh
```

## Catatan teknis singkat
- RTT/loss/throttle/dns-delay dipasang di **upstream interface** (`wlxd037456b1bc8`).
- DNS outage diseleksi dari trafik client hotspot yang masuk dari `wlp0s20f3`.
- Connectivity flap memutus interface upstream, jadi hotspot tetap ada, tapi jalur keluar putus.
