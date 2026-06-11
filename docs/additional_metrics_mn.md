# Penentuan `m-of-n Rule`

## 1. Definisi

`m-of-n rule` adalah aturan konfirmasi event yang menyatakan bahwa suatu event aktif jika terdapat minimal `m` kejadian abnormal dalam `n` sampel terakhir.

Secara umum:

```text
event_active = true jika abnormal_count >= m dalam n sampel terakhir
```

dengan:

```text
m = jumlah minimum kejadian abnormal
n = jumlah sampel dalam sliding window
```

Pada penelitian ini, `m-of-n rule` digunakan untuk event berbasis kejadian diskrit, count, ratio, atau transisi state, yaitu:

```text
S2 DNS_TIMEOUT_BURST
S3 LOSS_BURST
S6 CONNECTIVITY_FLAP
```

Event tersebut memiliki karakteristik berupa kejadian abnormal yang dapat muncul secara intermittent dalam periode pendek. Berbeda dari event berbasis threshold numerik yang harus bertahan secara berturut-turut, event berbasis `m-of-n` tidak mensyaratkan kejadian abnormal terjadi secara berurutan.

---

## 2. Tujuan Penggunaan `m-of-n Rule`

Penggunaan `m-of-n rule` bertujuan untuk mendeteksi pola gangguan yang muncul beberapa kali dalam window pendek, tetapi tidak selalu berturut-turut.

Contoh sequence DNS:

```text
OK, FAIL, OK, FAIL, OK, OK, OK, OK, OK, FAIL
```

Jika menggunakan `confirm_consecutive = 3`, sequence tersebut tidak akan trigger karena tidak ada 3 `FAIL` berturut-turut.

Namun, jika menggunakan:

```text
m = 3
n = 10
```

maka event aktif karena terdapat 3 DNS failure dalam 10 sampel terakhir.

Dengan demikian, `m-of-n rule` digunakan untuk mendeteksi gangguan berbentuk burst atau intermittent failure.

Contoh event yang cocok:

```text
DNS_TIMEOUT_BURST:
  beberapa DNS query gagal dalam window pendek

LOSS_BURST:
  beberapa ping gagal dalam window pendek

CONNECTIVITY_FLAP:
  beberapa perubahan state konektivitas terjadi dalam window pendek
```

---

## 3. Dasar Teoretis

Pemilihan `m-of-n rule` didasarkan pada prinsip trade-off antara **false alarm rate** dan **mean time to detect**.

Dalam anomaly-based detection, konfigurasi detector yang terlalu sensitif dapat menghasilkan deteksi cepat, tetapi meningkatkan false alarm. Sebaliknya, konfigurasi yang terlalu konservatif dapat menurunkan false alarm, tetapi meningkatkan waktu deteksi.

Pada `m-of-n rule`, sensitivitas detector dikendalikan oleh dua parameter:

```text
m = jumlah minimum abnormal event
n = jumlah sampel dalam window
```

Pengaruh parameter:

```text
m kecil:
  deteksi lebih cepat
  false alarm lebih tinggi

m besar:
  false alarm lebih rendah
  deteksi lebih lambat atau lebih sulit trigger

n kecil:
  window pendek
  deteksi lebih cepat
  tetapi rasio lebih kasar

n besar:
  window lebih stabil
  false alarm lebih rendah
  tetapi burst pendek dapat terdilusi
```

Prinsip ini sejalan dengan pendekatan pemilihan parameter detector yang mempertimbangkan trade-off antara false positive dan detection delay.

---

## 4. Asumsi Perhitungan

Pada penelitian ini, event yang menggunakan `m-of-n rule` dievaluasi melalui fast probe.

Asumsi dasar:

```text
fast_interval = 2 detik
samples_per_hour = 3600 / 2
samples_per_hour = 1800 sampel/jam
```

Untuk event S2 dan S3, satu sampel dianggap abnormal jika terjadi failure.

```text
S2 DNS_TIMEOUT_BURST:
  abnormal jika dns_success == false

S3 LOSS_BURST:
  abnormal jika ping.success == false
```

Untuk S6, abnormal event yang dihitung bukan failure langsung, tetapi perubahan state konektivitas.

