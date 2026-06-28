# Sensor Side

`sensor-side/` adalah runtime produksi modular untuk device sensor Micro-UXI. Folder ini terpisah dari `fault-tester`: fokusnya bukan lagi eksperimen per-skenario, tetapi menjalankan monitoring perangkat secara utuh dalam satu proses utama.

Fase implementasi saat ini mencakup:

- `Main` sebagai supervisor runtime
- `Monitoring` dengan probe `fast` dan `telemetry` berjalan bersamaan
- `Overhead` untuk memantau CPU, memori, disk, dan network I/O sistem

Modul berikut belum diimplementasikan, tetapi slot konfigurasinya sudah disiapkan:

- `Detection`
- `Evidence`
- `Exporter`

## Struktur

- `controller.py` adalah entry point runtime
- `config.py` memuat dan memvalidasi konfigurasi
- `monitoring.py` menjalankan scheduler probe `fast` dan `telemetry`
- `overhead.py` menjalankan sampling overhead sistem
- `probe/` berisi implementasi probe dan helper bersama

## Cara Kerja

1. `controller.py` memuat `config.json`
2. runtime menentukan modul mana yang aktif
3. `monitoring` menjalankan:
   - `fast` untuk sinyal ringan yang relevan ke event fast seperti S1/S2/S3/S6
   - `telemetry` untuk snapshot kaya metrik yang relevan ke event telemetry seperti S4/S5
4. `overhead` berjalan paralel dan mengambil metrik sistem
5. output default ditampilkan verbose di terminal
6. JSONL per modul bisa diaktifkan lewat config atau flag CLI

## CLI Dasar

```bash
cd sensor-side
python controller.py
python controller.py --duration 10m
python controller.py --enable-monitoring-jsonl --enable-overhead-jsonl
python controller.py --disable-overhead
python controller.py --quiet-monitoring
```

## Konfigurasi

Konfigurasi dipisah per modul dalam satu file utama:

- `device`: identitas node dan interface
- `runtime`: output path dan durasi default
- `modules`: switch enable/disable modul
- `monitoring`: scheduler, target ping/DNS/HTTP, verbosity, JSONL
- `overhead`: interval, metrik, verbosity, JSONL
- `detection`, `evidence`, `exporter`: placeholder untuk fase berikutnya

## Output

Default:

- monitoring verbose penuh di terminal
- overhead juga tampil di terminal
- file output nonaktif

Jika JSONL diaktifkan:

- `monitoring.jsonl` berisi sample `fast` dan `telemetry`
- `overhead.jsonl` berisi sample overhead sistem
