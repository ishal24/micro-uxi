# Penjelasan Teknis Implementasi Fault Injection

Dokumen ini membedah **bagaimana cara kerja di balik layar** dari skrip-skrip injeksi (S1 - S6) yang ada di folder ini. Tujuannya adalah untuk memahami mekanisme manipulasi jaringan di level Sistem Operasi (Linux) tanpa harus membaca kode bash baris demi baris.

---

## Konsep Dasar & Alat Utama

Karena topologi pengujian kita menggunakan laptop sebagai "router/hotspot" (`Uno Q -> Hotspot Laptop -> Wi-Fi Upstream -> Internet`), laptop memiliki kendali penuh atas paket data yang lewat. Kita menggunakan dua alat utama bawaan Linux:

1. **`tc` (Traffic Control / iproute2):** Digunakan untuk menambah *delay*, *packet loss*, atau membatasi *bandwidth* (shaping).
2. **`nftables` (Pengganti iptables):** Digunakan untuk memblokir paket secara mutlak (drop) atau memberi "tanda" (mark) pada paket spesifik (seperti paket DNS) agar bisa diproses secara berbeda oleh `tc`.

---

## Implementasi Per Skenario (S1 - S6)

### S1 - DNS Degraded (`fault_dns_delay.sh`)
**Tujuan:** Membuat resolusi DNS lambat, tapi Ping dan HTTP tetap cepat.
**Cara Implementasi:**
1. Menggunakan `nftables`, skrip menandai (memberi *mark 53*) khusus untuk trafik UDP dan TCP di **Port 53 (DNS)** yang berasal dari subnet klien hotspot (Uno Q).
2. Menggunakan `tc prio`, skrip membagi antrean jaringan di antarmuka upstream menjadi beberapa jalur (band).
3. Skrip memasang `tc netem delay` (contoh: 400ms) **hanya** pada jalur nomor 1 (`band 1:1`).
4. Skrip mengarahkan paket yang memiliki *mark 53* tadi agar masuk ke jalur nomor 1 tersebut. 
**Hasil:** Hanya trafik DNS yang terhambat, trafik lain mengalir normal di jalur default.

**Command Inti di Level OS (Under the hood):**
```bash
# Membuat tabel dan menandai paket DNS (Port 53) dari klien hotspot
nft add table ip fi_fault
nft add chain ip fi_fault FI_MANGLE '{ type filter hook prerouting priority -150; policy accept; }'
nft add rule ip fi_fault FI_MANGLE iifname "ap0" ip saddr "192.168.12.0/24" udp dport 53 meta mark set 53
nft add rule ip fi_fault FI_MANGLE iifname "ap0" ip saddr "192.168.12.0/24" tcp dport 53 meta mark set 53

# Membagi antrean di interface upstream dan menambahkan delay 400ms ke jalur spesifik
tc qdisc add dev wlxd037456b1bc8 root handle 1: prio
tc qdisc add dev wlxd037456b1bc8 parent 1:1 handle 10: netem delay 400ms

# Mengarahkan paket yang ditandai (DNS) masuk ke jalur delay
tc filter add dev wlxd037456b1bc8 parent 1: protocol ip prio 1 handle 53 fw flowid 1:1
```
**Command Rollback / Pembersihan:**
```bash
tc qdisc del dev wlxd037456b1bc8 root
nft delete table ip fi_fault
```
**Mengapa ini memicu S1:** 
Saat `fast_probe` atau `telemetry_probe` di Arduino melakukan *query* DNS, delay buatan ini akan membuat waktu resolusi melebihi batas `dns_latency_threshold_ms` (misalnya 243ms). Jika kondisi ini tertangkap sebanyak `confirm_consecutive` kali secara berturut-turut, detektor akan mengklasifikasikannya sebagai `DNS_DEGRADED`.

### S2 - DNS Timeout Burst (`fault_dns_outage.sh`)
**Tujuan:** Membuat kueri DNS gagal total (timeout) dalam beberapa detik, lalu normal lagi.
**Cara Implementasi:**
1. Skrip membuat tabel *firewall* sementara di `nftables` pada *hook* `forward` (jalur lintas paket dari hotspot ke luar).
2. Skrip memasukkan aturan: **"Jika paket dari Hotspot menuju Port 53 (UDP/TCP), maka `drop` (buang)!"**.
3. Karena menggunakan mode *burst/start_stop*, skrip master python akan membiarkan *rule drop* ini aktif selama beberapa detik, lalu mematikan/menghapusnya, dan mengulanginya lagi.
**Hasil:** Uno Q sama sekali tidak mendapat balasan saat melakukan kueri DNS.