```text
S6 CONNECTIVITY_FLAP:
  abnormal event = transition pada connectivity_ok
```

Asumsi probabilitas normal:

```text
p = peluang satu sampel normal menjadi abnormal
```

Jika tidak tersedia nilai empiris dari baseline, nilai awal yang digunakan untuk perhitungan teoretis adalah:

```text
p = 0.01
```

Artinya, pada kondisi normal diasumsikan sekitar 1% sampel dapat terlihat abnormal karena variasi sesaat, noise, atau kegagalan sporadis.

Untuk S6, digunakan simbol berbeda:

```text
q = peluang terjadi satu transisi state pada kondisi normal
```

Jika tidak tersedia nilai empiris, nilai awal yang digunakan adalah:

```text
q = 0.01
```

Catatan:

```text
p digunakan untuk DNS failure dan ping failure.
q digunakan untuk state transition pada connectivity flap.
```

---

## 5. Estimasi False Alarm Rate untuk `m-of-n Rule`

Jika peluang satu sampel abnormal pada kondisi normal adalah `p`, maka jumlah kejadian abnormal dalam `n` sampel dapat dimodelkan secara sederhana sebagai distribusi binomial:

```text
X ~ Binomial(n, p)
```

dengan:

```text
X = jumlah sampel abnormal dalam n sampel
n = jumlah sampel dalam window
p = peluang satu sampel abnormal pada kondisi normal
```

False alarm terjadi jika:

```text
X >= m
```

Maka peluang false alarm per evaluasi window dapat didekati sebagai:

```text
P_FA = P(X >= m)
```

Rumus lengkap:

```text
P_FA = Σ from k=m to n [ C(n,k) × p^k × (1-p)^(n-k) ]
```

dengan:

```text
C(n,k) = kombinasi n pilih k
```

False alarm rate per jam dapat didekati dengan:

```text
FAR ≈ P_FA × samples_per_hour
```

Karena sliding window dievaluasi berulang dan window saling overlap, nilai FAR per jam ini merupakan estimasi pendekatan, bukan nilai absolut. Namun, perhitungan ini tetap berguna untuk membandingkan sensitivitas antar nilai `m` dan `n`.

---

## 6. Perhitungan untuk S2 `DNS_TIMEOUT_BURST`

S2 `DNS_TIMEOUT_BURST` mendeteksi beberapa DNS failure atau timeout dalam window pendek.

Definisi abnormal:

```text
dns_success == false
```

Konfigurasi awal:

```text
fast_interval = 2 detik
n_dns = 10 sampel
W_dns = n_dns × fast_interval
W_dns = 10 × 2
W_dns = 20 detik
```

Asumsi:

```text
p_dns = 0.01
```

Artinya, pada kondisi normal diasumsikan peluang satu DNS query gagal adalah 1%.

Dengan:

```text
X_dns ~ Binomial(10, 0.01)
```

maka peluang false alarm untuk beberapa kandidat `m_dns` adalah:

|      Rule | Makna                                | `P_FA = P(X >= m)` | Approx FAR per jam |
| --------: | ------------------------------------ | -----------------: | -----------------: |
| `1-of-10` | minimal 1 DNS failure dalam 20 detik |           `0,0956` |        `172,1/jam` |
| `2-of-10` | minimal 2 DNS failure dalam 20 detik |          `0,00427` |         `7,68/jam` |
| `3-of-10` | minimal 3 DNS failure dalam 20 detik |         `0,000114` |        `0,205/jam` |
| `4-of-10` | minimal 4 DNS failure dalam 20 detik |       `0,00000200` |       `0,0036/jam` |

Interpretasi:

```text
1-of-10 terlalu sensitif karena satu DNS failure langsung dapat memicu event.

2-of-10 masih cukup sensitif, tetapi false alarm teoretis masih relatif tinggi.

3-of-10 mulai merepresentasikan burst karena membutuhkan beberapa DNS failure dalam window pendek.

4-of-10 lebih konservatif dan lebih aman terhadap false alarm, tetapi membutuhkan failure yang lebih berat sebelum event aktif.
```

Berdasarkan trade-off tersebut, konfigurasi awal yang dapat digunakan adalah:

