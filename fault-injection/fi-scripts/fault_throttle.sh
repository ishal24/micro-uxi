#!/usr/bin/env bash
# =============================================================================
# fault_throttle.sh
#
# Tujuan:
#   Mensimulasikan bandwidth throttling / pembatasan throughput.
#
# Cara kerja:
#   Script ini memasang `tc netem rate` di interface upstream.
#   Jadi throughput trafik keluar dibatasi ke rate tertentu.
#
# Contoh:
#   sudo ./fault_throttle.sh start 2mbit
#   sudo ./fault_throttle.sh start 1mbit
#   sudo ./fault_throttle.sh start 500kbit
#
#   sudo ./fault_throttle.sh stop
#
# Catatan:
#   Untuk eksperimen awal, `netem rate` sudah cukup.
#   Kalau nanti butuh shaping yang lebih presisi, baru pertimbangkan TBF/HTB.
# =============================================================================

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/fault_common.sh"

usage() {
  cat <<'EOF'
Usage:
  sudo ./fault_throttle.sh start <rate>
  sudo ./fault_throttle.sh stop

Examples:
  sudo ./fault_throttle.sh start 2mbit
  sudo ./fault_throttle.sh start 1mbit
  sudo ./fault_throttle.sh start 500kbit
  sudo ./fault_throttle.sh stop
EOF
}

start_fault() {
  local rate="$1"

  require_root
  check_interface_exists "${HOTSPOT_IF}"

  remove_tc_root_if_exists "${HOTSPOT_IF}"

  # Throttle hanya TCP sport 8080 (HTTP test server) pada HOTSPOT_IF (ap0) egress.
  # Traffic lain (DNS, ICMP ping) tetap tidak terbatas supaya tidak
  # memicu S1/S3 sebagai false positive selama eksperimen S5.
  #
  # Struktur:
  #   prio root
  #   ├── band 1:1 → pfifo (default, tidak terbatas) — untuk DNS, ping, dll
  #   └── band 1:2 → tbf rate X         — untuk HTTP port 8080 (throttled)
  #   filter: sport 8080 → 1:2; semua lain → 1:1 (default priomap)

  # priomap semua 0 = semua traffic default ke band 1 (tidak terbatas)
  tc qdisc add dev "${HOTSPOT_IF}" root handle 1: prio bands 2 \
    priomap 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0

  # Pasang tbf throttle di band 1:2
  tc qdisc add dev "${HOTSPOT_IF}" parent 1:2 handle 20: \
    tbf rate "${rate}" burst 15000 latency 200ms

  # Arahkan TCP sport 8080 (response dari HTTP server) ke band 1:2
  tc filter add dev "${HOTSPOT_IF}" parent 1:0 protocol ip prio 1 \
    u32 match ip protocol 6 0xff match ip sport 8080 0xffff flowid 1:2

  echo "[OK] S5 Throttle aktif: rate=${rate} hanya port 8080 di ${HOTSPOT_IF}"
  tc qdisc show dev "${HOTSPOT_IF}"
}

stop_fault() {
  require_root
  remove_tc_root_if_exists "${HOTSPOT_IF}" 2>/dev/null || true
  echo "[OK] S5 Bandwidth throttle dihentikan."
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
