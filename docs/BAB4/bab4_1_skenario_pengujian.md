# BAB IV
## HASIL DAN PEMBAHASAN

### 4.1 Skenario Pengujian

Skenario pengujian dirancang untuk mengevaluasi performa dan efektivitas sistem detektor Micro-UXI dalam mendeteksi berbagai jenis gangguan jaringan (*fault*). Pengujian dilakukan dengan membandingkan dua metode deteksi utama, yaitu **Metode Baseline** (menggunakan *threshold* statis) dan **Metode Event-Driven** (menggunakan *threshold* dinamis berbasis *Exponential Weighted Moving Average* atau EWMA). 

Alur pengujian dibagi menjadi dua tahapan utama:
1. **Uji Pendahuluan (*Preliminary Test*):** Dilakukan pada kondisi jaringan normal tanpa gangguan untuk mengalibrasi nilai *threshold* dasar dan menentukan parameter pemicu (*trigger*) yang optimal secara teoretis dan empiris.
2. **Pengujian Utama (*Main Experiment*):** Dilakukan dengan menyuntikkan gangguan secara terprogram menggunakan mekanisme *fault injection* untuk mengukur sensitivitas, kecepatan deteksi, tingkat alarm palsu, dan beban sumber daya sistem (*overhead*) dari kedua metode.

Infrastruktur dan topologi pengujian melibatkan dua entitas fisik, yaitu Laptop penguji yang bertindak sebagai *Access Point* (AP) sekaligus *Injector*, serta perangkat klien (dalam penelitian ini menggunakan Arduino Uno Q) yang bertindak sebagai *Monitor* atau pengamat kondisi jaringan.

---

#### 4.1.1 Uji Pendahuluan (*Preliminary Test*)

*Preliminary test* dilakukan untuk mengamati karakteristik performa jaringan pada kondisi ideal (normal) tanpa adanya suntikan gangguan. Data yang terkumpul dari pengujian ini dianalisis untuk menetapkan konfigurasi detektor sebelum uji coba utama dilakukan.

##### 4.1.1.1 Strategi Sampling dan Durasi Pengujian
Pengambilan sampel data pada uji pendahuluan dilakukan secara paralel menggunakan dua jenis mekanisme pemantauan (*probe*) pada perangkat klien dengan rincian durasi sebagai berikut:
1. ***Fast Probe*:** Berjalan dengan interval waktu 2 detik per pengambilan sampel. Target pengambilan sampel minimum adalah 2.000 sampel (membutuhkan waktu operasional sekitar 1,1 jam). *Fast probe* digunakan untuk memantau metrik yang membutuhkan respons cepat, seperti latensi kueri DNS dan status ping dasar.
2. ***Telemetry Probe*:** Berjalan dengan interval waktu 20 detik per pengambilan sampel. Target pengambilan sampel minimum adalah 1.000 sampel (membutuhkan waktu operasional sekitar 5,6 jam). *Telemetry probe* digunakan untuk memantau metrik yang membutuhkan jendela pengamatan lebih luas dan komputasi lebih tinggi, seperti RTT batch, transaksi HTTP, dan stabilitas koneksi Wi-Fi.

Kedua *probe* dijalankan secara paralel selama minimal 5,6 jam di bawah kondisi lingkungan jaringan yang stabil, minim interferensi, dan bebas dari trafik padat lainnya untuk memastikan validitas data *baseline*.

##### 4.1.1.2 Penentuan Threshold Statis (Persentil ke-99 / P99)
Nilai *threshold* statis ($T_{static}$) untuk metrik latensi DNS, latensi RTT, dan transaksi HTTP dihitung menggunakan metode persentil ke-99 ($P_{99}$) dari data *baseline* sukses yang berhasil dikumpulkan selama uji pendahuluan. Penggunaan persentil ke-99 bertujuan agar sistem memiliki toleransi terhadap fluktuasi minor jaringan normal (hanya 1% data ekstrem yang berada di luar batas) sehingga meminimalkan risiko alarm palsu akibat noise pengukuran.

Perhitungan dilakukan secara spesifik untuk masing-masing target atau URL (*per-target / per-URL basis*) guna menghindari bias perbedaan latensi geografis atau kapasitas server target:
*   **Threshold Latensi DNS ($T_{dns}$):** Dihitung per nama domain target (misalnya `its.ac.id` untuk lingkup internal dan `google.com` untuk lingkup eksternal).
*   **Threshold Latensi RTT ($T_{rtt}$):** Dihitung berdasarkan latensi *ping* menuju server DNS publik (misalnya `8.8.8.8`).
*   **Threshold Transaksi HTTP ($T_{http\_total}$ dan $T_{http\_ttfb}$):** Dihitung berdasarkan waktu total unduh (*total duration*) dan waktu respons awal (*Time to First Byte* / TTFB) per URL target.

