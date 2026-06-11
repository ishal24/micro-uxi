# Penentuan `confirm_consecutive`

## 1. Definisi

`confirm_consecutive` adalah jumlah sampel berturut-turut yang harus memenuhi kondisi abnormal sebelum suatu event dinyatakan aktif.

Secara umum:

```text
event_active = true jika metric >= threshold selama N sampel berturut-turut
```

dengan:

```text
N = confirm_consecutive
```

Pada penelitian ini, `confirm_consecutive` digunakan untuk event berbasis threshold numerik yang dievaluasi per sampel, yaitu:

```text
S1 DNS_DEGRADED
S4 HIGH_RTT
S5 HTTP_SLOW
```

Event tersebut memiliki karakteristik berupa peningkatan nilai metrik yang harus bertahan dalam beberapa pengamatan, bukan hanya terjadi sebagai spike sesaat.

---

## 2. Tujuan Penggunaan `confirm_consecutive`

Penggunaan `confirm_consecutive` bertujuan untuk membedakan antara:

```text
1. Spike sesaat pada kondisi normal
2. Degradasi yang benar-benar persisten
```

Contoh pada metrik RTT:

```text
Normal dengan spike sesaat:
25 ms, 27 ms, 240 ms, 29 ms, 26 ms
```

Jika satu sampel abnormal langsung dianggap event, maka nilai `240 ms` dapat menyebabkan false alarm.

Sebaliknya:

```text
Kondisi abnormal persisten:
25 ms, 27 ms, 240 ms, 260 ms, 250 ms
```

Pada kondisi ini, nilai RTT yang tinggi muncul lebih dari satu kali secara berturut-turut, sehingga lebih kuat untuk diklasifikasikan sebagai `HIGH_RTT`.

Oleh karena itu, `confirm_consecutive` digunakan sebagai mekanisme konfirmasi temporal sebelum event dinyatakan aktif.

---

## 3. Dasar Teoretis

Pemilihan `confirm_consecutive` didasarkan pada prinsip trade-off antara **false alarm rate** dan **mean time to detect**.

Dalam anomaly-based detection, konfigurasi detector yang terlalu sensitif dapat menghasilkan deteksi cepat, tetapi meningkatkan false alarm. Sebaliknya, konfigurasi yang terlalu konservatif dapat menurunkan false alarm, tetapi meningkatkan waktu deteksi.

Prinsip ini sejalan dengan Ghafouri et al. (2016), yang menyatakan bahwa pengaturan detector perlu mempertimbangkan trade-off antara false positive rate dan detection delay. Pada penelitian ini, prinsip tersebut diadaptasi untuk menentukan nilai `confirm_consecutive`.

---

## 4. Asumsi Perhitungan

Pada penelitian ini, threshold metrik ditentukan menggunakan P99 dari data preliminary test.

Jika threshold menggunakan P99, maka secara teoritis peluang satu sampel normal melewati threshold adalah:

```text
p = 1 - 0.99
p = 0.01
```

Artinya, meskipun kondisi jaringan normal, sekitar 1% sampel masih mungkin melewati threshold karena variasi alami, jitter, atau noise pengukuran.

Asumsi perhitungan:

```text
threshold = P99
p = 0.01
interval_sampling = 5 detik
N = confirm_consecutive
```

Dengan `confirm_consecutive = N`, event hanya aktif jika terdapat `N` sampel berturut-turut yang melewati threshold.

---

## 5. Estimasi False Alarm Rate

Peluang munculnya `N` sampel abnormal berturut-turut pada kondisi normal dapat didekati sebagai:

```text
P_false_run ≈ p^N
```

dengan:

```text
p = peluang satu sampel normal melewati threshold
N = jumlah sampel berturut-turut yang diperlukan
```

Karena threshold menggunakan P99:

```text
p = 0.01
```

Maka:

| `N` | Perhitungan | Estimasi peluang false trigger |
| --: | ----------: | -----------------------------: |
|   1 |    `0.01^1` |                         `0.01` |
|   2 |    `0.01^2` |                       `0.0001` |
|   3 |    `0.01^3` |                     `0.000001` |
|   4 |    `0.01^4` |                   `0.00000001` |

Dari tabel tersebut, terlihat bahwa peningkatan nilai `N` menurunkan peluang false trigger secara eksponensial.

