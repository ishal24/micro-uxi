# Event Catalog

Dokumen ini mendefinisikan event Micro-UXI secara operasional. Fokus dokumen ini adalah **kapan suatu kondisi dianggap event**, **sinyal apa yang dipakai**, dan **bagaimana event dibedakan dari noise**.

## Event Classification Principles

- Tidak semua deviasi sesaat adalah event.
- Suatu kondisi hanya dinyatakan sebagai event bila memenuhi **significance**, **persistence**, dan/atau **state-change relevance**.
- Detector sebaiknya membedakan tiga level:
  - **noise / normal variation**
  - **transient anomaly**
  - **confirmed event**
- Untuk metrik numerik, event idealnya memakai:
  - adaptive baseline (`rolling median`, `EWMA`, `MAD`) dan/atau threshold absolut
  - persistence rule (`N consecutive samples` atau `M of last N samples`)
  - recovery rule
  - debounce / merge rule
- Untuk metrik state, event idealnya memakai:
  - state-change logic
  - minimum duration
  - recovery stability rule

## Event Summary Table

| Event Name | Severity Class | Description | Primary Signals | Trigger Summary | Recovery Summary | Related Fault Injection Scenario |
|---|---|---|---|---|---|---|
| `DNS_DEGRADED` | Minor / Major | Resolusi DNS melambat signifikan tetapi belum gagal total | `dns_latency_ms`, optional `dns_success_rate` | DNS latency melewati adaptive threshold secara persisten | DNS latency kembali ke rentang normal selama beberapa sampel | `DNS Delay` |
| `DNS_TIMEOUT_BURST` | Major / Critical | Terjadi timeout DNS berulang dalam window pendek | `dns_timeout` | Minimal beberapa timeout dalam burst window | Tidak ada timeout lagi selama quiet period | `DNS Outage Burst` |
| `LOSS_BURST` | Minor / Major | Terjadi lonjakan packet loss pada interval pendek | `packet_loss_pct`, optional `consecutive_ping_failures` | Packet loss tinggi secara persisten dalam rolling window | Packet loss turun ke level normal selama beberapa sampel | `Packet Loss Burst` |
| `HIGH_RTT` | Minor / Major | RTT meningkat signifikan dibanding baseline lokal | `rtt_ms`, optional `baseline_rtt_ms`, `mad_rtt_ms` | RTT melewati adaptive threshold selama N sampel | RTT kembali dekat baseline selama K sampel | `RTT Increase` |
| `HTTP_SLOW` | Minor / Major | Respons HTTP / aplikasi melambat atau timeout | `http_connect_ms`, optional `http_total_ms`, `http_timeout` | HTTP timing tinggi secara persisten atau timeout berulang | HTTP timing kembali normal dan timeout berhenti | `Bandwidth Throttling`, service degradation |
| `CONNECTIVITY_FLAP` | Major / Critical | Konektivitas berubah putus–nyambung secara berulang atau terputus cukup lama | `wifi_link_state`, optional `wifi_disconnect_count` | Beberapa transisi state dalam window pendek, atau disconnect bertahan melewati minimum duration | Link stabil kembali selama recovery window | `Connectivity Flap` |

## Noise vs Transient Anomaly vs Confirmed Event

### Noise / Normal Variation
Deviasi kecil, sporadis, atau artefaktual yang tidak signifikan secara operasional.

Contoh:
- satu spike RTT tunggal
- satu timeout DNS tunggal tanpa pengulangan
- satu request HTTP yang sedikit lebih lambat
- satu paket hilang sporadis di jaringan Wi-Fi

### Transient Anomaly
Deviasi yang nyata tetapi belum cukup kuat untuk disebut event.

Contoh:
- DNS delay singkat yang hanya muncul sekali
- packet loss kecil dalam satu window
- disconnect sangat singkat yang tidak persisten

### Confirmed Event
Gangguan yang cukup signifikan, cukup persisten, atau cukup jelas secara state sehingga relevan secara operasional dan layak direkam sebagai evidence bundle lengkap.

## Detailed Event Definitions

---

## `DNS_DEGRADED`

**Description**  
Resolusi DNS melambat signifikan dibanding kondisi normal, tetapi belum mengalami outage total.

**Operational Meaning**  
Pengguna masih dapat melakukan resolve domain, namun waktu respon meningkat dan berpotensi menurunkan respons aplikasi yang bergantung pada DNS.

**Primary Signals**
- `dns_latency_ms`
- optional: `dns_success_rate`
- optional: `baseline_dns_ms`, `mad_dns_ms`

**Trigger Logic**
- Adaptive rule:
  - `dns_latency_ms > baseline_dns_ms + k * mad_dns_ms`
- Optional absolute guard:
  - `dns_latency_ms > max(T_abs_dns, baseline_dns_ms + k * mad_dns_ms)`
- Persistence rule:
  - `3 of last 5 samples`, atau aturan lain yang dikunci di konfigurasi

