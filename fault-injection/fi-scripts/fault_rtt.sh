#!/usr/bin/env bash
# =============================================================================
# fault_rtt.sh  —  S4 RTT Increase
#
# Tujuan:
#   Menambah delay pada seluruh trafik upstream KECUALI DNS (port 53).
#   Dengan begitu hanya ping/HTTP yang terasa lambat; DNS tetap cepat
#   sehingga detektor S1 DNS Delay tidak ikut terpicu.
#
# Cara kerja:
#   1) Trafik DNS dari client hotspot ditandai fwmark=53 via iptables mangle.
#   2) Root qdisc `prio` dibuat dengan 2 band:
#        band 1:1 → pfifo (no delay) — untuk paket bertanda 53 (DNS)
#        band 1:2 → netem delay      — untuk semua trafik lain
#   3) tc fw filter mengarahkan fwmark 53 ke band 1:1.
#   4) Semua trafik lain (default priomap=1 → band 1:2) kena delay.
#
# Contoh:
#   sudo ./fault_rtt.sh start 200
#   sudo ./fault_rtt.sh start 200 50    # dengan jitter 50 ms
#   sudo ./fault_rtt.sh stop
# =============================================================================

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/fault_common.sh"

usage() {
  cat <<'EOF'
Usage:
  sudo ./fault_rtt.sh start <delay_ms> [jitter_ms]
  sudo ./fault_rtt.sh stop

Examples:
  sudo ./fault_rtt.sh start 200
  sudo ./fault_rtt.sh start 200 50
  sudo ./fault_rtt.sh stop
EOF
}

start_fault() {
  local delay_ms="$1"
  local jitter_ms="${2:-}"

  require_root
  check_interface_exists "${UPSTREAM_IF}"
  check_interface_exists "${HOTSPOT_IF}"

  # Bersihkan root qdisc lama.
  remove_tc_root_if_exists "${UPSTREAM_IF}"

  # Tandai trafik DNS (port 53) dari client hotspot dengan fwmark=53.
  create_dns_mark_chain_if_needed
  attach_dns_mark_chain

  # Root prio qdisc: semua trafik default ke band 1:2 (kena delay).
  # priomap 1 1 ... → semua TOS class → band 2 (index 1).
  tc qdisc add dev "${UPSTREAM_IF}" root handle 1: prio bands 2 \
    priomap 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1

  # Pasang netem delay di band 1:2.
  if [[ -n "${jitter_ms}" ]]; then
    tc qdisc add dev "${UPSTREAM_IF}" parent 1:2 handle 20: \
      netem delay "${delay_ms}ms" "${jitter_ms}ms"
  else
    tc qdisc add dev "${UPSTREAM_IF}" parent 1:2 handle 20: \
      netem delay "${delay_ms}ms"
  fi

  # DNS (fwmark=53) → band 1:1 (pfifo, tanpa delay).
  tc filter add dev "${UPSTREAM_IF}" parent 1: protocol ip prio 1 \
    handle 53 fw flowid 1:1

  echo "[OK] S4 RTT fault aktif: delay=${delay_ms}ms jitter=${jitter_ms:-0}ms"
  echo "     DNS (port 53) dikecualikan dari delay."
  tc qdisc show dev "${UPSTREAM_IF}"
}

stop_fault() {
  require_root
  check_interface_exists "${UPSTREAM_IF}"

  remove_tc_root_if_exists "${UPSTREAM_IF}"

  # Bersihkan marking rules DNS.
  detach_dns_mark_chain
  destroy_dns_mark_chain

  echo "[OK] S4 RTT fault dihentikan."
}

case "${1:-}" in
  start)
    [[ -z "${2:-}" ]] && usage && exit 1
    start_fault "${2}" "${3:-}"
    ;;
  stop)
    stop_fault
    ;;
  *)
    usage
    exit 1
    ;;
esac