```text
n_dns = 10
m_dns = 3
```

Maknanya:

```text
DNS_TIMEOUT_BURST aktif jika terdapat minimal 3 DNS failure dalam 10 sampel terakhir,
atau sekitar 3 failure dalam window 20 detik.
```

Nilai ini tidak diklaim sebagai nilai optimal universal, tetapi sebagai konfigurasi desain awal yang menyeimbangkan sensitivitas deteksi dan false alarm.

---

## 7. Perhitungan untuk S3 `LOSS_BURST`

S3 `LOSS_BURST` mendeteksi peningkatan packet loss dalam window pendek.

Definisi abnormal:

```text
ping.success == false
```

Konfigurasi awal:

```text
fast_interval = 2 detik
n_ping = 20 sampel
W_ping = n_ping × fast_interval
W_ping = 20 × 2
W_ping = 40 detik
```

Alasan `n_ping` lebih besar dari `n_dns`:

```text
Packet loss lebih baik direpresentasikan sebagai rasio.
Semakin besar n, semakin halus resolusi rasio loss.
```

Resolusi rasio:

```text
n_ping = 20
resolution = 1 / 20
resolution = 5%
```

Artinya:

```text
1 ping failure dari 20 sampel = 5% loss
2 ping failure dari 20 sampel = 10% loss
4 ping failure dari 20 sampel = 20% loss
5 ping failure dari 20 sampel = 25% loss
```

Asumsi:

```text
p_ping = 0.01
```

Dengan:

```text
X_ping ~ Binomial(20, 0.01)
```

maka peluang false alarm untuk beberapa kandidat `m_ping` adalah:

|      Rule | Makna                           | `P_FA = P(X >= m)` | Approx FAR per jam |
| --------: | ------------------------------- | -----------------: | -----------------: |
| `1-of-20` | minimal 5% loss dalam 40 detik  |            `0,182` |        `327,8/jam` |
| `2-of-20` | minimal 10% loss dalam 40 detik |           `0,0169` |        `30,35/jam` |
| `3-of-20` | minimal 15% loss dalam 40 detik |          `0,00100` |         `1,81/jam` |
| `4-of-20` | minimal 20% loss dalam 40 detik |        `0,0000426` |       `0,0767/jam` |
| `5-of-20` | minimal 25% loss dalam 40 detik |       `0,00000137` |      `0,00246/jam` |

Interpretasi:

```text
1-of-20 dan 2-of-20 terlalu sensitif untuk mendefinisikan LOSS_BURST.

3-of-20 mulai mendeteksi loss yang bermakna, tetapi false alarm teoretis masih lebih tinggi.

4-of-20 merepresentasikan sekitar 20% packet loss dalam window 40 detik, sehingga cukup kuat untuk disebut LOSS_BURST.

5-of-20 lebih konservatif karena membutuhkan sekitar 25% packet loss.
```

Berdasarkan trade-off tersebut, konfigurasi awal yang dapat digunakan adalah:

```text
n_ping = 20
m_ping = 4
```

Maknanya:

```text
LOSS_BURST aktif jika terdapat minimal 4 ping failure dalam 20 sampel terakhir,
atau sekitar 20% packet loss dalam window 40 detik.
```

Jika penelitian ingin lebih konservatif terhadap false alarm, nilai `m_ping = 5` dapat digunakan. Namun, `m_ping = 5` akan membuat event lebih lambat atau lebih sulit aktif, terutama jika injected loss rate tidak terlalu tinggi.

---

## 8. State Transition untuk S6 `CONNECTIVITY_FLAP`

S6 `CONNECTIVITY_FLAP` berbeda dari S2 dan S3 karena event yang dihitung bukan failure count biasa, melainkan perubahan state konektivitas.

Definisikan state:

```text
connectivity_ok = wifi_up == true AND ping.success == true
```

Nilai `connectivity_ok` hanya memiliki dua kemungkinan:

```text
true  = konektivitas tersedia
false = konektivitas tidak tersedia
```

`state_transition_count` adalah jumlah perubahan state dalam window.

Contoh:

```text
true -> false = 1 transition
false -> true = 1 transition
```

Contoh sequence:

```text
true, true, false, false, true, true
```

