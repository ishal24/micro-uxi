# Metrics Catalog

Dokumen ini mendefinisikan metrik yang dimonitor oleh Micro-UXI. Fokus dokumen ini adalah **sinyal pengukuran** yang dikumpulkan probe, bukan definisi event. Event didefinisikan terpisah di `events.md`.

## Conventions

- **Metric Name** harus konsisten dengan field log / dataset / script.
- **Used In Detection** menunjukkan apakah metrik dipakai dalam logika trigger event.
- **Expected Normal Range** adalah referensi operasional awal, bukan threshold final.
- **Sampling Mode** dapat berupa:
  - `periodic`
  - `continuous`
  - `state-change`
  - `event-only`
- **Stored In Evidence Bundle** menunjukkan apakah metrik disimpan pada pre-event / event / post-event window atau snapshot diagnostik.

## Metrics Table

| Metric Name | Category | Description | Unit | Data Type | Collection Method | Sampling Mode | Sampling Interval / Window | Expected Normal Range | Used In Detection | Related Events | Stored In Evidence Bundle | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `timestamp` | Metadata | Waktu pengambilan sampel telemetri | ISO 8601 / epoch | string / integer | System clock | periodic | every sample | monotonic, synchronized | Yes | all events | Yes | Wajib sinkron dengan fault injector untuk alignment ground truth |
| `run_id` | Metadata | Identitas satu sesi eksperimen | string | string | Assigned by controller / exporter | per run | once per run | unique | No | all events | Yes | Wajib untuk grouping dataset |
| `scenario_id` | Metadata | Identitas skenario uji / fault injection | string | string | Assigned by test controller | per run | once per run | valid scenario name | No | all events | Yes | Digunakan untuk evaluasi |
| `wifi_link_state` | Wi-Fi | Status konektivitas Wi-Fi probe | state | enum / boolean | Wi-Fi status API / system interface | state-change + periodic | every sample or on change | `connected` saat normal | Yes | `CONNECTIVITY_FLAP` | Yes | Metrik utama untuk event berbasis state change |
| `wifi_disconnect_count` | Wi-Fi | Jumlah transisi putus koneksi dalam window pendek | count | integer | Derived from `wifi_link_state` | periodic | rolling window 10–30 s | 0 | Yes | `CONNECTIVITY_FLAP` | Yes | Derived metric |
| `wifi_rssi_dbm` | Wi-Fi | Kekuatan sinyal Wi-Fi | dBm | float | Wi-Fi interface stats | periodic | every sample / 1–5 s | tergantung lokasi, mis. > -67 dBm baik | No / Optional | `CONNECTIVITY_FLAP` | Yes | Lebih cocok sebagai konteks diagnostik daripada trigger utama |
| `wifi_bssid` | Wi-Fi | BSSID AP yang terhubung | text | string | Wi-Fi interface stats | periodic | every sample / 5–30 s | stable within run | No | `CONNECTIVITY_FLAP` | Snapshot | Berguna untuk analisis roaming / AP switch |
| `wifi_channel` | Wi-Fi | Channel Wi-Fi aktif | number | integer | Wi-Fi interface stats | periodic | every sample / 5–30 s | stable within run | No | `CONNECTIVITY_FLAP` | Snapshot | Konteks diagnostik |
| `ip_address` | Network | Alamat IP probe saat sampling | IPv4/IPv6 | string | Network interface status | periodic | every sample / 5–30 s | valid assigned address | No | `CONNECTIVITY_FLAP` | Snapshot | Berguna untuk mendeteksi DHCP issue |
| `default_gateway` | Network | Gateway aktif probe | text | string | Routing table / interface status | periodic | every sample / 5–30 s | stable within run | No | all events | Snapshot | Konteks jaringan |
| `dns_resolver` | DNS | Resolver DNS yang digunakan | text | string | Network config / resolver status | periodic | every sample / 30–60 s | stable within run | No | `DNS_DEGRADED`, `DNS_TIMEOUT_BURST` | Snapshot | Penting untuk troubleshooting |
| `rtt_ms` | Network | Round-trip time hasil ping / probe ICMP | ms | float | Ping probe | periodic | e.g. 1 s | rendah dan stabil sesuai lingkungan | Yes | `HIGH_RTT`, `LOSS_BURST` | Yes | Salah satu sinyal inti |
| `packet_loss_pct` | Network | Persentase paket hilang dalam satu batch pengukuran | % | float | Ping probe batch | periodic | per probe window / 1–5 s | ~0% saat normal | Yes | `LOSS_BURST` | Yes | Harus didefinisikan window-nya secara konsisten |
| `consecutive_ping_failures` | Network | Jumlah kegagalan ping beruntun | count | integer | Derived from ping results | periodic | rolling per sample | 0 | Optional | `LOSS_BURST`, `CONNECTIVITY_FLAP` | Yes | Bagus untuk debounce / severity |
| `dns_latency_ms` | DNS | Latensi resolusi DNS untuk target uji | ms | float | Synthetic DNS query | periodic | e.g. 1–5 s | rendah dan stabil | Yes | `DNS_DEGRADED` | Yes | Sinyal utama kualitas DNS |
| `dns_timeout` | DNS | Status timeout pada query DNS | boolean | boolean | Synthetic DNS query | periodic | every DNS probe | `false` saat normal | Yes | `DNS_TIMEOUT_BURST` | Yes | Sinyal burst / outage |
| `dns_success_rate` | DNS | Rasio query DNS sukses pada window pendek | % | float | Derived from DNS probe results | periodic | rolling window 5–30 s | ~100% saat normal | Optional | `DNS_DEGRADED`, `DNS_TIMEOUT_BURST` | Yes | Derived metric untuk robustness |
| `http_connect_ms` | HTTP | Waktu untuk establish koneksi HTTP/TCP/TLS ke endpoint uji | ms | float | Synthetic HTTP timing | periodic | e.g. 5–10 s | rendah dan stabil | Yes | `HTTP_SLOW` | Yes | Sesuaikan definisi dengan tool yang dipakai |
| `http_total_ms` | HTTP | Total waktu transaksi HTTP (jika tersedia) | ms | float | Synthetic HTTP timing | periodic | e.g. 5–10 s | rendah dan stabil | Optional | `HTTP_SLOW` | Yes | Lebih representatif terhadap pengalaman aplikasi |
| `http_timeout` | HTTP | Status timeout pada pengecekan HTTP | boolean | boolean | Synthetic HTTP check | periodic | every HTTP probe | `false` saat normal | Yes | `HTTP_SLOW` | Yes | Untuk mendeteksi failure keras |
| `http_status_code` | HTTP | Status code HTTP dari endpoint uji | code | integer | HTTP response | periodic | every HTTP probe | 2xx / expected code | Optional | `HTTP_SLOW` | Yes | Lebih cocok untuk validasi layanan |
| `event_trigger_score` | Derived | Skor deviasi / anomaly score terhadap baseline | score | float | Derived from baseline model | periodic | every sample | rendah saat normal | Yes | all metric-based events | Yes | Digunakan jika implementasi memakai MAD / EWMA |
| `baseline_rtt_ms` | Derived | Baseline lokal RTT | ms | float | Rolling median / EWMA | periodic | rolling window | mengikuti kondisi normal | Yes | `HIGH_RTT` | Yes | Parameter internal detector |
| `baseline_dns_ms` | Derived | Baseline lokal DNS latency | ms | float | Rolling median / EWMA | periodic | rolling window | mengikuti kondisi normal | Yes | `DNS_DEGRADED` | Yes | Parameter internal detector |
| `baseline_http_ms` | Derived | Baseline lokal HTTP timing | ms | float | Rolling median / EWMA | periodic | rolling window | mengikuti kondisi normal | Yes | `HTTP_SLOW` | Yes | Parameter internal detector |
| `mad_rtt_ms` | Derived | Median absolute deviation untuk RTT | ms | float | Derived from rolling window | periodic | rolling window | kecil saat stabil | Yes | `HIGH_RTT` | Optional | Untuk adaptive threshold |
| `mad_dns_ms` | Derived | Median absolute deviation untuk DNS latency | ms | float | Derived from rolling window | periodic | rolling window | kecil saat stabil | Yes | `DNS_DEGRADED` | Optional | Untuk adaptive threshold |
| `mad_http_ms` | Derived | Median absolute deviation untuk HTTP timing | ms | float | Derived from rolling window | periodic | rolling window | kecil saat stabil | Yes | `HTTP_SLOW` | Optional | Untuk adaptive threshold |
| `cpu_usage_pct` | System | Penggunaan CPU probe | % | float | OS / runtime stats | periodic | e.g. 5–30 s | rendah saat normal | No | all events | Yes | Untuk evaluasi overhead |
| `ram_usage_mb` | System | Penggunaan RAM probe | MB | float | OS / runtime stats | periodic | e.g. 5–30 s | stabil sesuai workload | No | all events | Yes | Untuk evaluasi overhead |
| `storage_used_mb` | System | Pertumbuhan storage akibat telemetri dan evidence | MB | float | Filesystem stats | periodic | per run / 30–60 s | meningkat wajar | No | all events | Yes | Untuk evaluasi overhead |
| `bandwidth_tx_mb` | System | Volume data outbound ke collector / server | MB | float | Network stats / exporter counters | periodic | per run / 30–60 s | rendah saat normal | No | all events | Yes | Untuk overhead mode normal vs event |
| `bandwidth_rx_mb` | System | Volume data inbound terkait operasi monitoring | MB | float | Network stats | periodic | per run / 30–60 s | rendah saat normal | No | all events | Yes | Opsional, tergantung desain pipeline |
| `event_id` | Event Metadata | Identitas event yang terdeteksi | string | string | Assigned by detector | event-only | on event start | unique | No | all events | Yes | Muncul hanya saat event terjadi |
| `event_type` | Event Metadata | Jenis event yang dipicu detector | enum | string | Detector output | event-only | on event | valid event type | No | all events | Yes | Harus mengacu ke definisi di `events.md` |
| `event_severity` | Event Metadata | Tingkat keparahan event | enum | string | Detector output | event-only | on event | implementation-defined | No | all events | Yes | Opsional tapi berguna |
| `event_start_ts` | Event Metadata | Timestamp awal event | ISO 8601 / epoch | string / integer | Detector output | event-only | on event | valid timestamp | No | all events | Yes | Untuk alignment ke ground truth |
| `event_end_ts` | Event Metadata | Timestamp akhir event | ISO 8601 / epoch | string / integer | Detector output | event-only | on event close | valid timestamp | No | all events | Yes | Untuk durasi event |
| `event_duration_s` | Event Metadata | Durasi total event | s | float | Derived from event timestamps | event-only | on event close | > 0 for closed event | No | all events | Yes | Derived metric |
| `snapshot_net_status` | Snapshot | Ringkasan status interface / IP / route | text blob | text | System diagnostic snapshot | event-only | on event start / close | n/a | No | all events | Yes | Bagian evidence bundle |
| `snapshot_wifi_status` | Snapshot | Ringkasan Wi-Fi (RSSI, BSSID, channel, state) | text blob | text | Wi-Fi diagnostic snapshot | event-only | on event start / close | n/a | No | all events | Yes | Bagian evidence bundle |

## Notes

### Missing values
- Timeout atau failure dapat direpresentasikan sebagai:
  - field boolean terpisah seperti `dns_timeout = true`, atau
  - nilai numerik kosong / `null` dengan status failure terpisah.
- Jangan mencampur kedua pendekatan tanpa aturan yang jelas.

### Recommended timestamp policy
- Simpan timestamp dalam format yang mudah disejajarkan dengan ground truth, misalnya ISO 8601 UTC atau epoch milliseconds.
- Clock probe dan fault injector harus disinkronkan sebelum run.

### Recommended implementation policy
- Metrik **raw** dan metrik **derived** sebaiknya dibedakan jelas di dataset.
- Threshold final dan parameter trigger tidak perlu ditulis di dokumen ini; simpan di `events.md` atau file konfigurasi detector.
