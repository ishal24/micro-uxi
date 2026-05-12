#!/usr/bin/env bash
# Menjalankan fault injection S1-S6 secara berurutan dan menulis ground truth
# yang selaras dengan schema monitoring baru.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/fault_common.sh"

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
S5_TEST_URL="${S5_TEST_URL:-}"
S5_TARGET_SCOPE="${S5_TARGET_SCOPE:-}"
S5_TARGET_PORTS="${S5_TARGET_PORTS:-}"

S6_FLAPS="${S6_FLAPS:-3}"
S6_DOWN_SEC="${S6_DOWN_SEC:-15}"
S6_GAP_SEC="${S6_GAP_SEC:-10}"

OUTPUT_DIR="${OUTPUT_DIR:-${SCRIPT_DIR}/fi-output}"
ALIGNMENT_DELTA_SEC="${ALIGNMENT_DELTA_SEC:-5}"

require_root
check_interface_exists "${HOTSPOT_IF}"
check_interface_exists "${UPSTREAM_IF}"

SESSION_TS="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_ID="fi-${SESSION_TS}"
mkdir -p "${OUTPUT_DIR}"

TIMELINE_CSV="${OUTPUT_DIR}/fault_timeline_${SESSION_TS}.csv"
GROUND_TRUTH_JSONL="${OUTPUT_DIR}/ground_truth_${SESSION_TS}.jsonl"
LOG_FILE="${OUTPUT_DIR}/fault_timeline_${SESSION_TS}.log"

exec > >(tee -a "${LOG_FILE}") 2>&1

_ts() {
  date -u +%Y-%m-%dT%H:%M:%SZ
}

_json_array() {
  python3 - "$@" <<'PY'
import json
import sys
print(json.dumps(sys.argv[1:]))
PY
}

_timeline() {
  local scenario_id="$1"
  local event_type="$2"
  local action="$3"
  local details="${4:-}"
  local ts escaped
  ts="$(_ts)"
  escaped="${details//\"/\"\"}"
  echo "${ts},${scenario_id},${event_type},${action},\"${escaped}\"" >> "${TIMELINE_CSV}"
  printf "[%s] [%-21s] %-16s %s\n" "${ts}" "${event_type}" "${action}" "${details}"
}

_append_ground_truth() {
  local scenario_id="$1"
  local event_type="$2"
  local fault_type="$3"
  local fault_start_ts="$4"
  local fault_end_ts="$5"
  local target_scope="$6"
  local target_urls_json="$7"
  local params_json="$8"

  RUN_ID_VALUE="${RUN_ID}" \
  SCENARIO_ID="${scenario_id}" \
  EVENT_TYPE="${event_type}" \
  FAULT_TYPE="${fault_type}" \
  FAULT_START_TS="${fault_start_ts}" \
  FAULT_END_TS="${fault_end_ts}" \
  TARGET_SCOPE="${target_scope}" \
  TARGET_URLS_JSON="${target_urls_json}" \
  PARAMS_JSON="${params_json}" \
  HOTSPOT_IF_VALUE="${HOTSPOT_IF}" \
  UPSTREAM_IF_VALUE="${UPSTREAM_IF}" \
  CLIENT_SUBNET_VALUE="${CLIENT_SUBNET}" \
  ALIGNMENT_DELTA_VALUE="${ALIGNMENT_DELTA_SEC}" \
  python3 - "${GROUND_TRUTH_JSONL}" <<'PY'
import json
import os
import sys

record = {
    "run_id": os.environ["RUN_ID_VALUE"],
    "scenario_id": os.environ["SCENARIO_ID"],
    "event_type": os.environ["EVENT_TYPE"],
    "fault_type": os.environ["FAULT_TYPE"],
    "fault_start_ts": os.environ["FAULT_START_TS"],
    "fault_end_ts": os.environ["FAULT_END_TS"],
    "target_scope": os.environ["TARGET_SCOPE"],
    "target_urls": json.loads(os.environ["TARGET_URLS_JSON"]),
    "parameters": json.loads(os.environ["PARAMS_JSON"]),
    "alignment_delta_sec": int(os.environ["ALIGNMENT_DELTA_VALUE"]),
    "alignment_strategy": "first-match",
    "interfaces": {
        "hotspot_if": os.environ["HOTSPOT_IF_VALUE"],
        "upstream_if": os.environ["UPSTREAM_IF_VALUE"],
        "client_subnet": os.environ["CLIENT_SUBNET_VALUE"],
    },
}

with open(sys.argv[1], "a", encoding="utf-8") as fh:
    fh.write(json.dumps(record) + "\n")
PY
}

