#!/usr/bin/env bash
# =============================================================================
# run_overhead.sh
#
# Wrapper shell untuk menjalankan overhead_monitor.py dengan mudah.
# Secara otomatis memakai venv yang sudah diinstall.
#
# Penggunaan:
#   ./run_overhead.sh                          # default (ringkasan, no file)
#   ./run_overhead.sh --verbose                # tampilan streaming
#   ./run_overhead.sh --daemon                 # background daemon
#   ./run_overhead.sh --stop                   # hentikan daemon
#   ./run_overhead.sh --status                 # cek status daemon
#   ./run_overhead.sh [args...]                # semua arg langsung diteruskan
#
# Contoh:
#   ./run_overhead.sh --verbose --duration 10m
#   ./run_overhead.sh --daemon --output out/overhead.jsonl --duration 1h
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="/opt/microuxi-venv/bin/python"
MONITOR="${SCRIPT_DIR}/overhead_monitor.py"
PIDFILE="${SCRIPT_DIR}/out/.overhead.pid"
OUTPUT_DIR="${SCRIPT_DIR}/out"

# ── Cek venv ──────────────────────────────────────────────────────────────────
if [[ ! -f "${VENV_PYTHON}" ]]; then
    echo "[ERROR] Python venv tidak ditemukan di /opt/microuxi-venv"
    echo "        Jalankan: sudo ./install_overhead.sh"
    exit 1
fi

mkdir -p "${OUTPUT_DIR}"

# ── Argumen khusus wrapper ────────────────────────────────────────────────────

if [[ "${1:-}" == "--stop" ]]; then
    if [[ -f "${PIDFILE}" ]]; then
        PID=$(cat "${PIDFILE}")
        if kill -0 "${PID}" 2>/dev/null; then
            kill "${PID}"
            rm -f "${PIDFILE}"
            echo "[OK] Daemon (PID ${PID}) dihentikan."
        else
            echo "[!] PID ${PID} tidak aktif. Membersihkan pidfile."
            rm -f "${PIDFILE}"
        fi
    else
        echo "[!] Tidak ada daemon yang berjalan (pidfile tidak ditemukan)."
    fi
    exit 0
fi

if [[ "${1:-}" == "--status" ]]; then
    if [[ -f "${PIDFILE}" ]]; then
        PID=$(cat "${PIDFILE}")
        if kill -0 "${PID}" 2>/dev/null; then
            echo "[OK] Daemon aktif — PID ${PID}"
            # Tampilkan 3 baris terakhir output jika ada
            LATEST=$(ls -t "${OUTPUT_DIR}"/overhead_*.jsonl 2>/dev/null | head -1)
            if [[ -n "${LATEST}" ]]; then
                echo "     File output: ${LATEST}"
                echo "     Sampel terakhir:"
                tail -1 "${LATEST}" | python3 -c "
import json,sys
d=json.load(sys.stdin)
print(f\"       ts={d.get('ts','-')}  cpu={d.get('cpu_pct','-')}%  mem={d.get('mem_pct','-')}%  proc_rss={d.get('proc_rss_mb','-')}MB\")
" 2>/dev/null || true
            fi
        else
            echo "[!] Daemon tidak aktif (PID ${PID} sudah mati)."
            rm -f "${PIDFILE}"
        fi
    else
        echo "[i] Tidak ada daemon yang berjalan."
    fi
    exit 0
fi

# ── Jika --daemon, tambahkan nama file output dengan timestamp ────────────────
EXTRA_ARGS=()
IS_DAEMON=false

for arg in "$@"; do
    [[ "${arg}" == "--daemon" || "${arg}" == "-d" ]] && IS_DAEMON=true
done

if "${IS_DAEMON}"; then
    # Tambahkan --output dan --pidfile otomatis jika user tidak menyebutkannya
    TS=$(date +%Y%m%d_%H%M%S)
    HAS_OUTPUT=false
    for arg in "$@"; do
        [[ "${arg}" == "--output" || "${arg}" == "-o" ]] && HAS_OUTPUT=true
    done
    if ! "${HAS_OUTPUT}"; then
        EXTRA_ARGS+=(--output "${OUTPUT_DIR}/overhead_${TS}.jsonl")
        EXTRA_ARGS+=(--csv    "${OUTPUT_DIR}/overhead_${TS}.csv")
    fi
    EXTRA_ARGS+=(--pidfile "${PIDFILE}")
    echo "[i] Menjalankan daemon..."
    echo "    Output : ${OUTPUT_DIR}/overhead_${TS}.jsonl"
    echo "    PIDfile: ${PIDFILE}"
    echo "    Stop dengan: ./run_overhead.sh --stop"
fi

# ── Jalankan ──────────────────────────────────────────────────────────────────
exec "${VENV_PYTHON}" "${MONITOR}" "$@" "${EXTRA_ARGS[@]}"
