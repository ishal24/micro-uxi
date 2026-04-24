#!/usr/bin/env bash
# =============================================================================
# run_all_faults.sh  —  Automated Sequential Fault Injection Runner
#
# Menjalankan semua 6 fault (S1–S6) satu per satu secara otomatis,
# dengan baseline period di antara setiap fault.
#
# Menghasilkan dua file output:
#   fault_timeline_<ts>.csv  — timeline fault injection (bisa di-compare
#                              dengan output CSV dari event_detector.py)
#   fault_timeline_<ts>.log  — log teks lengkap
#
# Cara pakai:
#   sudo ./run_all_faults.sh
#
# Konfigurasi (env var atau default):
#   BASELINE_SEC=30   HOTSPOT_IF=wlp0s20f3   UPSTREAM_IF=wlxd037456b1bc8
#   S1_DELAY_MS=400   S1_DURATION=45
#   S2_BURSTS=3       S2_OUTAGE_SEC=8   S2_GAP_SEC=5
#   S3_LOSS_PCT=60    S3_DURATION=30
#   S4_DELAY_MS=200   S4_DURATION=90
#   S5_RATE=1mbit     S5_DURATION=120
#   S6_FLAPS=3        S6_DOWN_SEC=8    S6_GAP_SEC=10
#   OUTPUT_DIR=./fi-output
#
# Syarat: jalankan dari direktori fi-scripts/ atau set PATH ke sana.
# =============================================================================

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/fault_common.sh"

# ── Konfigurasi default (override via env var) ─────────────────────────────
BASELINE_SEC="${BASELINE_SEC:-30}"

S1_DELAY_MS="${S1_DELAY_MS:-400}"
S1_DURATION="${S1_DURATION:-45}"

S2_BURSTS="${S2_BURSTS:-3}"
S2_OUTAGE_SEC="${S2_OUTAGE_SEC:-15}"
S2_GAP_SEC="${S2_GAP_SEC:-8}"

S3_LOSS_PCT="${S3_LOSS_PCT:-60}"
S3_DURATION="${S3_DURATION:-30}"

S4_DELAY_MS="${S4_DELAY_MS:-200}"
S4_DURATION="${S4_DURATION:-90}"

S5_RATE="${S5_RATE:-1mbit}"
S5_DURATION="${S5_DURATION:-120}"

S6_FLAPS="${S6_FLAPS:-3}"
S6_DOWN_SEC="${S6_DOWN_SEC:-15}"
S6_GAP_SEC="${S6_GAP_SEC:-10}"

OUTPUT_DIR="${OUTPUT_DIR:-${SCRIPT_DIR}/fi-output}"

# ── Setup output ───────────────────────────────────────────────────────────
require_root

SESSION_TS="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "${OUTPUT_DIR}"
TIMELINE_CSV="${OUTPUT_DIR}/fault_timeline_${SESSION_TS}.csv"
LOG_FILE="${OUTPUT_DIR}/fault_timeline_${SESSION_TS}.log"

# Redirect tee untuk log file
exec > >(tee -a "${LOG_FILE}") 2>&1

echo "============================================================"
echo "  Micro-UXI Automated Fault Runner"
echo "============================================================"
echo "  Session    : ${SESSION_TS}"
echo "  Timeline   : ${TIMELINE_CSV}"
echo "  Log        : ${LOG_FILE}"
echo "  Baseline   : ${BASELINE_SEC}s between faults"
echo ""
echo "  Fault params:"
echo "    S1 DNS Delay      : ${S1_DELAY_MS}ms for ${S1_DURATION}s"
echo "    S2 DNS Outage     : ${S2_BURSTS}x bursts, ${S2_OUTAGE_SEC}s down, ${S2_GAP_SEC}s gap"
echo "    S3 Packet Loss    : ${S3_LOSS_PCT}% for ${S3_DURATION}s"
echo "    S4 RTT Increase   : ${S4_DELAY_MS}ms for ${S4_DURATION}s"
echo "    S5 Throttle       : ${S5_RATE} for ${S5_DURATION}s"
echo "    S6 Flap           : ${S6_FLAPS}x flaps, ${S6_DOWN_SEC}s down, ${S6_GAP_SEC}s gap"
echo "============================================================"
echo ""

