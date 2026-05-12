#!/usr/bin/env bash
# S5 injector: membatasi response traffic HTTP agar monitoring menangkap HTTP_SLOW.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/fault_common.sh"

usage() {
  cat <<'EOF'
Usage:
  sudo ./fault_throttle.sh start <rate>
  sudo ./fault_throttle.sh stop

Optional env:
  HTTP_SLOW_PORTS=8080
  HTTP_SLOW_PORTS=80,443

Examples:
  sudo ./fault_throttle.sh start 1mbit
  sudo HTTP_SLOW_PORTS=8080 ./fault_throttle.sh start 500kbit
  sudo HTTP_SLOW_PORTS=443 ./fault_throttle.sh start 2mbit
  sudo ./fault_throttle.sh stop
EOF
}

parse_ports() {
  local raw="${1:-${HTTP_SLOW_PORTS}}"
  local cleaned=""
  local part

  IFS=',' read -r -a parts <<< "${raw}"
  for part in "${parts[@]}"; do
    part="$(echo "${part}" | tr -d '[:space:]')"
    [[ -z "${part}" ]] && continue
    if [[ ! "${part}" =~ ^[0-9]+$ ]] || (( part < 1 || part > 65535 )); then
      echo "[ERROR] Port HTTP_SLOW_PORTS tidak valid: '${part}'"
      exit 1
    fi
    if [[ -n "${cleaned}" ]]; then
      cleaned="${cleaned},"
    fi
    cleaned="${cleaned}${part}"
  done

  if [[ -z "${cleaned}" ]]; then
    echo "[ERROR] HTTP_SLOW_PORTS kosong."
    exit 1
  fi

  echo "${cleaned}"
}

start_fault() {
  local rate="$1"
  local ports
  local port

  require_root
  check_interface_exists "${HOTSPOT_IF}"

  ports="$(parse_ports)"
  remove_tc_root_if_exists "${HOTSPOT_IF}"

  # Default band 1:1 tidak dibatasi. Band 1:2 dibatasi dengan TBF.
  # Yang diarahkan ke band 1:2 hanya traffic response HTTP pada port tertentu.
  tc qdisc add dev "${HOTSPOT_IF}" root handle 1: prio bands 2 \
    priomap 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0

  tc qdisc add dev "${HOTSPOT_IF}" parent 1:2 handle 20: \
    tbf rate "${rate}" burst 15000 latency 200ms

  IFS=',' read -r -a port_list <<< "${ports}"
  for port in "${port_list[@]}"; do
    tc filter add dev "${HOTSPOT_IF}" parent 1:0 protocol ip prio 1 \
      u32 match ip protocol 6 0xff match ip sport "${port}" 0xffff flowid 1:2
  done

  echo "[OK] S5 HTTP_SLOW aktif: rate=${rate} ports=${ports} iface=${HOTSPOT_IF}"
  tc qdisc show dev "${HOTSPOT_IF}"
  tc filter show dev "${HOTSPOT_IF}"
}

stop_fault() {
  require_root
  remove_tc_root_if_exists "${HOTSPOT_IF}" > /dev/null 2>&1 || true
  echo "[OK] S5 HTTP_SLOW dihentikan."
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
