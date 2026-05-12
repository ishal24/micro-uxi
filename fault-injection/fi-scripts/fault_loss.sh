#!/usr/bin/env bash
# S3 injector: tambahkan packet loss pada jalur upstream.

set -euo pipefail
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
  echo "[OK] S3 LOSS_BURST aktif: loss=${loss_pct}% iface=${UPSTREAM_IF}"
  tc qdisc show dev "${UPSTREAM_IF}"
}

stop_fault() {
  require_root
  check_interface_exists "${UPSTREAM_IF}"
  remove_tc_root_if_exists "${UPSTREAM_IF}"
  echo "[OK] S3 LOSS_BURST dihentikan."
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