_baseline() {
  local label="$1"
  _timeline "NONE" "BASELINE" "BASELINE_START" "label=${label} duration_sec=${BASELINE_SEC}"
  sleep "${BASELINE_SEC}"
  _timeline "NONE" "BASELINE" "BASELINE_END" "label=${label}"
}

_rollback_all() {
  echo "[INFO] Rolling back all active faults."
  bash "${SCRIPT_DIR}/rollback_all_faults.sh" 2>/dev/null || true
}

trap '_rollback_all; echo "[INFO] Cleanup done."' EXIT INT TERM

HOTSPOT_IP="$(detect_ipv4_by_interface "${HOTSPOT_IF}")"

if [[ -z "${S5_TEST_URL}" ]]; then
  S5_TEST_URL="$(monitoring_http_target_url "${MONITORING_CONFIG}")"
fi
if [[ -z "${S5_TARGET_SCOPE}" ]]; then
  S5_TARGET_SCOPE="$(monitoring_http_target_scope "${MONITORING_CONFIG}")"
fi
if [[ -z "${S5_TARGET_PORTS}" && -n "${S5_TEST_URL}" ]]; then
  S5_TARGET_PORTS="$(http_port_from_url "${S5_TEST_URL}")"
fi

if [[ -z "${S5_TEST_URL}" && -n "${HOTSPOT_IP}" ]]; then
  S5_TEST_URL="http://${HOTSPOT_IP}:8080/testfile_1mb.bin"
fi
if [[ -z "${S5_TARGET_SCOPE}" && -n "${HOTSPOT_IP}" ]]; then
  if [[ "${S5_TEST_URL}" == "http://${HOTSPOT_IP}:"* ]]; then
    S5_TARGET_SCOPE="internal"
  fi
fi
if [[ -z "${S5_TARGET_SCOPE}" ]]; then
  S5_TARGET_SCOPE="unknown"
fi
if [[ -z "${S5_TARGET_PORTS}" ]]; then
  S5_TARGET_PORTS="${HTTP_SLOW_PORTS}"
fi

echo "============================================================"
echo "  Micro-UXI Automated Fault Runner"
echo "============================================================"
echo "  Run ID         : ${RUN_ID}"
echo "  Session        : ${SESSION_TS}"
echo "  Timeline CSV   : ${TIMELINE_CSV}"
echo "  Ground Truth   : ${GROUND_TRUTH_JSONL}"
echo "  Log File       : ${LOG_FILE}"
echo "  Baseline       : ${BASELINE_SEC}s"
echo ""
show_interfaces
echo "  Hotspot IP     : ${HOTSPOT_IP:-unknown}"
echo "  S5 Test URL    : ${S5_TEST_URL:-unset}"
echo "  S5 Scope       : ${S5_TARGET_SCOPE}"
echo "  S5 Port Match  : ${S5_TARGET_PORTS}"
echo ""
echo "  Fault params:"
echo "    S1 DNS_DEGRADED        : ${S1_DELAY_MS}ms for ${S1_DURATION}s"
echo "    S2 DNS_TIMEOUT_BURST   : ${S2_BURSTS} bursts, ${S2_OUTAGE_SEC}s down, ${S2_GAP_SEC}s gap"
echo "    S3 LOSS_BURST          : ${S3_LOSS_PCT}% for ${S3_DURATION}s"
echo "    S4 HIGH_RTT            : ${S4_DELAY_MS}ms for ${S4_DURATION}s"
echo "    S5 HTTP_SLOW           : ${S5_RATE} for ${S5_DURATION}s"
echo "    S6 CONNECTIVITY_FLAP   : ${S6_FLAPS} flaps, ${S6_DOWN_SEC}s down, ${S6_GAP_SEC}s gap"
echo "============================================================"
echo ""

echo "ts,scenario_id,event_type,action,details" > "${TIMELINE_CSV}"
: > "${GROUND_TRUTH_JSONL}"

S5_TARGET_URLS_JSON="[]"
if [[ -n "${S5_TEST_URL}" ]]; then
  S5_TARGET_URLS_JSON="$(_json_array "${S5_TEST_URL}")"
fi