# ── CSV header ─────────────────────────────────────────────────────────────
echo "ts,fault_code,fault_name,action,params" > "${TIMELINE_CSV}"

# ── Helpers ────────────────────────────────────────────────────────────────

_ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }

_log() {
  local fault_code="$1" fault_name="$2" action="$3" params="${4:-}"
  local ts
  ts="$(_ts)"
  echo "${ts},${fault_code},${fault_name},${action},\"${params}\"" >> "${TIMELINE_CSV}"
  printf "[%s] [%-6s] %-8s  %s\n" "${ts}" "${fault_code}" "${action}" "${params}"
}

_baseline() {
  local label="${1:-BASELINE}"
  _log "NONE" "${label}" "BASELINE_START" "duration=${BASELINE_SEC}s"
  echo "  Waiting ${BASELINE_SEC}s baseline..."
  sleep "${BASELINE_SEC}"
  _log "NONE" "${label}" "BASELINE_END" ""
}

_rollback_all() {
  echo "  Rolling back all faults..."
  bash "${SCRIPT_DIR}/rollback_all_faults.sh" 2>/dev/null || true
}

# ── Rollback on exit ───────────────────────────────────────────────────────
trap '_rollback_all; echo "[!] Cleanup done."' EXIT INT TERM

# ── S1: DNS Delay ──────────────────────────────────────────────────────────
_baseline "pre-S1"
_log "S1" "DNS_DELAY" "FAULT_START" "delay=${S1_DELAY_MS}ms"
bash "${SCRIPT_DIR}/fault_dns_delay.sh" start "${S1_DELAY_MS}"
echo "  S1 active for ${S1_DURATION}s..."
sleep "${S1_DURATION}"
bash "${SCRIPT_DIR}/fault_dns_delay.sh" stop
_log "S1" "DNS_DELAY" "FAULT_STOP" "duration=${S1_DURATION}s"

# ── S2: DNS Outage Burst ───────────────────────────────────────────────────
_baseline "pre-S2"
_log "S2" "DNS_OUTAGE_BURST" "FAULT_START" "bursts=${S2_BURSTS} outage=${S2_OUTAGE_SEC}s gap=${S2_GAP_SEC}s"
for ((i=1; i<=S2_BURSTS; i++)); do
  _log "S2" "DNS_OUTAGE_BURST" "BURST_${i}_ON"  "burst ${i}/${S2_BURSTS}"
  bash "${SCRIPT_DIR}/fault_dns_outage.sh" start
  sleep "${S2_OUTAGE_SEC}"
  bash "${SCRIPT_DIR}/fault_dns_outage.sh" stop
  _log "S2" "DNS_OUTAGE_BURST" "BURST_${i}_OFF" "burst ${i}/${S2_BURSTS}"
  if [[ "${i}" -lt "${S2_BURSTS}" ]]; then
    sleep "${S2_GAP_SEC}"
  fi
done
_log "S2" "DNS_OUTAGE_BURST" "FAULT_STOP" ""

# ── S3: Packet Loss Burst ──────────────────────────────────────────────────
_baseline "pre-S3"
_log "S3" "PACKET_LOSS_BURST" "FAULT_START" "loss=${S3_LOSS_PCT}%"
bash "${SCRIPT_DIR}/fault_loss.sh" start "${S3_LOSS_PCT}"
echo "  S3 active for ${S3_DURATION}s..."
sleep "${S3_DURATION}"
bash "${SCRIPT_DIR}/fault_loss.sh" stop
_log "S3" "PACKET_LOSS_BURST" "FAULT_STOP" "duration=${S3_DURATION}s"

# ── S4: RTT Increase ───────────────────────────────────────────────────────
_baseline "pre-S4"
_log "S4" "RTT_INCREASE" "FAULT_START" "delay=${S4_DELAY_MS}ms"
bash "${SCRIPT_DIR}/fault_rtt.sh" start "${S4_DELAY_MS}"
echo "  S4 active for ${S4_DURATION}s (needs ≥2 telemetry cycles = 60s)..."
sleep "${S4_DURATION}"
bash "${SCRIPT_DIR}/fault_rtt.sh" stop
_log "S4" "RTT_INCREASE" "FAULT_STOP" "duration=${S4_DURATION}s"

# ── S5: Bandwidth Throttle ─────────────────────────────────────────────────
_baseline "pre-S5"