##### 4.1.1.3 Penentuan Parameter Konfirmasi Temporal (*Confirm Consecutive*)
Untuk event deteksi berbasis ambang batas numerik yang dievaluasi per sampel (S1 - DNS Degraded, S4 - High RTT, dan S5 - HTTP Slow), peningkatan metrik sesaat (*spike*) sering kali terjadi akibat fluktuasi normal jaringan. Untuk membedakan *spike* sesaat dengan degradasi persisten, digunakan parameter `confirm_consecutive` ($N$), yaitu jumlah sampel berturut-turut yang harus melewati threshold sebelum alarm dinyatakan aktif.

Pemilihan nilai $N$ didasarkan pada prinsip *trade-off* antara tingkat alarm palsu (*False Alarm Rate* / FAR) dan waktu deteksi rata-rata (*Mean Time to Detect* / MTTD). Dengan asumsi peluang satu sampel normal melewati threshold P99 adalah $p = 0,01$:
1.  **Estimasi Peluang Alarm Palsu ($P_{false\_run}$):** Peluang munculnya $N$ sampel abnormal berturut-turut pada kondisi jaringan normal didekati dengan:
    $$P_{false\_run} \approx p^N$$
2.  **Average Run Length sampai False Alarm ($\text{ARL}_N$):** Jumlah rata-rata sampel normal yang dievaluasi sebelum memicu satu alarm palsu dihitung dengan:
    $$\text{ARL}_N = \frac{1 - p^N}{(1 - p) \cdot p^N}$$
3.  **Tingkat Alarm Palsu per Jam ($\text{FAR}_N$):** Berdasarkan frekuensi evaluasi $\text{samples\_per\_hour} = \frac{3600}{\text{interval\_sampling}}$:
    $$\text{FAR}_N = \frac{\text{samples\_per\_hour}}{\text{ARL}_N}$$

*Trade-off* matematis berdasarkan variasi nilai $N$ dijabarkan pada Tabel 4.1 (untuk evaluasi Fast Probe 2 detik pada S1) dan Tabel 4.2 (untuk evaluasi Telemetry Probe 20 detik pada S4 dan S5):

**Tabel 4.1** Analisis *Trade-off* Parameter $N$ pada Fast Probe (Interval 2 Detik)
| $N$ | Peluang $P_{false\_run}$ | $\text{ARL}_N$ (Sampel) | Waktu Rata-rata sampai False Alarm | Est. $\text{FAR}$ per Jam | Penambahan Delay Deteksi |
|:---:|:------------------------:|:-----------------------:|:----------------------------------:|:-------------------------:|:------------------------:|
| 1 | $10^{-2}$ | 100 | 200 detik ≈ 3,3 menit | 18,00 | 0 detik |
| 2 | $10^{-4}$ | 10.100 | 20.200 detik ≈ 5,6 jam | 0,178 | 2 detik |
| 3 | $10^{-6}$ | 1.010.100 | 2.020.200 detik ≈ 23,4 hari | 0,00178 | 4 detik |
| 4 | $10^{-8}$ | 101.010.100 | 202.020.000 detik ≈ 6,4 tahun | 0,0000178 | 6 detik |

**Tabel 4.2** Analisis *Trade-off* Parameter $N$ pada Telemetry Probe (Interval 20 Detik)
| $N$ | Peluang $P_{false\_run}$ | $\text{ARL}_N$ (Sampel) | Waktu Rata-rata sampai False Alarm | Est. $\text{FAR}$ per Jam | Penambahan Delay Deteksi |
|:---:|:------------------------:|:-----------------------:|:----------------------------------:|:-------------------------:|:------------------------:|
| 1 | $10^{-2}$ | 100 | 2.000 detik ≈ 33,3 menit | 1,80 | 0 detik |
| 2 | $10^{-4}$ | 10.100 | 202.000 detik ≈ 56,1 jam | 0,0178 | 20 detik |
| 3 | $10^{-6}$ | 1.010.100 | 20.202.000 detik ≈ 233,8 hari | 0,000178 | 40 detik |
| 4 | $10^{-8}$ | 101.010.100 | 2.020.200.000 detik ≈ 64,0 tahun | 0,0000178 | 60 detik |

Berdasarkan analisis *trade-off* tersebut, nilai **$N = 2$** dipilih sebagai konfigurasi sistem. Nilai ini mampu menekan tingkat alarm palsu secara signifikan (menjadi 1 kali per 5,6 jam pada Fast Probe dan 1 kali per 56,1 jam pada Telemetry Probe) dengan penambahan delay deteksi yang minimal (2 detik pada Fast Probe dan 20 detik pada Telemetry Probe).

##### 4.1.1.4 Penentuan Parameter Aturan Jendela Geser (*m-of-n Rule*)
Untuk gangguan yang bersifat diskrit, intermiten, atau akumulatif dalam periode tertentu (S2 - DNS Timeout Burst, S3 - Loss Burst, dan S6 - Connectivity Flap), aturan konfirmasi konsekutif berturut-turut kurang efektif. Sebagai gantinya, digunakan aturan `m-of-n rule` yang menyatakan bahwa alarm aktif jika terdapat minimal $m$ sampel abnormal dalam $n$ sampel terakhir dalam jendela geser (*sliding window*).