Transition count:

```text
true -> true   = 0
true -> false  = 1
false -> false = 0
false -> true  = 1
true -> true   = 0

state_transition_count = 2
```

Makna:

```text
state_transition_count = 2
```

berarti terdapat satu siklus putus-pulih:

```text
true -> false -> true
```

Contoh lain:

```text
true, false, true, false, true
```

Transition count:

```text
true -> false = 1
false -> true = 1
true -> false = 1
false -> true = 1

state_transition_count = 4
```

Makna:

```text
state_transition_count = 4
```

berarti terdapat dua siklus putus-pulih.

Karena `CONNECTIVITY_FLAP` didefinisikan sebagai konektivitas yang berubah berulang, maka state transition lebih tepat dibanding sekadar menghitung ping failure.

---

## 9. Perhitungan untuk S6 `CONNECTIVITY_FLAP`

Konfigurasi awal:

```text
fast_interval = 2 detik
W_flap = 30 detik
n_flap = 15 sampel
```

Jika terdapat 15 sampel state, maka jumlah pasangan state berurutan yang dapat menghasilkan transition adalah:

```text
transition_pairs = n_flap - 1
transition_pairs = 15 - 1
transition_pairs = 14
```

Asumsi:

```text
q = 0.01
```

Artinya, pada kondisi normal diasumsikan peluang terjadi satu transisi state antar dua sampel berurutan adalah 1%.

Jika:

```text
Y_transition ~ Binomial(14, 0.01)
```

maka peluang false alarm untuk beberapa kandidat `m_transition` adalah:

|            Rule | Makna                                 | `P_FA = P(Y >= m)` | Approx FAR per jam |
| --------------: | ------------------------------------- | -----------------: | -----------------: |
|  `1 transition` | satu perubahan state                  |            `0,131` |        `236,3/jam` |
| `2 transitions` | satu siklus putus-pulih               |          `0,00840` |        `15,12/jam` |
| `3 transitions` | lebih dari satu perubahan bolak-balik |         `0,000335` |        `0,603/jam` |
| `4 transitions` | dua siklus putus-pulih                |       `0,00000924` |       `0,0166/jam` |

Interpretasi:

```text
1 transition belum cukup disebut CONNECTIVITY_FLAP karena hanya menunjukkan awal outage.

2 transitions menunjukkan satu siklus putus-pulih, yaitu true -> false -> true.

3 transitions menunjukkan konektivitas berubah lebih dari satu kali, tetapi belum kembali penuh ke pola dua siklus.

4 transitions menunjukkan dua siklus putus-pulih, sehingga lebih kuat untuk mendefinisikan flap yang berulang.
```

Berdasarkan makna event `CONNECTIVITY_FLAP`, konfigurasi yang lebih ketat dan lebih sesuai secara semantik adalah:

```text
W_flap = 30 detik
m_transition = 4
```

Maknanya:

```text
CONNECTIVITY_FLAP aktif jika terdapat minimal 4 transisi state konektivitas dalam window 30 detik.
```

Dengan kata lain, event aktif jika perangkat mengalami minimal dua siklus putus-pulih dalam window tersebut.

Jika penelitian ingin mendeteksi satu siklus putus-pulih sebagai flap, maka dapat digunakan:

```text
m_transition = 2
```

Namun, nilai tersebut harus dijelaskan sebagai definisi flap minimal, bukan flap berulang yang ketat.

---

## 10. Estimasi Mean Time to Detect untuk `m-of-n Rule`

Penggunaan `m-of-n rule` menambah waktu deteksi karena detector harus menunggu sampai jumlah kejadian abnormal mencapai `m`.

Jika fault menyebabkan setiap sampel menjadi abnormal, maka Mean Time to Detect dapat didekati sebagai:

```text
MTTD_m ≈ (interval_sampling / 2) + ((m - 1) × interval_sampling)
```

Dengan:

```text
interval_sampling = 2 detik
```

maka:

| `m` | MTTD rata-rata jika semua sampel abnormal | Worst-case detection time |
| --: | ----------------------------------------: | ------------------------: |
|   1 |                                   1 detik |                   2 detik |
|   2 |                                   3 detik |                   4 detik |
|   3 |                                   5 detik |                   6 detik |
|   4 |                                   7 detik |                   8 detik |
|   5 |                                   9 detik |                  10 detik |