---

## 6. Average Run Length sampai False Alarm

Selain menggunakan pendekatan `p^N`, estimasi waktu rata-rata sampai false alarm dapat dihitung menggunakan Average Run Length untuk run sebanyak `N` kejadian berturut-turut.

Rumus:

```text
ARL_N = (1 - p^N) / ((1 - p) × p^N)
```

dengan:

```text
ARL_N = rata-rata jumlah sampel sampai muncul N abnormal berturut-turut
p     = peluang satu sampel normal melewati threshold
N     = confirm_consecutive
```

Karena interval sampling adalah 5 detik, maka:

```text
samples_per_hour = 3600 / 5
samples_per_hour = 720 sampel/jam
```

False alarm rate per jam dapat dihitung dengan:

```text
FAR_N = samples_per_hour / ARL_N
```

Hasil perhitungan:

| `N` |            `ARL_N` |    Average time to false alarm |                FAR per jam |
| --: | -----------------: | -----------------------------: | -------------------------: |
|   1 |         100 sampel |          500 detik ≈ 8,3 menit |        7,2 false alarm/jam |
|   2 |      10.100 sampel |        50.500 detik ≈ 14,0 jam |      0,071 false alarm/jam |
|   3 |   1.010.100 sampel |    5.050.500 detik ≈ 58,5 hari |   0,000713 false alarm/jam |
|   4 | 101.010.100 sampel | 505.050.500 detik ≈ 16,0 tahun | 0,00000713 false alarm/jam |

Interpretasi:

```text
N = 1 terlalu sensitif karena estimasi false alarm mencapai 7,2 kali per jam.
N = 2 menurunkan false alarm secara signifikan menjadi sekitar satu false alarm setiap 14 jam.
N = 3 menurunkan false alarm lebih jauh menjadi sekitar satu false alarm setiap 58,5 hari.
N = 4 memberikan false alarm yang sangat rendah, tetapi menjadi terlalu konservatif untuk sistem monitoring ringan.
```

---

## 7. Estimasi Mean Time to Detect

Penggunaan `confirm_consecutive` menambah waktu deteksi karena detector harus menunggu beberapa sampel abnormal berturut-turut.

Dengan interval sampling:

```text
interval_sampling = 5 detik
```

Tambahan detection delay dibanding single-sample trigger adalah:

```text
extra_delay = (N - 1) × interval_sampling
```

Maka:

| `N` |   Perhitungan | Extra detection delay |
| --: | ------------: | --------------------: |
|   1 | `(1 - 1) × 5` |               0 detik |
|   2 | `(2 - 1) × 5` |               5 detik |
|   3 | `(3 - 1) × 5` |              10 detik |
|   4 | `(4 - 1) × 5` |              15 detik |

Jika gangguan dapat mulai kapan saja di antara dua sampel, maka rata-rata waktu tunggu sampai sampel pertama adalah setengah interval sampling:

```text
average_wait_to_first_sample = 5 / 2
average_wait_to_first_sample = 2,5 detik
```

Sehingga Mean Time to Detect dapat didekati sebagai:

```text
MTTD_N ≈ 2,5 + ((N - 1) × 5)
```

Hasilnya:

| `N` | MTTD rata-rata |
| --: | -------------: |
|   1 |      2,5 detik |
|   2 |      7,5 detik |
|   3 |     12,5 detik |
|   4 |     17,5 detik |

Sedangkan worst-case detection time dapat didekati sebagai:

```text
MTTD_worst = N × interval_sampling
```

| `N` | Worst-case detection time |
| --: | ------------------------: |
|   1 |                   5 detik |
|   2 |                  10 detik |
|   3 |                  15 detik |
|   4 |                  20 detik |

---

## 8. Trade-off FAR dan MTTD

Gabungan antara estimasi false alarm rate dan mean time to detect adalah sebagai berikut:

| `N` |    FAR per jam | Average time to false alarm | MTTD rata-rata | Extra detection delay |
| --: | -------------: | --------------------------: | -------------: | --------------------: |
|   1 |        7,2/jam |                   8,3 menit |      2,5 detik |               0 detik |
|   2 |      0,071/jam |                    14,0 jam |      7,5 detik |               5 detik |
|   3 |   0,000713/jam |                   58,5 hari |     12,5 detik |              10 detik |
|   4 | 0,00000713/jam |                  16,0 tahun |     17,5 detik |              15 detik |