Dengan asumsi peluang satu sampel bernilai abnormal secara acak pada kondisi jaringan normal adalah $p = 0,01$, jumlah sampel abnormal $X$ dalam jendela $n$ sampel dapat dimodelkan secara binomial:
$$X \sim \text{Binomial}(n, p)$$

Peluang alarm palsu per evaluasi jendela geser ($P_{FA}$) dihitung melalui fungsi distribusi kumulatif binomial:
$$P_{FA} = P(X \ge m) = \sum_{k=m}^{n} \binom{n}{k} \cdot p^k \cdot (1 - p)^{n - k}$$

Tingkat alarm palsu per jam ($\text{FAR}$) didekati dengan:
$$\text{FAR} \approx P_{FA} \cdot \text{samples\_per\_hour}$$

Berdasarkan kebutuhan masing-masing skenario, penentuan parameter $(m, n)$ dirinci sebagai berikut:

1.  **S2 - DNS Timeout Burst:** Diuji menggunakan Fast Probe (interval 2 detik) dengan ukuran jendela $n_{dns} = 10$ sampel (durasi jendela 20 detik). Peluang kegagalan kueri DNS normal diasumsikan $p = 0,01$. Analisis kandidat $m_{dns}$ disajikan pada Tabel 4.3.
    
    **Tabel 4.3** Analisis Kandidat $m_{dns}$ untuk Jendela Geser $n_{dns} = 10$
    | Rule | Makna Semantik | Peluang $P_{FA}$ | Est. $\text{FAR}$ per Jam | Keputusan Desain |
    |:---:|:---|:---:|:---:|:---:|
    | 1-of-10 | Minimal 1 DNS gagal dalam 20 detik | 0,0956 | 172,1 | Terlalu Sensitif |
    | 2-of-10 | Minimal 2 DNS gagal dalam 20 detik | 0,00427 | 7,68 | Sensitif |
    | **3-of-10** | **Minimal 3 DNS gagal dalam 20 detik** | **0,000114** | **0,205** | **Terpilih (Optimal)** |
    | 4-of-10 | Minimal 4 DNS gagal dalam 20 detik | 0,000002 | 0,0036 | Terlalu Konservatif |

    Konfigurasi **3-of-10** dipilih karena mewakili kejadian *burst* (kegagalan beruntun pendek) secara valid dengan tingkat alarm palsu yang sangat rendah (0,205 per jam).

2.  **S3 - Loss Burst:** Menggunakan Fast Probe (interval 2 detik) dengan ukuran jendela lebih lebar yaitu $n_{ping} = 20$ sampel (durasi jendela 40 detik) agar resolusi perhitungan rasio kehilangan paket (*loss ratio*) lebih halus (resolusi 5% per sampel). Peluang kehilangan paket acak normal diasumsikan $p = 0,01$. Analisis kandidat $m_{ping}$ disajikan pada Tabel 4.4.
    
    **Tabel 4.4** Analisis Kandidat $m_{ping}$ untuk Jendela Geser $n_{ping} = 20$
    | Rule | Makna Rasio Kehilangan Paket | Peluang $P_{FA}$ | Est. $\text{FAR}$ per Jam | Keputusan Desain |
    |:---:|:---|:---:|:---:|:---:|
    | 1-of-20 | Minimal 5% loss dalam 40 detik | 0,182 | 327,8 | Terlalu Sensitif |
    | 2-of-20 | Minimal 10% loss dalam 40 detik | 0,0169 | 30,35 | Sensitif |
    | 3-of-20 | Minimal 15% loss dalam 40 detik | 0,001 | 1,81 | Batas Toleransi |
    | **4-of-20** | **Minimal 20% loss dalam 40 detik** | **0,0000426** | **0,0767** | **Terpilih (Optimal)** |
    | 5-of-20 | Minimal 25% loss dalam 40 detik | 0,00000137 | 0,00246 | Terlalu Konservatif |

    Konfigurasi **4-of-20** dipilih karena mewakili tingkat *packet loss* yang signifikan (20%) dengan tingkat alarm palsu yang aman (0,0767 per jam).