**Command Inti di Level OS (Under the hood):**
```bash
# Membuat tabel firewall dan langsung membuang (drop) paket DNS
nft add table ip fi_fault
nft add chain ip fi_fault FI_FORWARD '{ type filter hook forward priority -1; policy accept; }'
nft add rule ip fi_fault FI_FORWARD iifname "ap0" ip saddr "192.168.12.0/24" udp dport 53 drop
nft add rule ip fi_fault FI_FORWARD iifname "ap0" ip saddr "192.168.12.0/24" tcp dport 53 drop
```
**Mengapa ini memicu S2:**
Aturan `drop` menyebabkan alat `dig` pada probe mengalami *timeout*. Sampel DNS akan ditandai sebagai gagal. Evaluator menggunakan aturan `m-of-n rule` (misal: butuh 3 kegagalan dalam jendela 10 sampel). Terputusnya trafik DNS ini akan secara cepat mendongkrak hitungan kegagalan, sehingga event `DNS_TIMEOUT_BURST` aktif.

### S3 - Loss Burst (`fault_loss.sh`)
**Tujuan:** Membuat *packet loss* parah (misal: 40%) di semua trafik, membuat koneksi putus-nyambung secara acak.
**Cara Implementasi:**
1. Skrip secara brutal memasang `tc netem loss 40%` sebagai antrean utama (root qdisc) di antarmuka jaringan upstream.
2. Aturan ini mencegat seluruh paket data yang akan keluar dari laptop menuju internet dan secara probabilistik (acak) membuang 40% di antaranya.
**Hasil:** Ping banyak yang RTO (Request Timeout), streaming video bisa putus-putus, walau logo Wi-Fi masih tersambung.

**Command Inti di Level OS (Under the hood):**
```bash
# Membuang 40% dari seluruh paket yang keluar dari interface upstream
tc qdisc add dev wlxd037456b1bc8 root netem loss 40%
```
**Command Rollback / Pembersihan:**
```bash
tc qdisc del dev wlxd037456b1bc8 root
```
**Mengapa ini memicu S3:**
Probe yang terus-menerus mengirim `ping` (ICMP Echo) akan mulai gagal menerima respons akibat *packet loss* buatan. Detektor akan melihat metrik kegagalan ping meningkat dalam jendela waktu yang telah ditentukan (*sliding window*). Jika rasio atau akumulasi kegagalannya melampaui `loss_threshold_pct` atau parameter `m_ping`, `LOSS_BURST` akan menyala.

### S4 - High RTT (`fault_rtt.sh`)
**Tujuan:** Membuat RTT (Ping/Latency umum) melonjak tinggi, tetapi anehnya resolusi DNS tetap cepat (untuk mengecualikan event S1).
**Cara Implementasi:**
Ini adalah kebalikan dari S1.
1. Menggunakan `nftables`, paket DNS diberi *mark 53*.
2. Menggunakan `tc prio`, dibuatlah 2 jalur. Jalur default adalah jalur nomor 2 (`band 1:2`).
3. Skrip memasang `tc netem delay` (contoh: 300ms) di jalur default (`1:2`).
4. Skrip membuat filter: "Khusus paket *mark 53* (DNS), arahkan ke jalur khusus nomor 1 (`1:1`) yang bebas hambatan/delay".
**Hasil:** Ping dan HTTP menjadi sangat lambat (300ms+), tetapi kueri `dig google.com` tetap selesai dalam ~20ms.

**Command Inti di Level OS (Under the hood):**
```bash
# Menandai paket DNS seperti pada S1
nft add table ip fi_fault
nft add chain ip fi_fault FI_MANGLE '{ type filter hook prerouting priority -150; policy accept; }'
nft add rule ip fi_fault FI_MANGLE iifname "ap0" ip saddr "192.168.12.0/24" udp dport 53 meta mark set 53
nft add rule ip fi_fault FI_MANGLE iifname "ap0" ip saddr "192.168.12.0/24" tcp dport 53 meta mark set 53

# Membagi 2 antrean: antrean default (band 2) diberi delay 300ms
tc qdisc add dev wlxd037456b1bc8 root handle 1: prio bands 2 priomap 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1
tc qdisc add dev wlxd037456b1bc8 parent 1:2 handle 20: netem delay 300ms

# Mengarahkan paket DNS (mark 53) ke band 1 yang BEBAS delay
tc filter add dev wlxd037456b1bc8 parent 1: protocol ip prio 1 handle 53 fw flowid 1:1
```
**Mengapa ini memicu S4:**
Saat `telemetry_probe` mengirim sekumpulan ping, responsnya akan terlambat 300ms sesuai konfigurasi *delay* `tc`. Akibatnya, nilai `rtt_avg_ms` melonjak di atas batas wajar (misal `279ms`). Namun, karena resolusi DNS diarahkan ke jalur yang aman, detektor memastikan masalah utamanya ada di latensi koneksi (RTT), bukan di layanan DNS. Event `HIGH_RTT` aktif setelah dikonfirmasi berturut-turut.

