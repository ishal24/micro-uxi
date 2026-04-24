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
echo "[1/3] Mengecek & memasang paket sistem..."
apt-get update -qq
apt-get install -y --no-install-recommends \
    procps \
    python3 \
    python3-pip \
    python3-venv \
    > /dev/null

echo "      OK: procps, python3, python3-pip, python3-venv"

# ── 3. Python venv ────────────────────────────────────────────────────────────
echo "[2/3] Menyiapkan Python virtual environment di ${VENV_DIR}..."
if [[ ! -d "${VENV_DIR}" ]]; then
    python3 -m venv "${VENV_DIR}"
    echo "      OK: venv dibuat"
else
    echo "      OK: venv sudah ada, lewati pembuatan"
fi

# ── 4. Python packages ────────────────────────────────────────────────────────
echo "[3/3] Memasang library Python (psutil)..."
"${VENV_DIR}/bin/pip" install --quiet --upgrade pip
"${VENV_DIR}/bin/pip" install --quiet psutil

echo ""
echo "============================================="
echo "  Instalasi selesai."
echo "  Jalankan monitor dengan:"
echo "    ${VENV_DIR}/bin/python overhead_monitor.py --help"
echo "============================================="