3.  **S6 - Connectivity Flap:** Parameter abnormal yang diukur adalah transisi status konektivitas (*UP* ke *DOWN* atau sebaliknya). Menggunakan Fast Probe (interval 2 detik) dengan ukuran jendela $n_{flap} = 15$ sampel (durasi jendela 30 detik). Total pasangan sampel berurutan yang dapat dievaluasi transisinya adalah $n_{flap} - 1 = 14$ pasang. Peluang transisi acak pada kondisi normal diasumsikan $q = 0,01$. Analisis kandidat $m_{transition}$ disajikan pada Tabel 4.5.
    
    **Tabel 4.5** Analisis Kandidat $m_{transition}$ untuk $n_{flap} - 1 = 14$ Pasang Transisi
    | Rule | Makna Siklus Transisi | Peluang $P_{FA}$ | Est. $\text{FAR}$ per Jam | Keputusan Desain |
    |:---:|:---|:---:|:---:|:---:|
    | 1 transisi | Satu kali putus atau satu kali terhubung | 0,131 | 236,3 | Bukan Pola Flap |
    | 2 transisi | Satu siklus putus-pulih | 0,0084 | 15,12 | Flap Minimal |
    | 3 transisi | Perubahan status berulang ganjil | 0,000335 | 0,603 | Flap Sedang |
    | **4 transisi** | **Dua siklus putus-pulih lengkap** | **0,00000924** | **0,0166** | **Terpilih (Optimal)** |

    Konfigurasi **4 transisi** dipilih karena secara semantik menunjukkan koneksi yang tidak stabil secara berulang (*flapping*) dengan tingkat alarm palsu minimal (0,0166 per jam).

---

#### 4.1.2 Pengujian Utama (*Main Experiment*) dan Mekanisme Suntikan Gangguan

Pengujian utama bertujuan untuk mengevaluasi kinerja pendeteksian dari kedua metode detektor di bawah kondisi gangguan jaringan yang disuntikkan secara terprogram.

##### 4.1.2.1 Orkestrasi dan Siklus Eksperimen
Eksperimen dijalankan secara otomatis dan berulang kali (*looping*) untuk menjamin konsistensi data hasil uji. Setiap iterasi pengujian mengikuti tahapan berikut:
1.  **Inisialisasi Pengujian:** Skrip pengontrol gangguan di sisi laptop (`fault_master.py`) dan skrip pemantau di sisi klien (`monitor_master.py`) diaktifkan secara simultan. Parameter skenario ($S_1 - S_6$) diselaraskan menggunakan argumen `--event`.
2.  **Suntikan Gangguan (*Fault Injection*):** Skrip manipulasi mengeksekusi perintah manipulasi jaringan selama durasi yang ditentukan ($duration\_sec$).
3.  **Perekaman Data Riil:** Waktu mulai dan berakhirnya gangguan dicatat secara otomatis ke dalam file *ground truth* (`ground_truth.jsonl`) di sisi laptop sebagai acuan absolut.
4.  **Rollback dan Grace Period:** Setelah durasi gangguan selesai, skrip pembersih (`rollback_all_faults.sh`) secara paksa mereset seluruh konfigurasi manipulasi jaringan (`tc` dan `nftables`) agar jaringan kembali normal. Sistem kemudian dibiarkan dalam kondisi normal (*Grace Period*) selama minimal 60 detik sebelum memasuki iterasi berikutnya.
5.  **Perulangan Skenario:** Eksperimen ini diulang sebanyak 30 kali iterasi untuk setiap skenario gangguan guna menghasilkan sampel evaluasi yang signifikan secara statistik.

##### 4.1.2.2 Detail Teknis Skenario Gangguan (S1 - S6)
Detail mengenai alat manipulasi, penjelasan perintah baris demi baris (*line-by-line command*) yang dijalankan pada Laptop Injector, efek gangguan yang dihasilkan, serta bagaimana perangkat pemantau (Uno Q) melakukan pengukuran dan pendeteksian pada masing-masing skenario gangguan didefinisikan sebagai berikut:

###### S1 – DNS Degraded
*   **Alat yang Digunakan:** `nftables` dan `tc` (*Traffic Control* dengan modul `netem`).
*   **Perintah Utama (*Command*):**
    ```bash
    # 1. Menandai paket DNS (Port 53) dari subnet klien
    nft add rule ip fi_fault FI_MANGLE iifname "ap0" ip saddr "192.168.12.0/24" udp dport 53 meta mark set 53
    # 2. Membuat antrean prioritas pada root interface upstream
    tc qdisc add dev wlxd037456b1bc8 root handle 1: prio
    # 3. Menambahkan delay 400ms pada kelas prioritas pertama
    tc qdisc add dev wlxd037456b1bc8 parent 1:1 handle 10: netem delay 400ms
    # 4. Mengarahkan paket DNS bertanda 53 ke kelas prioritas yang terkena delay
    tc filter add dev wlxd037456b1bc8 parent 1: protocol ip prio 1 handle 53 fw flowid 1:1
    ```
