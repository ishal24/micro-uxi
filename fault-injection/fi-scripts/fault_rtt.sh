#!/usr/bin/env bash
# S4 injector: tambahkan delay upstream, kecuali trafik DNS.

set -euo pipefail
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

  remove_tc_root_if_exists "${UPSTREAM_IF}"
  create_dns_mark_chain_if_needed
  attach_dns_mark_chain

  tc qdisc add dev "${UPSTREAM_IF}" root handle 1: prio bands 2 \
    priomap 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1

  if [[ -n "${jitter_ms}" ]]; then
    tc qdisc add dev "${UPSTREAM_IF}" parent 1:2 handle 20: \
      netem delay "${delay_ms}ms" "${jitter_ms}ms"
  else
    tc qdisc add dev "${UPSTREAM_IF}" parent 1:2 handle 20: \
      netem delay "${delay_ms}ms"
  fi

  tc filter add dev "${UPSTREAM_IF}" parent 1: protocol ip prio 1 \
    handle 53 fw flowid 1:1

  echo "[OK] S4 HIGH_RTT aktif: delay=${delay_ms}ms jitter=${jitter_ms:-0}ms"
  echo "[INFO] DNS tetap dilewatkan tanpa delay."
  tc qdisc show dev "${UPSTREAM_IF}"
}

stop_fault() {
  require_root
  check_interface_exists "${UPSTREAM_IF}"
  remove_tc_root_if_exists "${UPSTREAM_IF}"
  detach_dns_mark_chain
  destroy_dns_mark_chain
  echo "[OK] S4 HIGH_RTT dihentikan."
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