Namun, untuk event seperti packet loss, fault tidak selalu membuat semua sampel gagal. Jika fault bersifat probabilistik, maka jumlah sampel yang dibutuhkan untuk memperoleh `m` failure dapat didekati dengan:

```text
required_samples ≈ m / p_fault
```

dengan:

```text
p_fault = probabilitas sampel menjadi abnormal saat fault injection aktif
```

Mean Time to Detect dapat didekati sebagai:

```text
MTTD_m ≈ (interval_sampling / 2) + ((required_samples - 1) × interval_sampling)
```

Contoh untuk S3 `LOSS_BURST`:

```text
m_ping = 4
p_fault = 0.20
interval_sampling = 2 detik
```

Maka:

```text
required_samples ≈ 4 / 0.20
required_samples ≈ 20 sampel
```

Sehingga:

```text
MTTD_m ≈ 1 + ((20 - 1) × 2)
MTTD_m ≈ 39 detik
```

Artinya, jika loss yang diinjeksi adalah 20%, maka rule `4-of-20` akan membutuhkan sekitar 40 detik secara ekspektasi untuk memperoleh 4 ping failure.

---

## 11. Trade-off FAR dan MTTD

Gabungan trade-off `m-of-n rule` dapat dirangkum sebagai berikut.

Untuk DNS dengan:

```text
n_dns = 10
p_dns = 0.01
fast_interval = 2 detik
```

|      Rule | Approx FAR per jam | Deteksi jika semua sampel fail |
| --------: | -----------------: | -----------------------------: |
| `1-of-10` |        `172,1/jam` |                   sangat cepat |
| `2-of-10` |         `7,68/jam` |                          cepat |
| `3-of-10` |        `0,205/jam` |                         sedang |
| `4-of-10` |       `0,0036/jam` |       lebih lambat/lebih ketat |

Untuk packet loss dengan:

```text
n_ping = 20
p_ping = 0.01
fast_interval = 2 detik
```

|      Rule | Approx FAR per jam | Makna loss ratio |
| --------: | -----------------: | ---------------: |
| `1-of-20` |        `327,8/jam` |          5% loss |
| `2-of-20` |        `30,35/jam` |         10% loss |
| `3-of-20` |         `1,81/jam` |         15% loss |
| `4-of-20` |       `0,0767/jam` |         20% loss |
| `5-of-20` |      `0,00246/jam` |         25% loss |

Untuk connectivity flap dengan:

```text
W_flap = 30 detik
n_flap = 15
transition_pairs = 14
q = 0.01
```

|            Rule | Approx FAR per jam | Makna                                          |
| --------------: | -----------------: | ---------------------------------------------- |
|  `1 transition` |        `236,3/jam` | satu perubahan state, belum cukup disebut flap |
| `2 transitions` |        `15,12/jam` | satu siklus putus-pulih                        |
| `3 transitions` |        `0,603/jam` | beberapa perubahan state                       |
| `4 transitions` |       `0,0166/jam` | dua siklus putus-pulih                         |

Dari tabel tersebut:

```text
m kecil memberikan deteksi cepat tetapi false alarm tinggi.
m besar menurunkan false alarm tetapi membutuhkan gangguan yang lebih kuat atau lebih lama.
```

---

## 12. Fungsi Objektif Sederhana

Untuk memformalkan trade-off, pemilihan parameter `m` dan `n` dapat dinyatakan menggunakan fungsi objektif:

```text
J(m,n) = C_FA × FAR(m,n) + C_D × MTTD(m,n)
```

dengan:

```text
J(m,n)   = total cost untuk kombinasi m dan n
C_FA     = bobot biaya false alarm
FAR(m,n) = false alarm rate untuk kombinasi m dan n
C_D      = bobot biaya detection delay
MTTD(m,n)= mean time to detect untuk kombinasi m dan n
```

Kombinasi parameter yang dipilih adalah:

```text
(m*, n*) = argmin J(m,n)
```

