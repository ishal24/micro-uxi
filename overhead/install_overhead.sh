#!/usr/bin/env bash
# =============================================================================
# install_overhead.sh
#
# Instalasi dependensi untuk overhead monitoring Micro-UXI di Arduino Uno Q.
# Hanya memasang paket minimal yang dibutuhkan oleh overhead_monitor.py.
#
# Penggunaan:
#   sudo ./install_overhead.sh
# =============================================================================

set -e

VENV_DIR="/opt/microuxi-venv"

echo "============================================="
echo "  Micro-UXI Overhead Monitor — Installer"
echo "============================================="

# ── 1. Root check ─────────────────────────────────────────────────────────────
if [[ "${EUID}" -ne 0 ]]; then
    echo "[ERROR] Jalankan dengan sudo."
    exit 1
fi

# ── 2. Paket sistem ───────────────────────────────────────────────────────────
echo "[1/4] Mengecek & memasang paket sistem..."
apt-get update -qq
apt-get install -y --no-install-recommends \
    procps \
    python3 \
    python3-pip \
    python3-venv \
    > /dev/null

echo "      OK: procps, python3, python3-pip, python3-venv"

# ── 3. Python venv ────────────────────────────────────────────────────────────
echo "[2/4] Menyiapkan Python virtual environment di ${VENV_DIR}..."
if [[ ! -d "${VENV_DIR}" ]]; then
    python3 -m venv "${VENV_DIR}"
    echo "      OK: venv dibuat"
else
    echo "      OK: venv sudah ada, lewati pembuatan"
fi

# ── 4. Install psutil ke venv ────────────────────────────────────────────────
echo "[3/4] Memasang psutil ke venv (${VENV_DIR})..."
"${VENV_DIR}/bin/pip" install --quiet --upgrade pip
"${VENV_DIR}/bin/pip" install --quiet psutil
echo "      OK: psutil terpasang di venv"

# ── 5. Install psutil ke system Python juga (agar bisa dijalankan langsung) ──
echo "[4/4] Memasang psutil ke system Python (python3 / python)..."
# Coba pip3, kalau gagal lanjut saja (tidak wajib)
if python3 -m pip install --quiet --break-system-packages psutil 2>/dev/null; then
    echo "      OK: psutil terpasang di system Python (--break-system-packages)"
elif python3 -m pip install --quiet psutil 2>/dev/null; then
    echo "      OK: psutil terpasang di system Python"
else
    echo "      [!] Gagal install ke system Python — gunakan venv atau run_overhead.sh"
fi

echo ""
echo "============================================="
echo "  Instalasi selesai."
echo ""
echo "  Cara menjalankan (pilih salah satu):"
echo ""
echo "  1. Dengan run_overhead.sh (DIREKOMENDASIKAN):"
echo "     ./run_overhead.sh --server-url http://192.168.1.56:5000"
echo ""
echo "  2. Langsung dengan venv Python:"
echo "     ${VENV_DIR}/bin/python overhead_monitor.py \\"
echo "       --server-url http://192.168.1.56:5000"
echo ""
echo "  3. Langsung dengan system python (setelah install step [4/4] OK):"
echo "     sudo python3 overhead_monitor.py \\"
echo "       --server-url http://192.168.1.56:5000"
echo "============================================="