_baseline "pre-S1"
S1_START_TS="$(_ts)"
_timeline "S1_DNS_DEGRADED" "DNS_DEGRADED" "FAULT_START" "delay_ms=${S1_DELAY_MS}"
bash "${SCRIPT_DIR}/fault_dns_delay.sh" start "${S1_DELAY_MS}"
sleep "${S1_DURATION}"
bash "${SCRIPT_DIR}/fault_dns_delay.sh" stop
S1_END_TS="$(_ts)"
_timeline "S1_DNS_DEGRADED" "DNS_DEGRADED" "FAULT_STOP" "duration_sec=${S1_DURATION}"
_append_ground_truth \
  "S1_DNS_DEGRADED" \
  "DNS_DEGRADED" \
  "dns_delay" \
  "${S1_START_TS}" \
  "${S1_END_TS}" \
  "all" \
  "[]" \
  "{\"injected_delay_ms\": ${S1_DELAY_MS}, \"duration_sec\": ${S1_DURATION}}"

_baseline "pre-S2"
S2_START_TS="$(_ts)"
_timeline "S2_DNS_TIMEOUT_BURST" "DNS_TIMEOUT_BURST" "FAULT_START" "bursts=${S2_BURSTS} outage_sec=${S2_OUTAGE_SEC} gap_sec=${S2_GAP_SEC}"
for ((i=1; i<=S2_BURSTS; i++)); do
  _timeline "S2_DNS_TIMEOUT_BURST" "DNS_TIMEOUT_BURST" "BURST_ON" "burst=${i}/${S2_BURSTS}"
  bash "${SCRIPT_DIR}/fault_dns_outage.sh" start
  sleep "${S2_OUTAGE_SEC}"
  bash "${SCRIPT_DIR}/fault_dns_outage.sh" stop
  _timeline "S2_DNS_TIMEOUT_BURST" "DNS_TIMEOUT_BURST" "BURST_OFF" "burst=${i}/${S2_BURSTS}"
  if [[ "${i}" -lt "${S2_BURSTS}" ]]; then
    sleep "${S2_GAP_SEC}"
  fi
done
S2_END_TS="$(_ts)"
_timeline "S2_DNS_TIMEOUT_BURST" "DNS_TIMEOUT_BURST" "FAULT_STOP" ""
_append_ground_truth \
  "S2_DNS_TIMEOUT_BURST" \
  "DNS_TIMEOUT_BURST" \
  "dns_outage_burst" \
  "${S2_START_TS}" \
  "${S2_END_TS}" \
  "all" \
  "[]" \
  "{\"burst_count\": ${S2_BURSTS}, \"outage_seconds\": ${S2_OUTAGE_SEC}, \"gap_seconds\": ${S2_GAP_SEC}}"

_baseline "pre-S3"
S3_START_TS="$(_ts)"
_timeline "S3_LOSS_BURST" "LOSS_BURST" "FAULT_START" "loss_pct=${S3_LOSS_PCT}"
bash "${SCRIPT_DIR}/fault_loss.sh" start "${S3_LOSS_PCT}"
sleep "${S3_DURATION}"
bash "${SCRIPT_DIR}/fault_loss.sh" stop
S3_END_TS="$(_ts)"
_timeline "S3_LOSS_BURST" "LOSS_BURST" "FAULT_STOP" "duration_sec=${S3_DURATION}"
_append_ground_truth \
  "S3_LOSS_BURST" \
  "LOSS_BURST" \
  "packet_loss" \
  "${S3_START_TS}" \
  "${S3_END_TS}" \
  "all" \
  "[]" \
  "{\"loss_percent\": ${S3_LOSS_PCT}, \"duration_sec\": ${S3_DURATION}}"

_baseline "pre-S4"
S4_START_TS="$(_ts)"
_timeline "S4_HIGH_RTT" "HIGH_RTT" "FAULT_START" "delay_ms=${S4_DELAY_MS}"
bash "${SCRIPT_DIR}/fault_rtt.sh" start "${S4_DELAY_MS}"
sleep "${S4_DURATION}"
bash "${SCRIPT_DIR}/fault_rtt.sh" stop
S4_END_TS="$(_ts)"
_timeline "S4_HIGH_RTT" "HIGH_RTT" "FAULT_STOP" "duration_sec=${S4_DURATION}"
_append_ground_truth \
  "S4_HIGH_RTT" \
  "HIGH_RTT" \
  "rtt_increase" \
  "${S4_START_TS}" \
  "${S4_END_TS}" \
  "all" \
  "[]" \
  "{\"injected_delay_ms\": ${S4_DELAY_MS}, \"duration_sec\": ${S4_DURATION}, \"dns_excluded\": true}"

_baseline "pre-S5"
S5_SKIPPED=0
if [[ -z "${S5_TEST_URL}" ]]; then
  echo "[WARN] S5 dilewati karena target HTTP belum diketahui."
  echo "       Set S5_TEST_URL atau isi telemetry_probe.http_targets di monitoring/default_config.json."
  _timeline "S5_HTTP_SLOW" "HTTP_SLOW" "SKIPPED" "missing_http_target"
  S5_SKIPPED=1
