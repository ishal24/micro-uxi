#!/usr/bin/env bash
# S2 injector: putuskan DNS dari klien hotspot secara burst.

set -euo pipefail
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
  echo "[OK] S2 DNS_TIMEOUT_BURST aktif."
}

stop_fault() {
  require_root
  detach_dns_outage_chain
  destroy_dns_outage_chain
  echo "[OK] S2 DNS_TIMEOUT_BURST dihentikan."
}

burst_fault() {
  local count="$1"
  local outage_s="$2"
  local gap_s="$3"
  local i

  require_root
  for ((i=1; i<=count; i++)); do
    echo "[INFO] S2 burst ${i}/${count}: ON"
    start_fault
    sleep "${outage_s}"
    echo "[INFO] S2 burst ${i}/${count}: OFF"
    stop_fault
    if [[ "${i}" -lt "${count}" ]]; then
      sleep "${gap_s}"
    fi
  done
  echo "[OK] S2 DNS_TIMEOUT_BURST selesai."
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
