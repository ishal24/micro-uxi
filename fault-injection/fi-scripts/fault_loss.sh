#!/usr/bin/env bash
# =============================================================================
# fault_loss.sh
#
# Tujuan:
#   Mensimulasikan packet loss pada jalur upstream.
#
# Cara kerja:
#   Script ini memasang `tc netem loss` pada interface upstream.
#   Semua trafik keluar dari laptop lewat interface itu akan mengalami loss
#   sesuai persen yang kamu tentukan.
#
# Contoh:
#   sudo ./fault_loss.sh start 15
#     -> loss 15%
#
#   sudo ./fault_loss.sh stop
#     -> hapus loss injection
#
# Catatan:
#   Untuk "burst" paling sederhana, aktifkan selama beberapa detik lalu stop.
#   Atau bungkus dari shell:
#     sudo ./fault_loss.sh start 15
#     sleep 10
#     sudo ./fault_loss.sh stop
# =============================================================================

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/fault_common.sh"

usage() {
  cat <<'EOF'
Usage:
  sudo ./fault_loss.sh start <loss_percent>
  sudo ./fault_loss.sh stop

Examples:
  sudo ./fault_loss.sh start 10
  sudo ./fault_loss.sh start 15
  sudo ./fault_loss.sh stop
EOF
}

start_fault() {
  local loss_pct="$1"

  require_root
  check_interface_exists "${UPSTREAM_IF}"

  remove_tc_root_if_exists "${UPSTREAM_IF}"
  tc qdisc add dev "${UPSTREAM_IF}" root netem loss "${loss_pct}%"

  echo "[OK] Packet loss fault aktif: loss=${loss_pct}% di ${UPSTREAM_IF}"
  tc qdisc show dev "${UPSTREAM_IF}"
}

stop_fault() {
  require_root
  check_interface_exists "${UPSTREAM_IF}"
  remove_tc_root_if_exists "${UPSTREAM_IF}"
  echo "[OK] Packet loss fault dihentikan."
}

case "${1:-}" in
  start)
    [[ -z "${2:-}" ]] && usage && exit 1
    start_fault "${2}"
    ;;
  stop)
    stop_fault
    ;;
  *)
    usage
    exit 1
    ;;
esac