*   **Penjelasan Perintah Baris demi Baris:**
    *   *Line 1 (`nft add rule ...`)*: Menambahkan aturan pada rantai firewall `FI_MANGLE` untuk menandai paket kueri DNS (UDP port 53) dari subnet klien `192.168.12.0/24` yang masuk lewat interface `ap0` dengan penanda numerik `53`.
    *   *Line 2 (`tc qdisc add ... root handle 1: prio`)*: Membuat disiplin antrean utama (*queueing discipline* / qdisc) bertipe kelas prioritas (`prio`) di root interface upstream `wlxd037456b1bc8` dengan penanda handle `1:`.
    *   *Line 3 (`tc qdisc add ... parent 1:1 ... netem delay 400ms`)*: Menyisipkan modul emulator jaringan (`netem`) di bawah kelas prioritas `1:1` (handle `10:`) untuk memperkenalkan tambahan waktu tunda/latensi sebesar 400ms.
    *   *Line 4 (`tc filter add ... handle 53 fw flowid 1:1`)*: Membuat filter klasifikasi berdasarkan tanda firewall (mark `53`) untuk membelokkan paket DNS tersebut ke kelas aliran data `1:1` agar mengalami penundaan latensi.
*   **Efek Gangguan:** Kueri DNS klien mengalami hambatan tambahan latensi sebesar 400 milidetik, sedangkan trafik ping dan HTTP lainnya mengalir normal tanpa delay.
*   **Mekanisme Pemantauan & Deteksi Uno Q:** Dipantau oleh skrip `test_s1_dns_degraded.py` (pada folder `fault-injection/fault-tester`) dengan langkah-langkah:
    1.  **Pengecekan Status Wi-Fi:** Membaca status operasional antarmuka Wi-Fi secara periodik dari berkas sistem `/sys/class/net/{iface}/operstate` (memastikan bernilai `up`).
    2.  **Pengecekan Konektivitas Dasar (Ping):** Mengeksekusi perintah ping tunggal ke IP target untuk memverifikasi jalur dasar:
        ```bash
        ping -c 1 -W 1 <ping_target>
        ```
    3.  **Pengukuran Latensi DNS:** Jika Wi-Fi aktif dan ping sukses, skrip mengirimkan kueri DNS ke resolver target setiap 2 detik:
        ```bash
        dig @<dns_resolver> +short +time=2 <dns_target>
        ```
        Latensi resolusi dihitung dari selisih waktu eksekusi perintah `dig`.
    4.  **Evaluasi Deteksi:** Nilai latensi dievaluasi terhadap threshold statis (243 ms) atau dinamis EWMA (`dynamic_threshold.py`). Alarm aktif jika latensi melebihi threshold berturut-turut sebanyak $N$ kali (`confirm_consecutive`).

###### S2 – DNS Timeout Burst
*   **Alat yang Digunakan:** `nftables` (*Firewall drop rules*).
*   **Perintah Utama (*Command*):**
    ```bash
    # 1. Membuang (drop) kueri DNS UDP port 53 dari subnet klien
    nft add rule ip fi_fault FI_FORWARD iifname "ap0" ip saddr "192.168.12.0/24" udp dport 53 drop
    # 2. Membuang (drop) kueri DNS TCP port 53 dari subnet klien
    nft add rule ip fi_fault FI_FORWARD iifname "ap0" ip saddr "192.168.12.0/24" tcp dport 53 drop
    ```
*   **Penjelasan Perintah Baris demi Baris:**
    *   *Line 1 (`nft add rule ... udp dport 53 drop`)*: Menambahkan aturan pada rantai forwarding firewall (`FI_FORWARD`) untuk mencocokkan kueri DNS UDP yang masuk dari interface `ap0` dan membuangnya secara instan (`drop`).
    *   *Line 2 (`nft add rule ... tcp dport 53 drop`)*: Menambahkan aturan serupa untuk membuang paket kueri DNS berbasis protokol TCP, memblokir alternatif resolusi DNS TCP klien.
*   **Efek Gangguan:** Seluruh paket kueri DNS dari klien dibuang secara mutlak, memaksa sistem klien mengalami kegagalan resolusi (*timeout*).
*   **Mekanisme Pemantauan & Deteksi Uno Q:** Dipantau oleh skrip `test_s2_dns_timeout.py` (pada folder `fault-injection/fault-tester`) dengan langkah-langkah:
    1.  **Pengecekan Wi-Fi & Ping:** Membaca berkas sistem `/sys/class/net/{iface}/operstate` and mengeksekusi ping dasar:
        ```bash
        ping -c 1 -W 1 <ping_target>
        ```
    2.  **Pengecekan Resolusi DNS:** Mengeksekusi resolusi DNS berkala menggunakan perintah:
        ```bash
        dig @<dns_resolver> +short +time=2 <dns_target>
        ```
    3.  **Evaluasi Deteksi:** Status sukses/gagal dari kueri DNS dicatat ke dalam antrean rolling `deque` berukuran `n_dns` (10 sampel). Alarm dipicu jika jumlah kegagalan DNS mencapai minimal `m_dns` (3 kegagalan) di dalam jendela geser tersebut.

