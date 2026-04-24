#!/usr/bin/env bash
# =============================================================================
# setup_http_server.sh  —  S5 Throughput Test Server
#
# Bikin test file 1 MB dan jalankan HTTP server di port 8080.
# Harus dijalankan di laptop (hotspot) sebelum eksperimen S5.
#
# Cara pakai:
#   bash setup_http_server.sh                # detect IP otomatis
#   bash setup_http_server.sh 10.64.88.54   # atau IP manual
# =============================================================================

PORT="${PORT:-8080}"
FILE_NAME="testfile_1mb.bin"
SERVE_DIR="${SERVE_DIR:-$(pwd)/http-serve}"
HOTSPOT_IF="${HOTSPOT_IF:-ap0}"

# ── Detect IP ─────────────────────────────────────────────────────────────────
detect_ip() {
  local iface="$1"
  ip -4 addr show "${iface}" 2>/dev/null \
    | grep -oP '(?<=inet\s)\d+(\.\d+){3}' \
    | head -1
}

echo "============================================================"
echo "  Micro-UXI — S5 HTTP Test Server Setup"
echo "============================================================"

# Cari IP
LAPTOP_IP="${1:-}"

if [[ -z "${LAPTOP_IP}" ]]; then
  LAPTOP_IP="$(detect_ip "${HOTSPOT_IF}")"
fi

if [[ -z "${LAPTOP_IP}" ]]; then
  echo ""
  echo "  [!] Interface '${HOTSPOT_IF}' tidak punya IPv4 address."
  echo "      Kemungkinan hotspot belum nyala."
  echo ""
  echo "  Cek interface yang tersedia:"
  ip -4 addr show 2>/dev/null | grep -E "^[0-9]+:|inet " | head -20
  echo ""
  echo "  Masukkan IP laptop kamu secara manual (atau Ctrl+C untuk batal):"
  read -rp "  IP: " LAPTOP_IP
  if [[ -z "${LAPTOP_IP}" ]]; then
    echo "[ERROR] IP tidak diisi. Keluar."
    exit 1
  fi
fi

echo ""
echo "  Laptop IP  : ${LAPTOP_IP}"
echo "  Port       : ${PORT}"
echo "  Serve dir  : ${SERVE_DIR}"

# ── Buat direktori dan test file ──────────────────────────────────────────────
mkdir -p "${SERVE_DIR}"
cd "${SERVE_DIR}"

if [[ ! -f "${FILE_NAME}" ]]; then
  echo ""
  echo "  [+] Membuat test file 1MB..."
  dd if=/dev/urandom of="${FILE_NAME}" bs=1M count=1 2>/dev/null
  echo "  [+] File dibuat: ${SERVE_DIR}/${FILE_NAME}"
else
  echo "  [+] Test file sudah ada: ${SERVE_DIR}/${FILE_NAME} ($(du -h "${FILE_NAME}" | cut -f1))"
fi

# ── Cek apakah port sudah dipakai ────────────────────────────────────────────
if ss -tlnp 2>/dev/null | grep -q ":${PORT} "; then
  echo ""
  echo "  [WARN] Port ${PORT} sudah dipakai:"
  ss -tlnp 2>/dev/null | grep ":${PORT} "
  echo "  Ubah PORT env var atau stop proses tersebut dulu."
  exit 1
fi

# ── Info URL ──────────────────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo "  URL test file:"
echo "    http://${LAPTOP_IP}:${PORT}/${FILE_NAME}"
echo ""
echo "  Pastikan config.json di Uno Q berisi:"
echo "    \"url\": \"http://${LAPTOP_IP}:${PORT}/${FILE_NAME}\","
echo "    \"expected_bytes\": 1048576"
echo ""
echo "  Test download dari Uno Q:"
echo "    curl -o /dev/null http://${LAPTOP_IP}:${PORT}/${FILE_NAME}"
echo ""
echo "  Server jalan di foreground. Ctrl+C untuk stop."
echo "============================================================"
echo ""

# ── Jalankan server ───────────────────────────────────────────────────────────
python3 -m http.server "${PORT}" --bind "${LAPTOP_IP}"
