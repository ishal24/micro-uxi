#!/usr/bin/env bash
# Local HTTP target untuk eksperimen S5_HTTP_SLOW.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/fault_common.sh"

PORT="${PORT:-8080}"
FILE_NAME="${FILE_NAME:-testfile_1mb.bin}"
SERVE_DIR="${SERVE_DIR:-$(pwd)/http-serve}"

echo "============================================================"
echo "  Micro-UXI S5 Local HTTP Server"
echo "============================================================"

LAPTOP_IP="${1:-}"
if [[ -z "${LAPTOP_IP}" ]]; then
  LAPTOP_IP="$(detect_ipv4_by_interface "${HOTSPOT_IF}")"
fi

if [[ -z "${LAPTOP_IP}" ]]; then
  echo ""
  echo "[WARN] Interface '${HOTSPOT_IF}' belum punya IPv4."
  echo "       Pastikan hotspot aktif atau isi IP manual."
  echo ""
  ip -4 addr show 2>/dev/null | grep -E '^[0-9]+:|inet ' | head -20
  echo ""
  read -rp "Masukkan IP hotspot laptop: " LAPTOP_IP
  if [[ -z "${LAPTOP_IP}" ]]; then
    echo "[ERROR] IP tidak diisi."
    exit 1
  fi
fi

mkdir -p "${SERVE_DIR}"
cd "${SERVE_DIR}"

if [[ ! -f "${FILE_NAME}" ]]; then
  echo "[INFO] Membuat file uji 1MB di ${SERVE_DIR}/${FILE_NAME}"
  dd if=/dev/urandom of="${FILE_NAME}" bs=1M count=1 status=none
else
  echo "[INFO] File uji sudah ada: ${SERVE_DIR}/${FILE_NAME}"
fi

if ss -tln 2>/dev/null | grep -q ":${PORT} "; then
  echo "[ERROR] Port ${PORT} sudah dipakai."
  ss -tlnp 2>/dev/null | grep ":${PORT} " || true
  exit 1
fi

echo ""
echo "Target URL untuk monitoring:"
echo "  http://${LAPTOP_IP}:${PORT}/${FILE_NAME}"
echo ""
echo "Snippet yang disarankan untuk monitoring/default_config.json:"
echo '  "http_targets": ['
echo "    {"
echo "      \"url\": \"http://${LAPTOP_IP}:${PORT}/${FILE_NAME}\","
echo '      "scope": "internal",'
echo '      "expected_status_min": 200,'
echo '      "expected_status_max": 399'
echo "    }"
echo '  ]'
echo ""
echo "Set port shaping S5 bila perlu:"
echo "  HTTP_SLOW_PORTS=${PORT}"
echo ""
echo "Server jalan di foreground. Ctrl+C untuk stop."
echo "============================================================"
echo ""

python3 -m http.server "${PORT}" --bind "${LAPTOP_IP}"