###### S3 – Loss Burst
*   **Alat yang Digunakan:** `tc` (*Traffic Control* dengan modul `netem` loss).
*   **Perintah Utama (*Command*):**
    ```bash
    # 1. Membuang 40% paket data secara acak pada antarmuka upstream
    tc qdisc add dev wlxd037456b1bc8 root netem loss 40%
    ```
*   **Penjelasan Perintah Baris demi Baris:**
    *   *Line 1 (`tc qdisc add ... netem loss 40%`)*: Mengaitkan disiplin antrean emulator jaringan (`netem`) langsung pada root antarmuka upstream `wlxd037456b1bc8` untuk mensimulasikan kehilangan paket (*packet loss*) sebesar 40% pada seluruh trafik keluar.
*   **Efek Gangguan:** Kehilangan paket data (*packet loss*) sebesar 40% secara global untuk seluruh jenis trafik yang keluar dari antarmuka upstream laptop.
*   **Mekanisme Pemantauan & Deteksi Uno Q:** Dipantau oleh skrip `test_s3_loss_burst.py` (pada folder `fault-injection/fault-tester`) dengan langkah-langkah:
    1.  **Pengecekan Status Wi-Fi:** Membaca berkas sistem `/sys/class/net/{iface}/operstate` (memastikan bernilai `up`).
    2.  **Pengukuran Packet Loss:** Mengeksekusi perintah ping tunggal berkala ke target setiap 2 detik:
        ```bash
        ping -c 1 -W 1 <ping_target>
        ```
    3.  **Evaluasi Deteksi:** Hasil sukses/gagal ping dicatat dalam antrean `deque` berukuran `n_ping` (20 sampel). Alarm dipicu jika jumlah kegagalan ping mencapai minimal `m_ping` (4 kegagalan) di dalam jendela geser tersebut.

###### S4 – High RTT
*   **Alat yang Digunakan:** `nftables` dan `tc` (*Traffic Control* dengan modul `prio` dan `netem` delay).
*   **Perintah Utama (*Command*):**
    ```bash
    # 1. Membuat antrean prioritas 2 band dengan memetakan seluruh trafik bawaan ke band 1:2
    tc qdisc add dev wlxd037456b1bc8 root handle 1: prio bands 2 priomap 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1
    # 2. Menambahkan delay 300ms khusus pada band 1:2
    tc qdisc add dev wlxd037456b1bc8 parent 1:2 handle 20: netem delay 300ms
    # 3. Mengarahkan kueri DNS bertanda 53 ke band 1:1 yang bebas dari delay
    tc filter add dev wlxd037456b1bc8 parent 1: protocol ip prio 1 handle 53 fw flowid 1:1
    ```
*   **Penjelasan Perintah Baris demi Baris:**
    *   *Line 1 (`tc qdisc add ... root handle 1: prio bands 2 priomap ...`)*: Membuat qdisc kelas prioritas dengan 2 band. Konfigurasi `priomap` memaksa seluruh paket dengan prioritas IP TOS apa pun secara default masuk ke band kedua (`1:2` / indeks ke-1).
    *   *Line 2 (`tc qdisc add ... parent 1:2 ... netem delay 300ms`)*: Memasang emulator jaringan `netem` di bawah band `1:2` untuk menyuntikkan keterlambatan transmisi (*delay*) konstan sebesar 300ms pada semua lalu lintas default.
    *   *Line 3 (`tc filter add ... handle 53 fw flowid 1:1`)*: Menyaring paket bertanda firewall `53` (paket kueri DNS) untuk dilewatkan ke band pertama (`1:1`) yang bersih dari delay, sehingga kueri DNS klien dibebaskan dari gangguan delay RTT.
*   **Efek Gangguan:** Semua trafik (termasuk ping dan HTTP) mengalami delay tambahan latensi sebesar 300 milidetik, kecuali trafik kueri DNS yang dibebaskan dari delay.
*   **Mekanisme Pemantauan & Deteksi Uno Q:** Dipantau oleh skrip `test_s4_high_rtt.py` (pada folder `fault-injection/fault-tester`) dengan langkah-langkah:
    1.  **Pengecekan Status Wi-Fi:** Membaca berkas sistem `/sys/class/net/{iface}/operstate` (memastikan bernilai `up`).
    2.  **Pengecekan RTT & Loss Batch:** Mengeksekusi batch ping sebanyak 5 paket secara berkala (setiap 20 detik):
        ```bash
        ping -c 5 -i 0.2 -W 1 <ping_target>
        ```
        Skrip mengurai hasil untuk mendapatkan persentase paket hilang (`loss_pct`) dan rata-rata latensi RTT (`rtt_avg_ms`).
    3.  **Evaluasi Deteksi:** Nilai rata-rata RTT (`rtt_avg_ms`) dievaluasi terhadap threshold statis (279 ms) atau threshold dinamis EWMA (`dynamic_threshold.py`). Alarm aktif jika RTT rata-rata melebihi threshold berturut-turut sebanyak $N$ kali (`confirm_consecutive`).

