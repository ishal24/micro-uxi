# Sensor Side

`sensor-side/` adalah runtime produksi modular untuk device sensor Micro-UXI. Folder ini terpisah dari `fault-tester`: fokusnya bukan lagi eksperimen per-skenario, tetapi menjalankan monitoring perangkat secara utuh dalam satu proses utama.

Fase implementasi saat ini mencakup:

- `Main` sebagai supervisor runtime
- `Monitoring` dengan probe `fast` dan `telemetry` berjalan bersamaan
- `Overhead` untuk memantau CPU, memori, disk, dan network I/O sistem
- `Detection` untuk alarm event real-time berbasis stream sample monitoring
- `Exporter` untuk mengirim record monitoring, overhead, dan detection ke endpoint HTTP generik

Modul berikut belum diimplementasikan, tetapi slot konfigurasinya sudah disiapkan:

- `Evidence`

## Struktur

- `controller.py` adalah entry point runtime
- `config.py` memuat dan memvalidasi konfigurasi
- `monitoring.py` menjalankan scheduler probe `fast` dan `telemetry`
- `overhead.py` menjalankan sampling overhead sistem
- `detection.py` menjalankan deteksi event dari sample monitoring
- `exporter.py` menjalankan queue + retry untuk pengiriman HTTP generik
- `probe/` berisi implementasi probe dan helper bersama

## Cara Kerja

1. `controller.py` memuat `config.json`
2. runtime menentukan modul mana yang aktif
3. `monitoring` menjalankan:
   - `fast` untuk sinyal ringan yang relevan ke event fast seperti S1/S2/S3/S6
   - `telemetry` untuk snapshot kaya metrik yang relevan ke event telemetry seperti S4/S5
4. `overhead` berjalan paralel dan mengambil metrik sistem
5. `detection` menerima sample `fast` dan `telemetry` dari `monitoring`, lalu mengevaluasi event
6. `exporter` menerima sample/event dari modul lain dan mengirimkannya ke endpoint HTTP generik lewat background queue
7. mode deteksi bisa dipilih antara baseline statik dan dynamic event-driven
8. output default ditampilkan verbose di terminal
9. JSONL per modul bisa diaktifkan lewat config atau flag CLI

## CLI Dasar

```bash
cd sensor-side
python controller.py
python controller.py --duration 10m
python controller.py --enable-monitoring-jsonl --enable-overhead-jsonl
python controller.py --disable-overhead
python controller.py --disable-exporter
python controller.py --enable-exporter
python controller.py --quiet-monitoring
```

## Konfigurasi

Konfigurasi dipisah per modul dalam satu file utama:

- `device`: identitas node dan interface
- `runtime`: output path dan durasi default
- `modules`: switch enable/disable modul
- `monitoring`: scheduler, target ping/DNS/HTTP, verbosity, JSONL
- `overhead`: interval, metrik, verbosity, JSONL
- `detection`: switch modul dan path ke file config deteksi terpisah
- `exporter`: switch modul dan path ke file config exporter terpisah
- `evidence`: placeholder untuk fase berikutnya

File deteksi dipisah di `detection_config.json`. Di file ini terdapat:

- `detection.mode = baseline | dynamic`
- threshold baseline statik
- parameter EWMA untuk mode event-driven
- rule per event seperti `confirm_consecutive`, `n_dns/m_dns`, `n_ping/m_ping`, dan `n_flap/m_transition`

Catatan mode:

- `mode = baseline` memakai threshold statik
- `mode = dynamic` memakai EWMA event-driven
- tidak ada lagi `dynamic_thresholds.enabled`; pemilih mode hanya `detection.mode`

File exporter dipisah di `exporter_config.json`. Di file ini terdapat:

- `transport.base_url`, `api_key`, `timeout_sec`
- path endpoint per stream: `monitoring`, `overhead`, `detection`
- queue memory bounded
- retry delay dan attempt policy
- toggle stream per jenis data

## Output

Default:

- monitoring verbose penuh di terminal
- overhead juga tampil di terminal
- file output nonaktif

Jika JSONL diaktifkan:

- `monitoring.jsonl` berisi sample `fast` dan `telemetry`
- `overhead.jsonl` berisi sample overhead sistem
- `detection.jsonl` berisi alarm dan recovery event

Exporter tidak menulis outbox lokal. Jika aktif, exporter mengirim:

- semua sample monitoring
- semua sample overhead
- hanya transition event detection (`ALARM` dan `RECOVERY`)
