# Monitoring Rewrite

Stack monitoring baru untuk Micro-UXI yang memisahkan:

- `probes/` untuk akuisisi sample multi-rate
- `detector.py` untuk logika event S1-S6 dan A1
- `evidence.py` untuk evidence bundle lokal
- `controller.py` untuk orkestrasi worker, logging sample, dan lifecycle event

## Run

Dari root repo:

```bash
python -m monitoring.controller
```

Default run plan:

- mode: `once-all`
- fast interval: `5s`
- telemetry interval: `30s`
- throughput interval: `15m`
- duration: `indefinite`
- detection mode: `static`
- output: disabled

Sebelum run dimulai, controller akan:

1. menampilkan ringkasan run plan
2. meminta konfirmasi `y/n`
3. jika `n`, meminta field mana yang ingin diubah

Contoh:

```bash
python -m monitoring.controller --mode all --fast-interval 2s --detection-mode dynamic --output ./monitoring/out
```

## Output

Jika output diaktifkan, data ditulis ke path output yang dipilih:

- `samples/*.jsonl` untuk raw sample per probe
- `events_<run_id>.jsonl` untuk lifecycle event
- `evidence/<run_id>/<event_id>/` untuk bundle event

## Catatan

- Naming event mengikuti `docs/event.md`
- S5 direpresentasikan sebagai `HTTP_SLOW`
- Throughput dipisah sebagai `BANDWIDTH_THROTTLE` / A1
- `static` vs `dynamic` bisa dipilih per run
- Integrasi server sengaja belum dimasukkan