**Recommended Default Parameters**
- baseline window: 30–60 s
- `k = 3`
- persistence: `3 of last 5 samples`

**Recovery Logic**
- `dns_latency_ms <= baseline_dns_ms + k_recovery * mad_dns_ms`
- selama `K` sampel berturut-turut

**Recommended Recovery Parameters**
- `k_recovery = 1.5`
- `K = 5 samples`

**Not Considered an Event**
- satu spike DNS latency tunggal
- delay DNS singkat tanpa pengulangan
- outlier yang tidak memenuhi persistence rule

**Related Fault Injection**
- `DNS Delay`

**Expected Evidence Bundle**
- pre-event window
- event window
- post-event window
- network snapshot
- DNS context / resolver info

**Ground Truth Matching Rule**
- dipasangkan dengan fault `DNS Delay`
- `event_start_ts` berada dalam jendela toleransi terhadap `fault_start_ts` dan `fault_end_ts`

**Notes**
- Jangan hanya pakai threshold absolut jika kondisi baseline DNS di lingkungan uji berubah-ubah.

---

## `DNS_TIMEOUT_BURST`

**Description**  
Terjadi beberapa timeout DNS dalam interval pendek yang menunjukkan outage parsial atau burst failure.

**Operational Meaning**  
Aplikasi dapat gagal resolve domain secara sporadis atau beruntun, yang lebih berat daripada sekadar DNS lambat.

**Primary Signals**
- `dns_timeout`
- optional: `dns_success_rate`
- optional: `dns_latency_ms`

**Trigger Logic**
- Burst rule:
  - `count(dns_timeout = true) >= B` dalam `burst_window`
- Alternatif:
  - timeout pada `N` sampel berturut-turut

**Recommended Default Parameters**
- `B = 2`
- `burst_window = 10 s`

**Recovery Logic**
- tidak ada timeout DNS lagi selama `quiet_period`
- dan, bila dipakai, `dns_latency_ms` kembali normal

**Recommended Recovery Parameters**
- `quiet_period = 10 s`

**Not Considered an Event**
- satu timeout DNS tunggal
- failure sekali yang langsung normal tanpa pengulangan

**Related Fault Injection**
- `DNS Outage Burst`

**Expected Evidence Bundle**
- pre-event window
- event window
- post-event window
- network snapshot
- DNS resolver snapshot

**Ground Truth Matching Rule**
- dipasangkan dengan fault `DNS Outage Burst`
- gunakan first-match atau best-match sesuai kebijakan evaluasi

**Notes**
- Ini salah satu event terbaik untuk membedakan event-driven dari baseline periodik statis.

---

## `LOSS_BURST`

**Description**  
Packet loss melonjak pada interval pendek dan cukup persisten untuk menunjukkan gangguan konektivitas parsial.

**Operational Meaning**  
Kualitas konektivitas menurun, yang dapat memengaruhi respons jaringan dan kestabilan aplikasi.

**Primary Signals**
- `packet_loss_pct`
- optional: `consecutive_ping_failures`

**Trigger Logic**
- `packet_loss_pct > max(T_abs_loss, baseline_loss + k * mad_loss)`
- dengan persistence rule, misalnya `3 of last 5 samples`
- atau loss batch tinggi pada beberapa window berturut-turut

**Recommended Default Parameters**
- `T_abs_loss = 10%` atau sesuai testbed
- `k = 3`
- persistence: `3 of last 5 samples`

**Recovery Logic**
- packet loss kembali di bawah threshold recovery
- selama `K` sampel berturut-turut

**Recommended Recovery Parameters**
- `K = 5 samples`

**Not Considered an Event**
- satu paket hilang tunggal
- loss sporadis kecil yang masih wajar di Wi-Fi

**Related Fault Injection**
- `Packet Loss Burst`

**Expected Evidence Bundle**
- pre-event window
- event window
- post-event window
- ping statistics snapshot
- network snapshot

**Ground Truth Matching Rule**
- dipasangkan dengan fault `Packet Loss Burst`

**Notes**
- Definisikan batch/window loss secara eksplisit di implementasi agar hasil konsisten.

---

## `HIGH_RTT`

**Description**  
RTT meningkat signifikan dibanding kondisi normal dalam durasi yang cukup untuk dianggap relevan secara operasional.

**Operational Meaning**  
Respons jaringan terasa lebih lambat dan dapat menurunkan kualitas pengalaman pengguna.

**Primary Signals**
- `rtt_ms`
- `baseline_rtt_ms`
- `mad_rtt_ms`

**Trigger Logic**
- `rtt_ms > max(T_abs_rtt, baseline_rtt_ms + k * mad_rtt_ms)`
- selama `N` sampel berturut-turut

**Recommended Default Parameters**
- `k = 3`
- `N = 3`
- `T_abs_rtt` disesuaikan dengan lingkungan uji

**Recovery Logic**
- `rtt_ms <= baseline_rtt_ms + k_recovery * mad_rtt_ms`
- selama `K` sampel berturut-turut

