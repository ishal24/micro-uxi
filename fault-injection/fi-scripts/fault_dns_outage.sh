#!/usr/bin/env bash
# =============================================================================
# fault_dns_outage.sh
#
# Tujuan:
#   Mensimulasikan DNS outage / DNS timeout dengan cara DROP trafik DNS
#   (UDP/TCP port 53) dari client hotspot.
#
# Cara kerja:
#   - Buat chain iptables custom: FI_DNS_OUTAGE
#   - Hook chain itu ke FORWARD untuk trafik yang datang dari HOTSPOT_IF
#   - Semua paket DNS dari client hotspot akan di-drop
#
# Mode:
#   start -> aktifkan outage
#   stop  -> hapus outage
#   burst -> outage beberapa kali secara otomatis
#
# Contoh:
#   sudo ./fault_dns_outage.sh start
#   sudo ./fault_dns_outage.sh stop
#
#   sudo ./fault_dns_outage.sh burst 3 8 5
#     -> 3 burst, tiap burst aktif 8 detik, jeda 5 detik antar burst
# =============================================================================

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/fault_common.sh"

usage() {
  cat <<'EOF'
Usage:
  sudo ./fault_dns_outage.sh start
  sudo ./fault_dns_outage.sh stop
  sudo ./fault_dns_outage.sh burst <count> <outage_seconds> <gap_seconds>

Examples:
  sudo ./fault_dns_outage.sh start
  sudo ./fault_dns_outage.sh stop
  sudo ./fault_dns_outage.sh burst 3 8 5
EOF
}

start_fault() {
  require_root
  check_interface_exists "${HOTSPOT_IF}"

  create_dns_outage_chain_if_needed
  attach_dns_outage_chain

  echo "[OK] S2 DNS outage aktif. DNS dari client hotspot sekarang di-DROP (nft priority -1)."
}

stop_fault() {
  require_root
  detach_dns_outage_chain
  destroy_dns_outage_chain
  echo "[OK] DNS outage dihentikan."
}

burst_fault() {
  local count="$1"
  local outage_s="$2"
  local gap_s="$3"
  local i

  require_root
  for ((i=1; i<=count; i++)); do
    echo "[INFO] DNS outage burst ${i}/${count}: ON"
    start_fault
    sleep "${outage_s}"

    echo "[INFO] DNS outage burst ${i}/${count}: OFF"
    stop_fault

    if [[ "${i}" -lt "${count}" ]]; then
      sleep "${gap_s}"
    fi
  done

  echo "[OK] DNS outage burst selesai."
}

case "${1:-}" in
  start)
    start_fault
    ;;
  stop)
    stop_fault
    ;;
  burst)
    [[ -z "${2:-}" || -z "${3:-}" || -z "${4:-}" ]] && usage && exit 1
    burst_fault "${2}" "${3}" "${4}"
    ;;
  *)
    usage
    exit 1
    ;;
esac