Dari tabel tersebut:

```text
N = 1 memberikan MTTD paling cepat, tetapi FAR terlalu tinggi.
N = 2 memberikan penurunan FAR yang besar dibanding N = 1, dengan tambahan delay hanya 5 detik.
N = 3 memberikan FAR yang jauh lebih rendah dibanding N = 2, tetapi menambah delay lagi sebesar 5 detik.
N = 4 memberikan FAR yang sangat rendah, tetapi manfaat tambahannya kecil dibanding peningkatan delay.
```

---

## 9. Fungsi Objektif Sederhana

Untuk memformalkan trade-off, pemilihan `N` dapat dinyatakan menggunakan fungsi objektif:

```text
J(N) = C_FA × FAR_N + C_D × MTTD_N
```

dengan:

```text
J(N)   = total cost untuk nilai N
C_FA   = bobot biaya false alarm
FAR_N  = false alarm rate untuk nilai N
C_D    = bobot biaya detection delay
MTTD_N = mean time to detect untuk nilai N
```

Nilai `N` yang dipilih adalah nilai yang meminimalkan `J(N)`:

```text
N* = argmin J(N)
```

Karena penelitian ini tidak melakukan optimasi biaya secara eksplisit, pemilihan `N` dilakukan berdasarkan trade-off numerik antara estimasi FAR dan MTTD.

---

## 10. Pemilihan Nilai `confirm_consecutive`

Berdasarkan perhitungan sebelumnya:

```text
N = 1:
  FAR terlalu tinggi, yaitu sekitar 7,2 false alarm per jam.

N = 2:
  FAR turun menjadi sekitar 0,071 false alarm per jam,
  atau sekitar satu false alarm setiap 14 jam.
  Tambahan detection delay hanya 5 detik.

N = 3:
  FAR turun menjadi sekitar 0,000713 false alarm per jam,
  atau sekitar satu false alarm setiap 58,5 hari.
  Namun tambahan detection delay menjadi 10 detik.

N = 4:
  FAR sangat rendah, tetapi terlalu konservatif untuk monitoring ringan.
```

Dengan mempertimbangkan bahwa Micro-UXI ditujukan untuk monitoring gangguan jaringan secara ringan dan relatif cepat, nilai:

```text
confirm_consecutive = 2
```

dipilih sebagai kompromi antara penurunan false alarm dan kebutuhan deteksi cepat.

Nilai ini tidak diklaim sebagai nilai optimal universal, tetapi sebagai konfigurasi desain yang diperoleh dari perhitungan trade-off antara false alarm rate dan mean time to detect dengan asumsi threshold P99 dan interval sampling 5 detik.

---

## 11. Keterbatasan Perhitungan

Perhitungan ini menggunakan beberapa asumsi:

```text
1. Threshold menggunakan P99, sehingga p ≈ 0,01.
2. Sampel dianggap relatif independen.
3. Gangguan yang benar-benar terjadi diasumsikan membuat metrik melewati threshold secara konsisten.
4. Interval sampling adalah 5 detik.
```

Pada kondisi jaringan nyata, sampel dapat memiliki autokorelasi. Jika sampel saling berkorelasi, false alarm aktual dapat berbeda dari estimasi teoretis. Oleh karena itu, hasil ini digunakan sebagai dasar desain parameter, bukan sebagai klaim performa absolut.

---

## 12. Kesimpulan

`confirm_consecutive` digunakan untuk mencegah event aktif akibat single-sample spike pada kondisi normal. Dengan threshold P99, peluang satu sampel normal melewati threshold adalah sekitar 1%. Jika `confirm_consecutive = N`, peluang false trigger akibat `N` sampel abnormal berturut-turut menurun secara eksponensial, yaitu mendekati `p^N`.

Dengan interval sampling 5 detik, `N = 2` menurunkan estimasi false alarm dari 7,2 false alarm per jam menjadi sekitar 0,071 false alarm per jam, dengan tambahan detection delay sebesar 5 detik. Oleh karena itu, `confirm_consecutive = 2` dipilih sebagai konfigurasi desain untuk event berbasis threshold numerik pada Micro-UXI.
