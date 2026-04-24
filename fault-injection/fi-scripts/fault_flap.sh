#!/usr/bin/env bash
# =============================================================================
# fault_flap.sh
#
# Tujuan:
#   Mensimulasikan connectivity flap dengan cara mematikan lalu menyalakan lagi
#   interface upstream. Hotspot tetap ada, tapi jalur keluar putus.
#
# Mode:
#   1) once   -> flap satu kali
#   2) repeat -> flap berulang
#   3) down   -> paksa interface down
#   4) up     -> paksa interface up
#
# Contoh:
#   sudo ./fault_flap.sh once 5
#     -> upstream down 5 detik lalu up lagi
#
#   sudo ./fault_flap.sh repeat 3 5 10
#     -> 3 kali, tiap kali down 5 detik, lalu jeda 10 detik setelah up
#
#   sudo ./fault_flap.sh down
#   sudo ./fault_flap.sh up
# =============================================================================

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/fault_common.sh"

usage() {
  cat <<'EOF'
Usage:
  sudo ./fault_flap.sh once <down_seconds>
  sudo ./fault_flap.sh repeat <count> <down_seconds> <up_gap_seconds>
  sudo ./fault_flap.sh down
  sudo ./fault_flap.sh up

Examples:
  sudo ./fault_flap.sh once 5
  sudo ./fault_flap.sh repeat 3 5 10
  sudo ./fault_flap.sh down
  sudo ./fault_flap.sh up
EOF
}

do_down() {
  ip link set dev "${UPSTREAM_IF}" down
  echo "[OK] ${UPSTREAM_IF} -> DOWN"
}

do_up() {
  ip link set dev "${UPSTREAM_IF}" up
  echo "[OK] ${UPSTREAM_IF} -> UP"
}

once_flap() {
  local down_s="$1"
  do_down
  sleep "${down_s}"
  do_up
  echo "[OK] Connectivity flap once selesai."
}

repeat_flap() {
  local count="$1"
  local down_s="$2"
  local up_gap_s="$3"

  local i
  for ((i=1; i<=count; i++)); do
    echo "[INFO] Flap ${i}/${count}"
    do_down
    sleep "${down_s}"
    do_up
    if [[ "${i}" -lt "${count}" ]]; then
      sleep "${up_gap_s}"
    fi
  done

  echo "[OK] Connectivity flap repeat selesai."
}

require_root
check_interface_exists "${UPSTREAM_IF}"

case "${1:-}" in
  once)
    [[ -z "${2:-}" ]] && usage && exit 1
    once_flap "${2}"
    ;;
  repeat)
    [[ -z "${2:-}" || -z "${3:-}" || -z "${4:-}" ]] && usage && exit 1
    repeat_flap "${2}" "${3}" "${4}"
    ;;
  down)
    do_down
    ;;
  up)
    do_up
    ;;
  *)
    usage
    exit 1
    ;;
esac