**Recommended Recovery Parameters**
- `k_recovery = 1.5`
- `K = 5`

**Not Considered an Event**
- satu spike RTT tunggal
- jitter kecil yang masih dalam variasi normal

**Related Fault Injection**
- `RTT Increase`

**Expected Evidence Bundle**
- pre-event window
- event window
- post-event window
- ping statistics snapshot

**Ground Truth Matching Rule**
- dipasangkan dengan fault `RTT Increase`

**Notes**
- Cocok sebagai event awal untuk implementasi dan verifikasi detector.

---

## `HTTP_SLOW`

**Description**  
Transaksi HTTP / aplikasi menjadi lambat atau mengalami timeout, meskipun link atau DNS belum tentu gagal total.

**Operational Meaning**  
Lebih dekat ke pengalaman pengguna aplikasi karena mengukur lapisan layanan, bukan hanya jaringan dasar.

**Primary Signals**
- `http_connect_ms`
- optional: `http_total_ms`
- optional: `http_timeout`
- optional: `http_status_code`

**Trigger Logic**
- `http_metric > max(T_abs_http, baseline_http_ms + k * mad_http_ms)`
- secara persisten (`3 of last 5 samples`), atau
- timeout HTTP berulang dalam window pendek

**Recommended Default Parameters**
- `k = 3`
- persistence: `3 of last 5 samples`
- timeout burst window: 10–30 s

**Recovery Logic**
- metrik HTTP kembali normal
- dan tidak ada timeout lagi selama quiet period

**Recommended Recovery Parameters**
- `quiet_period = 10–20 s`

**Not Considered an Event**
- satu request HTTP lambat tunggal
- outlier sesaat tanpa pengulangan
- delay yang diketahui berasal dari endpoint eksternal yang tidak stabil, bila testbed tidak terkontrol

**Related Fault Injection**
- `Bandwidth Throttling`
- service degradation scenario

**Expected Evidence Bundle**
- pre-event window
- event window
- post-event window
- HTTP timing summary
- network snapshot

**Ground Truth Matching Rule**
- dipasangkan dengan fault yang berdampak ke metrik HTTP

**Notes**
- Akan lebih kuat bila implementasi memiliki `http_total_ms` atau `transfer_duration`, bukan hanya `http_connect_ms`.

---

## `CONNECTIVITY_FLAP`

**Description**  
Konektivitas probe berubah putus–nyambung berulang dalam interval pendek, atau terjadi putus koneksi yang bertahan melewati ambang minimum.

**Operational Meaning**  
Ini adalah gangguan keras yang langsung memengaruhi availability konektivitas probe.

**Primary Signals**
- `wifi_link_state`
- optional: `wifi_disconnect_count`
- optional: `ip_address` / DHCP state

**Trigger Logic**
- jumlah transisi state `>= F` dalam `flap_window`, atau
- satu transisi `connected -> disconnected` yang bertahan lebih dari `disconnect_min_duration`

**Recommended Default Parameters**
- `F = 2`
- `flap_window = 30 s`
- `disconnect_min_duration = 3–5 s`

**Recovery Logic**
- status `connected` stabil selama `recovery_window`

**Recommended Recovery Parameters**
- `recovery_window = 10–20 s`

**Not Considered an Event**
- glitch pembacaan state yang sangat singkat
- disconnect sangat singkat yang telah diketahui sebagai artefak sampling dan tidak memenuhi minimum duration

**Related Fault Injection**
- `Connectivity Flap`

**Expected Evidence Bundle**
- pre-event window
- event window
- post-event window
- Wi-Fi snapshot
- network snapshot

**Ground Truth Matching Rule**
- dipasangkan dengan fault `Connectivity Flap`

**Notes**
- Event ini lebih cocok memakai state-change logic daripada threshold numerik biasa.

## Merge / Debounce Rule

Agar satu gangguan tidak terpecah menjadi banyak event:
- dua trigger sejenis yang terjadi dengan jarak kurang dari `merge_gap` dapat digabung menjadi satu event
- contoh awal: `merge_gap = 10 s`

## Handling Noise and Unexpected Real-World Events During Testing

### Noisy Non-Event Runs
Selain run event utama, sebaiknya ada run dengan gangguan kecil yang sengaja dibuat tetapi **tidak memenuhi definisi event**. Tujuannya untuk menguji apakah detector mampu menahan false positive.

### Unexpected Real-World Events
Jika selama run muncul gangguan nyata di luar skenario scripted fault:
- tandai run sebagai `contaminated` atau `confounded`
- jangan otomatis menganggapnya sebagai ground truth utama
- idealnya run diulang untuk evaluasi utama precision / recall / F1 / MTTD
- event tetap boleh direkam oleh sistem, tetapi dianalisis terpisah dari scripted experiment

## Recommended Evaluation Mapping

- alarm pada event scenario yang sesuai ground truth -> kandidat `TP`
- alarm pada clean normal run -> `FP`
- alarm pada noisy non-event run -> `FP`
- fault tanpa event yang cocok -> `FN`