Karena penelitian ini tidak melakukan optimasi biaya secara eksplisit, pemilihan `m` dan `n` dilakukan berdasarkan trade-off numerik antara estimasi FAR dan MTTD, serta makna semantik dari setiap event.

---

## 13. Pemilihan Nilai `m-of-n Rule`

Berdasarkan perhitungan sebelumnya, konfigurasi awal yang digunakan adalah:

```text
S2 DNS_TIMEOUT_BURST:
  n_dns = 10
  m_dns = 3
  window = 20 detik
  makna = minimal 3 DNS failure dalam 10 sampel terakhir

S3 LOSS_BURST:
  n_ping = 20
  m_ping = 4
  window = 40 detik
  makna = minimal 4 ping failure dalam 20 sampel terakhir,
          atau sekitar 20% packet loss

S6 CONNECTIVITY_FLAP:
  W_flap = 30 detik
  n_flap = 15
  m_transition = 4
  makna = minimal 4 transisi state,
          atau sekitar dua siklus putus-pulih dalam 30 detik
```

Alasan pemilihan:

```text
S2:
  1 atau 2 DNS failure belum cukup kuat untuk disebut burst.
  3 DNS failure dalam 20 detik sudah menunjukkan pola DNS failure berulang.

S3:
  Packet loss perlu direpresentasikan sebagai rasio.
  Dengan n_ping = 20, resolusi loss adalah 5%.
  m_ping = 4 berarti sekitar 20% loss, cukup kuat untuk disebut LOSS_BURST.

S6:
  Satu transisi hanya berarti koneksi mulai down.
  Dua transisi berarti satu siklus putus-pulih.
  Empat transisi menunjukkan dua siklus putus-pulih, sehingga lebih sesuai dengan makna flap yang berulang.
```

Nilai tersebut tidak diklaim sebagai nilai optimal universal, tetapi sebagai konfigurasi desain awal yang diperoleh dari perhitungan trade-off antara false alarm rate dan mean time to detect, dengan asumsi fast probe berjalan setiap 2 detik.

---

## 14. Keterbatasan Perhitungan

Perhitungan ini menggunakan beberapa asumsi:

```text
1. Fast probe berjalan setiap 2 detik.
2. Peluang abnormal pada kondisi normal diasumsikan p = 0.01.
3. Untuk S6, peluang transition pada kondisi normal diasumsikan q = 0.01.
4. Sampel dianggap relatif independen.
5. Estimasi FAR per jam dihitung dari evaluasi window yang disederhanakan.
6. Sliding window yang overlap dapat membuat estimasi FAR aktual berbeda dari perhitungan teoretis.
7. Untuk packet loss, MTTD bergantung pada injected loss rate.
8. Untuk connectivity flap, MTTD bergantung pada durasi down/up dan jumlah siklus flap.
```

Pada kondisi jaringan nyata, sampel dapat memiliki autokorelasi. DNS failure, ping failure, dan connectivity transition juga dapat saling bergantung. Karena itu, hasil perhitungan ini digunakan sebagai dasar desain parameter, bukan sebagai klaim performa absolut.

---

## 15. Kesimpulan

`m-of-n rule` digunakan untuk event yang berbasis kejadian diskrit dalam sliding window. Berbeda dari `confirm_consecutive` yang mensyaratkan kondisi abnormal terjadi berturut-turut, `m-of-n rule` hanya mensyaratkan jumlah kejadian abnormal mencapai batas minimum dalam window.

Pada penelitian ini, `m-of-n rule` digunakan untuk:

```text
S2 DNS_TIMEOUT_BURST:
  menghitung jumlah DNS failure dalam window

S3 LOSS_BURST:
  menghitung jumlah ping failure atau packet loss dalam window

S6 CONNECTIVITY_FLAP:
  menghitung jumlah transisi state connectivity_ok dalam window
```

Dengan fast interval 2 detik, konfigurasi desain awal yang digunakan adalah:

```text
S2: 3-of-10 DNS failure dalam 20 detik
S3: 4-of-20 ping failure dalam 40 detik
S6: 4 transition dalam 30 detik
```

Konfigurasi tersebut dipilih sebagai kompromi antara penurunan false alarm dan kebutuhan deteksi cepat pada Micro-UXI.