###### S5 – HTTP Slow
*   **Alat yang Digunakan:** `tc` (*Traffic Control* dengan filter `u32` dan modul `tbf`/*Token Bucket Filter*).
*   **Perintah Utama (*Command*):**
    ```bash
    # 1. Membuat antrean prioritas 2 band pada interface Access Point
    tc qdisc add dev ap0 root handle 1: prio bands 2 priomap 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0
    # 2. Mengaitkan limitasi bandwidth TBF 1 Mbps pada band 1:2
    tc qdisc add dev ap0 parent 1:2 handle 20: tbf rate 1mbit burst 15000 latency 200ms
    # 3. Memfilter paket TCP port asal 8080 (HTTP Server) ke band 1:2 yang terlimit
    tc filter add dev ap0 parent 1:0 protocol ip prio 1 u32 match ip protocol 6 0xff match ip sport 8080 0xffff flowid 1:2
    ```
*   **Penjelasan Perintah Baris demi Baris:**
    *   *Line 1 (`tc qdisc add dev ap0 root ... prio bands 2 priomap ...`)*: Membuat qdisc kelas prioritas 2 band pada interface Access Point `ap0`. Konfigurasi `priomap` diatur agar seluruh trafik default dialirkan ke band pertama (`1:1` / indeks ke-0) yang bebas dari pembatasan.
    *   *Line 2 (`tc qdisc add dev ap0 parent 1:2 ... tbf rate 1mbit ...`)*: Menggunakan *Token Bucket Filter* (`tbf`) untuk membatasi kecepatan data maksimal 1 Mbps (`rate 1mbit`), dengan ukuran burst data 15 KB (`burst 15000`), dan batas buffer tunda antrean 200 ms.
    *   *Line 3 (`tc filter add ... u32 match ip protocol 6 0xff match ip sport 8080 0xffff flowid 1:2`)*: Membuat filter klasifikasi mentah `u32` untuk memeriksa paket IP yang menggunakan protokol TCP (nilai 6) dan memiliki nomor port sumber/asal `8080` (layanan HTTP Server), kemudian membelokkannya ke band terlimit `1:2`.
*   **Efek Gangguan:** Bandwidth untuk trafik HTTP lokal (TCP Port 8080) dibatasi secara ketat hingga maksimal 1 Mbps, memperlambat proses transaksi unduh objek HTTP tanpa memengaruhi latensi ping atau DNS.
*   **Mekanisme Pemantauan & Deteksi Uno Q:** Dipantau oleh skrip `test_s5_http_slow.py` (pada folder `fault-injection/fault-tester`) dengan langkah-langkah:
    1.  **Pengecekan Status Wi-Fi:** Membaca berkas sistem `/sys/class/net/{iface}/operstate` (memastikan bernilai `up`).
    2.  **Pengukuran Kinerja Transaksi HTTP:** Mengeksekusi pengunduhan berkas uji 1 MB via HTTP secara periodik (setiap 20 detik) menggunakan perintah `curl`:
        ```bash
        curl -s -o /dev/null -w "%{http_code}:%{time_total}:%{time_starttransfer}" --connect-timeout 5 --max-time 15 <url>
        ```
        Skrip mengurai output untuk mendapatkan kode status HTTP, durasi total unduh (`total_ms` dari `time_total` dikali 1000), dan waktu respon awal TTFB (`ttfb_ms` dari `time_starttransfer` dikali 1000).
    3.  **Evaluasi Deteksi:** Nilai `total_ms` and `ttfb_ms` dievaluasi terhadap threshold masing-masing. Alarm aktif jika salah satu metrik melanggar threshold statis (1.535 ms untuk total, 88 ms untuk TTFB) atau dinamis EWMA secara berturut-turut sebanyak $N$ kali (`confirm_consecutive`).

###### S6 – Connectivity Flap
*   **Alat yang Digunakan:** `iproute2` (`ip link` untuk kontrol status interface).
*   **Perintah Utama (*Command*):**
    ```bash
    # 1. Menonaktifkan (down) antarmuka upstream
    ip link set dev wlxd037456b1bc8 down
    # 2. Mengaktifkan kembali (up) antarmuka upstream
    ip link set dev wlxd037456b1bc8 up
    ```
*   **Penjelasan Perintah Baris demi Baris:**
    *   *Line 1 (`ip link set dev ... down`)*: Mematikan status tautan fisik/logis antarmuka upstream `wlxd037456b1bc8` secara paksa, yang menyebabkan hilangnya seluruh aliran paket data (pemutusan koneksi global).
    *   *Line 2 (`ip link set dev ... up`)*: Menyalakan kembali antarmuka untuk memulai proses negosiasi tautan nirkabel dan memulihkan arus paket data.
*   **Efek Gangguan:** Konektivitas jaringan ke internet terputus total saat interface bernilai `down` dan kembali terhubung saat interface bernilai `up`, menyimulasikan koneksi yang tidak stabil secara ekstrem.
*   **Mekanisme Pemantauan & Deteksi Uno Q:** Dipantau oleh skrip `test_s6_connectivity_flap.py` (pada folder `fault-injection/fault-tester`) dengan langkah-langkah:
    1.  **Pengecekan Status Antarmuka Wi-Fi:** Membaca berkas sistem `/sys/class/net/{iface}/operstate`.
    2.  **Pengecekan Konektivitas Ping:** Mengeksekusi perintah ping tunggal ke target:
        ```bash
        ping -c 1 -W 1 <ping_target>
        ```
    3.  **Evaluasi Konektivitas & Transaksi:** Status konektivitas global (`connectivity_ok`) bernilai `True` jika status Wi-Fi bernilai `up` dan ping berhasil. Status ini dicatat ke dalam antrean `deque` berukuran `n_flap` (15 sampel). Alarm aktif jika jumlah transisi status (perubahan boolean dalam antrean) bernilai minimal `m_transition` kali (4 transisi) dalam jendela geser tersebut.

---

#### 4.1.3 Metode Pembandingan Detektor

Eksperimen dievaluasi menggunakan dua pendekatan deteksi untuk mengukur performansi detektor Micro-UXI:

##### 4.1.3.1 Metode Baseline (Threshold Statis)
Detektor menggunakan batas toleransi numerik yang bersifat statis ($T_{static}$) yang telah dihitung dan disimpan di dalam file konfigurasi sistem berdasarkan persentil ke-99 ($P_{99}$) hasil uji pendahuluan. Batas ini tidak pernah berubah sepanjang pengujian utama berlangsung.

##### 4.1.3.2 Metode Event-Driven (Threshold Dinamis EWMA)
Detektor menghitung batas deteksi secara adaptif di setiap waktu pengambilan sampel $t$ menggunakan algoritma *Exponential Weighted Moving Average* (EWMA). Batas deteksi dinamis ($T_{dynamic, t}$) dihitung berdasarkan estimasi nilai rata-rata bergerak ($\mu_t$) dan nilai varians rata-rata bergerak ($v_t$) historis metrik:

$$\mu_t = \alpha \cdot x_t + (1 - \alpha) \cdot \mu_{t-1}$$

$$v_t = \beta \cdot (x_t - \mu_{t-1})^2 + (1 - \beta) \cdot v_{t-1}$$

$$T_{dynamic, t} = \mu_{t-1} + k \cdot \sqrt{v_{t-1}}$$

Dimana:
*   $x_t$ adalah nilai metrik teramati pada waktu $t$.
*   $\alpha$ dan $\beta$ adalah parameter bobot pemulusan (*smoothing factor*) untuk rata-rata dan varians (dikonfigurasi $\alpha = 0,1$ dan $\beta = 0,1$).
*   $k$ adalah faktor pengali deviasi standar untuk mengatur tingkat sensitivitas (dikonfigurasi $k = 3$).

**Logika Pembekuan Threshold (*Threshold Freezing*):**
Untuk mencegah naiknya nilai threshold akibat pengaruh metrik gangguan, pembaruan parameter $\mu_t$ dan $v_t$ ditangguhkan atau dibekukan ketika metrik teramati melebihi batas dinamis yang aktif ($x_t \ge T_{dynamic, t}$). Selama alarm aktif, nilai threshold dikunci pada kondisi normal terakhir hingga terdeteksi pemulihan kondisi jaringan.

---

#### 4.1.4 Metrik Evaluasi Perbandingan

Performa kedua metode dibandingkan secara kuantitatif berdasarkan parameter performansi berikut:
1.  **Precision:** Rasio alarm yang benar terhadap total alarm yang dikeluarkan sistem.
    $$\text{Precision} = \frac{\text{True Positive}}{\text{True Positive} + \text{False Positive}}$$
2.  **Recall:** Rasio gangguan yang berhasil terdeteksi terhadap total kejadian gangguan aktual.
    $$\text{Recall} = \frac{\text{True Positive}}{\text{True Positive} + \text{False Negative}}$$
3.  **F1-Score:** Rata-rata harmonis untuk mengevaluasi akurasi deteksi secara keseluruhan.
    $$\text{F1-Score} = 2 \cdot \frac{\text{Precision} \cdot \text{Recall}}{\text{Precision} + \text{Recall}}$$
4.  **Mean Time to Detect (MTTD):** Waktu tunda deteksi rata-rata yang dihitung dari selisih waktu suntikan pertama kali dengan waktu pemicuan alarm pada log detektor.
5.  **False Alarm Rate (FAR):** Frekuensi kemunculan alarm palsu selama masa observasi kondisi normal.
6.  **System Overhead:** Penggunaan sumber daya fisik perangkat monitor (Arduino Uno Q) yang diukur per 2 detik, meliputi utilisasi CPU (%), RAM (MB), dan bandwidth jaringan.