### S5 - HTTP Slow (`fault_throttle.sh`)
**Tujuan:** Membuat transaksi HTTP menjadi sangat lambat (download lemot) tanpa memengaruhi Ping/DNS.
**Cara Implementasi:**
Skenario ini menggunakan teknik *Rate Limiting / Shaping* (bukan delay).
1. Skrip memasang `tc tbf` (Token Bucket Filter) untuk membatasi *bandwidth* aliran data (contoh: dilimit hanya 1mbit atau lambat).
2. Skrip memasang filter `u32` (microcode) yang secara spesifik hanya mencocokkan paket **TCP** dari **Port 8080** (atau port HTTP target).
3. Hanya trafik dari port tersebut yang dilewatkan ke jalur *Token Bucket Filter* tadi.
**Hasil:** Transaksi HTTP untuk file besar akan memakan waktu lama (karena bandwidth dicekik), tetapi ICMP (Ping) tetap lancar jaya.

**Command Inti di Level OS (Under the hood):**
```bash
# Membagi antrean di interface hotspot (ap0)
tc qdisc add dev ap0 root handle 1: prio bands 2 priomap 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0

# Membuat Token Bucket Filter (TBF) untuk melimit kecepatan jadi 1mbit
tc qdisc add dev ap0 parent 1:2 handle 20: tbf rate 1mbit burst 15000 latency 200ms

# Memfilter spesifik paket TCP port 8080 (target HTTP lokal) ke jalur limitasi tersebut
tc filter add dev ap0 parent 1:0 protocol ip prio 1 u32 match ip protocol 6 0xff match ip sport 8080 0xffff flowid 1:2
```
**Mengapa ini memicu S5:**
Probe `telemetry` melakukan pengecekan `curl` ke sebuah URL. Limitasi bandwidth yang agresif (misalnya `1mbit`) akan memaksa pengunduhan (atau transmisi HTTP) berjalan perlahan. Hal ini menyebabkan parameter `http_total_ms` (total durasi transfer) meningkat tajam melewati `http_total_threshold_ms`. Probe mendeteksi DNS dan RTT normal, tetapi HTTP lambat, sehingga event `HTTP_SLOW` terpicu.

### S6 - Connectivity Flap (`fault_flap.sh`)
**Tujuan:** Mensimulasikan koneksi yang "kedap-kedip" (putus-nyambung secara ekstrem).
**Cara Implementasi:**
Sangat sederhana namun efektif.
1. Skrip menggunakan perintah dasar Linux `ip link set dev <interface> down` untuk secara paksa mematikan antarmuka Wi-Fi upstream.
2. Sistem akan menunggu beberapa detik (contoh: 10 detik).
3. Skrip memanggil `ip link set dev <interface> up` untuk menyalakannya kembali.
4. Loop ini diulang beberapa kali.
**Hasil:** Arduino Uno Q mendapati `connectivity_ok` berubah `true -> false -> true` berulang kali secara dramatis.

**Command Inti di Level OS (Under the hood):**
```bash
# Mematikan paksa interface upstream (membuat internet terputus)
ip link set dev wlxd037456b1bc8 down
```
*(Mengulangi putus-nyambung 3 kali, dengan durasi down 5 detik, dan up 10 detik)*

**Mengapa ini memicu S6:**
`fast_probe` senantiasa mengevaluasi koneksi dasar (`ping.success`). Siklus turun dan naiknya antarmuka memaksa metrik ini berubah. Sistem menganggap satu kali "turun lalu naik" sebagai 2 transisi. Apabila ada beberapa perubahan kondisi ini (misal 4 transisi/`m_transition` = 2 siklus putus-pulih) dalam jendela waktu tertentu, `CONNECTIVITY_FLAP` akan terpicu.

---

## Orkestrasi & Rollback

Tantangan terbesar menggunakan `tc` dan `nftables` adalah **"aturan yang nyangkut"**. Jika skrip dihentikan paksa (misal karena *error*), aturan delay atau loss bisa tetap menempel selamanya di laptop Anda dan membuat internet lambat secara permanen.

Untuk mencegahnya, sistem ini memiliki file **`rollback_all_faults.sh`**.
File ini bertindak sebagai "Sapu Jagat" yang dengan brutal menghapus seluruh tabel `fi_fault` di `nftables` dan mereset antrean utama `tc qdisc del dev <interface> root` untuk kedua antarmuka (hotspot dan upstream). Master skrip selalu mengeksekusi file ini di setiap masa *grace period*.

**Penggunaan Command:**
```bash
sudo ./rollback_all_faults.sh
```
