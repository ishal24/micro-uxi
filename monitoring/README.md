# Monitoring Rewrite

Stack monitoring baru untuk Micro-UXI yang memisahkan:

- `probes/` untuk akuisisi sample multi-rate
- `detector.py` untuk logika event S1-S6 dan A1
- `evidence.py` untuk evidence bundle lokal
- `controller.py` untuk orkestrasi worker, logging sample, streaming, remote config, dan lifecycle event

## Run

Dari root repo:

```bash
python -m monitoring.controller
```

Default run plan:

- mode: `once-all`
- fast interval: `5s`
- telemetry interval: `30s`
- throughput interval: `60s`
- overhead interval: `2s`
- duration: `indefinite`
- detection mode: `static`
- output: disabled
- stream: disabled

Sebelum run dimulai, controller akan:

1. menampilkan ringkasan run plan
2. meminta konfirmasi `y/n`
3. jika `n`, meminta field mana yang ingin diubah

Contoh:

```bash
python -m monitoring.controller --mode all --fast-interval 2s --detection-mode dynamic --output ./monitoring/out
```

Untuk kirim sample langsung ke server dashboard, aktifkan stream dan isi IP/port
server:

```bash
python -m monitoring.controller --mode all --stream yes --stream-ip 192.168.12.1 --stream-port 5000
```

Kalau `--stream yes` dipilih tapi IP atau port belum diisi, controller akan
meminta keduanya sebelum run dimulai.

Saat `stream` aktif, controller juga polling remote config dari server melalui
`/api/config`. Nilai dari panel Remote Control di dashboard akan diterapkan ke
interval `fast`, `telemetry`, `throughput`, dan `overhead` tanpa restart.

## Output

Jika output diaktifkan, data ditulis ke path output yang dipilih:

- `samples/*.jsonl` untuk raw sample per probe
- `events_<run_id>.jsonl` untuk lifecycle event
- `evidence/<run_id>/<event_id>/` untuk bundle event
- bila `stream` aktif, sample sensor dikirim ke `http://<ip>:<port>/api/ingest/sensor`
- sample overhead dikirim ke `http://<ip>:<port>/api/ingest/overhead`

## Catatan

- Naming event mengikuti `docs/event.md`
- S5 direpresentasikan sebagai `HTTP_SLOW`
- Throughput dipisah sebagai `BANDWIDTH_THROTTLE` / A1
- Throughput default memakai Cloudflare speed endpoint seperti stack sensor lama
- Overhead sekarang menjadi worker controller dan tampil di dashboard server
- `static` vs `dynamic` bisa dipilih per run
- Integrasi server tersedia via opsi `stream`