else
  echo "[INFO] S5 target HTTP: ${S5_TEST_URL}"
  if curl -sf --max-time 10 -o /dev/null "${S5_TEST_URL}"; then
    echo "[INFO] S5 target reachable."
  else
    echo "[WARN] Target S5 belum reachable: ${S5_TEST_URL}"
    echo "       Jalankan setup_http_server.sh jika kamu pakai target lokal."
    echo "       Tekan Enter untuk retry, atau Ctrl+C untuk batal."
    read -r
    if ! curl -sf --max-time 10 -o /dev/null "${S5_TEST_URL}"; then
      echo "[WARN] Target S5 masih gagal diakses. S5 dilewati."
      _timeline "S5_HTTP_SLOW" "HTTP_SLOW" "SKIPPED" "http_target_unreachable url=${S5_TEST_URL}"
      S5_SKIPPED=1
    fi
  fi
fi

if [[ "${S5_SKIPPED}" -eq 0 ]]; then
  export HTTP_SLOW_PORTS="${S5_TARGET_PORTS}"
  S5_START_TS="$(_ts)"
  _timeline "S5_HTTP_SLOW" "HTTP_SLOW" "FAULT_START" "rate=${S5_RATE} ports=${S5_TARGET_PORTS} url=${S5_TEST_URL}"
  bash "${SCRIPT_DIR}/fault_throttle.sh" start "${S5_RATE}"
  sleep "${S5_DURATION}"
  bash "${SCRIPT_DIR}/fault_throttle.sh" stop
  S5_END_TS="$(_ts)"
  _timeline "S5_HTTP_SLOW" "HTTP_SLOW" "FAULT_STOP" "duration_sec=${S5_DURATION}"
  _append_ground_truth \
    "S5_HTTP_SLOW" \
    "HTTP_SLOW" \
    "http_slow" \
    "${S5_START_TS}" \
    "${S5_END_TS}" \
    "${S5_TARGET_SCOPE}" \
    "${S5_TARGET_URLS_JSON}" \
    "{\"rate_limit\": \"${S5_RATE}\", \"duration_sec\": ${S5_DURATION}, \"applied_ports\": \"${S5_TARGET_PORTS}\", \"affected_phase\": \"total\"}"
fi

_baseline "pre-S6"
S6_START_TS="$(_ts)"
_timeline "S6_CONNECTIVITY_FLAP" "CONNECTIVITY_FLAP" "FAULT_START" "flaps=${S6_FLAPS} down_sec=${S6_DOWN_SEC} gap_sec=${S6_GAP_SEC}"
for ((i=1; i<=S6_FLAPS; i++)); do
  _timeline "S6_CONNECTIVITY_FLAP" "CONNECTIVITY_FLAP" "FLAP_DOWN" "flap=${i}/${S6_FLAPS}"
  ip link set dev "${UPSTREAM_IF}" down
  sleep "${S6_DOWN_SEC}"
  ip link set dev "${UPSTREAM_IF}" up
  _timeline "S6_CONNECTIVITY_FLAP" "CONNECTIVITY_FLAP" "FLAP_UP" "flap=${i}/${S6_FLAPS}"
  if [[ "${i}" -lt "${S6_FLAPS}" ]]; then
    sleep "${S6_GAP_SEC}"
  fi
done
S6_END_TS="$(_ts)"
_timeline "S6_CONNECTIVITY_FLAP" "CONNECTIVITY_FLAP" "FAULT_STOP" ""
_append_ground_truth \
  "S6_CONNECTIVITY_FLAP" \
  "CONNECTIVITY_FLAP" \
  "connectivity_flap" \
  "${S6_START_TS}" \
  "${S6_END_TS}" \
  "all" \
  "[]" \
  "{\"repeat_count\": ${S6_FLAPS}, \"down_duration_sec\": ${S6_DOWN_SEC}, \"up_gap_sec\": ${S6_GAP_SEC}, \"affected_layer\": \"upstream\"}"

_baseline "post-S6-cooldown"

echo ""
echo "============================================================"
echo "  All faults complete"
echo "  Timeline CSV : ${TIMELINE_CSV}"
echo "  Ground Truth : ${GROUND_TRUTH_JSONL}"
echo "  Log File     : ${LOG_FILE}"
echo ""
echo "  Gunakan ground_truth JSONL ini untuk alignment ke event monitoring:"
echo "    scenario_id"
echo "    event_type"
echo "    fault_start_ts"
echo "    fault_end_ts"
echo "============================================================"
