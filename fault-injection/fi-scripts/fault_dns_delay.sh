#!/usr/bin/env bash
# =============================================================================
# fault_dns_delay.sh
#
# Tujuan:
#   Mensimulasikan DNS Delay, yaitu menambah delay hanya pada trafik DNS.
#
# Cara kerja:
#   1) Trafik DNS dari client hotspot ditandai (fwmark=53) dengan iptables mangle
#   2) Di interface upstream dibuat qdisc `prio`
#   3) Band 1 diberi `netem delay`
#   4) Filter `tc fw` mengarahkan paket bertanda 53 ke band yang kena delay
#
# Mode:
#   start <delay_ms> [jitter_ms]
#   stop
#
# Contoh:
#   sudo ./fault_dns_delay.sh start 400
#   sudo ./fault_dns_delay.sh start 400 50
#   sudo ./fault_dns_delay.sh stop
#
# Catatan:
#   Script ini memakai root qdisc di interface upstream.
#   Jadi jangan digabung dulu dengan RTT/loss/throttle tanpa desain qdisc yang lain.
# =============================================================================

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/fault_common.sh"

usage() {
  cat <<'EOF'
Usage:
  sudo ./fault_dns_delay.sh start <delay_ms> [jitter_ms]
  sudo ./fault_dns_delay.sh stop

Examples:
  sudo ./fault_dns_delay.sh start 400
  sudo ./fault_dns_delay.sh start 400 50
  sudo ./fault_dns_delay.sh stop
EOF
}

start_fault() {
  local delay_ms="$1"
  local jitter_ms="${2:-}"

  require_root
  check_interface_exists "${HOTSPOT_IF}"
  check_interface_exists "${UPSTREAM_IF}"

  # Bersihkan root qdisc lama dulu supaya tidak bentrok.
  remove_tc_root_if_exists "${UPSTREAM_IF}"

  # Buat marking rule DNS.
  create_dns_mark_chain_if_needed
  attach_dns_mark_chain

  # Buat root qdisc prio.
  tc qdisc add dev "${UPSTREAM_IF}" root handle 1: prio

  # Pasang netem delay di band 1:1.
  if [[ -n "${jitter_ms}" ]]; then
    tc qdisc add dev "${UPSTREAM_IF}" parent 1:1 handle 10: netem delay "${delay_ms}ms" "${jitter_ms}ms"
  else
    tc qdisc add dev "${UPSTREAM_IF}" parent 1:1 handle 10: netem delay "${delay_ms}ms"
  fi

  # Arahkan semua paket yang punya fwmark 53 ke flow/band 1:1.
  tc filter add dev "${UPSTREAM_IF}" parent 1: protocol ip prio 1 handle 53 fw flowid 1:1

  echo "[OK] DNS delay aktif: delay=${delay_ms}ms jitter=${jitter_ms:-0}ms"
  tc qdisc show dev "${UPSTREAM_IF}"
  tc filter show dev "${UPSTREAM_IF}"
}

stop_fault() {
  require_root

  # Hapus qdisc root dan semua child/filter di bawahnya.
  remove_tc_root_if_exists "${UPSTREAM_IF}"

  # Hapus marking rules DNS.
  detach_dns_mark_chain
  destroy_dns_mark_chain

  echo "[OK] DNS delay dihentikan."
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