# Baca URL dari config.json (cari di parent dirs)
S5_TEST_URL="${S5_TEST_URL:-}"
if [[ -z "${S5_TEST_URL}" ]]; then
  CFG_FILE="$(find "${SCRIPT_DIR}/../.." -name "config.json" -path "*/sensor/*" 2>/dev/null | head -1)"
  if [[ -n "${CFG_FILE}" ]]; then
    S5_TEST_URL="$(python3 -c "import json; c=json.load(open('${CFG_FILE}')); print(c['throughput']['routine']['url'])" 2>/dev/null || true)"
  fi
fi

echo ""
echo "  [S5] Checking HTTP server sebelum throttle..."
if [[ -z "${S5_TEST_URL}" ]]; then
  echo "  [WARN] Tidak bisa baca URL dari config.json. Set S5_TEST_URL env var."
  echo "         Contoh: S5_TEST_URL=http://10.64.88.54:8080/testfile_1mb.bin"
else
  echo "  [S5] Test URL: ${S5_TEST_URL}"
  if curl -sf --max-time 10 -o /dev/null "${S5_TEST_URL}"; then
    echo "  [S5] ✓ HTTP server reachable — lanjut injeksi S5."
  else
    echo ""
    echo "  [ERROR] HTTP server TIDAK bisa diakses: ${S5_TEST_URL}"
    echo "  Jalankan dulu di laptop (terminal terpisah):"
    echo "    bash $(realpath ${SCRIPT_DIR})/setup_http_server.sh"
    echo ""
    echo "  Tekan Enter setelah server jalan, atau Ctrl+C untuk batal..."
    read -r
    if ! curl -sf --max-time 10 -o /dev/null "${S5_TEST_URL}"; then
      echo "  [ERROR] Server masih tidak bisa diakses. Skip S5."
      _log "S5" "THROTTLE" "SKIPPED" "HTTP server unreachable: ${S5_TEST_URL}"
      return 0 2>/dev/null || true
    fi
  fi
fi

_log "S5" "THROTTLE" "FAULT_START" "rate=${S5_RATE}"
bash "${SCRIPT_DIR}/fault_throttle.sh" start "${S5_RATE}"
echo "  S5 active for ${S5_DURATION}s..."
sleep "${S5_DURATION}"
bash "${SCRIPT_DIR}/fault_throttle.sh" stop
_log "S5" "THROTTLE" "FAULT_STOP" "duration=${S5_DURATION}s"

# ── S6: Connectivity Flap ──────────────────────────────────────────────────
_baseline "pre-S6"
_log "S6" "CONNECTIVITY_FLAP" "FAULT_START" "flaps=${S6_FLAPS} down=${S6_DOWN_SEC}s gap=${S6_GAP_SEC}s"
for ((i=1; i<=S6_FLAPS; i++)); do
  _log "S6" "CONNECTIVITY_FLAP" "FLAP_${i}_DOWN" "flap ${i}/${S6_FLAPS}"
  ip link set dev "${UPSTREAM_IF}" down
  sleep "${S6_DOWN_SEC}"
  ip link set dev "${UPSTREAM_IF}" up
  _log "S6" "CONNECTIVITY_FLAP" "FLAP_${i}_UP" "flap ${i}/${S6_FLAPS}"
  if [[ "${i}" -lt "${S6_FLAPS}" ]]; then
    sleep "${S6_GAP_SEC}"
  fi
done
_log "S6" "CONNECTIVITY_FLAP" "FAULT_STOP" ""

# ── Done ───────────────────────────────────────────────────────────────────
_baseline "post-S6-cooldown"

echo ""
echo "============================================================"
echo "  All faults complete!"
echo "  Timeline CSV : ${TIMELINE_CSV}"
echo "  Log          : ${LOG_FILE}"
echo ""
echo "  Compare with event_detector CSV:"
echo "    python3 - << 'PYEOF'"
echo "    import pandas as pd"
echo "    fi = pd.read_csv('${TIMELINE_CSV}')"
echo "    det = pd.read_csv('<path/to/events.csv>')"
echo "    print(fi[fi.action.str.contains('FAULT_START|BURST.*ON|FLAP.*DOWN')])"
echo "    PYEOF"
echo "============================================================"
