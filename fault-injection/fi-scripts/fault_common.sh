#!/usr/bin/env bash
# Shared helpers for Micro-UXI fault injection scripts.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Interface hotspot/AP tempat Uno Q terhubung.
HOTSPOT_IF="${HOTSPOT_IF:-ap0}"

# Interface upstream/internet, biasanya USB Wi-Fi adapter.
UPSTREAM_IF="${UPSTREAM_IF:-wlxd037456b1bc8}"

# Subnet klien di belakang hotspot.
CLIENT_SUBNET="${CLIENT_SUBNET:-192.168.12.0/24}"

# Port HTTP response yang akan dibatasi untuk S5.
HTTP_SLOW_PORTS="${HTTP_SLOW_PORTS:-8080}"

# Config monitoring yang dipakai untuk mencoba sinkron target HTTP S5.
MONITORING_CONFIG="${MONITORING_CONFIG:-${REPO_ROOT}/monitoring/default_config.json}"

FI_TABLE="fi_fault"
DNS_OUTAGE_CHAIN="FI_FORWARD"
DNS_MARK_CHAIN="FI_MANGLE"

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    echo "[ERROR] Jalankan script ini dengan sudo/root."
    exit 1
  fi
}

show_interfaces() {
  echo "[INFO] HOTSPOT_IF      = ${HOTSPOT_IF}"
  echo "[INFO] UPSTREAM_IF     = ${UPSTREAM_IF}"
  echo "[INFO] CLIENT_SUBNET   = ${CLIENT_SUBNET}"
  echo "[INFO] HTTP_SLOW_PORTS = ${HTTP_SLOW_PORTS}"
  echo "[INFO] MONITORING_CFG  = ${MONITORING_CONFIG}"
}

check_interface_exists() {
  local dev="$1"
  if ! ip link show "${dev}" > /dev/null 2>&1; then
    echo "[ERROR] Interface '${dev}' tidak ditemukan."
    exit 1
  fi
}

detect_ipv4_by_interface() {
  local dev="$1"
  ip -4 addr show "${dev}" 2>/dev/null \
    | awk '/inet / {print $2}' \
    | cut -d/ -f1 \
    | head -n 1
}

remove_tc_root_if_exists() {
  local dev="$1"
  tc qdisc del dev "${dev}" root > /dev/null 2>&1 || true
}

monitoring_http_target_field() {
  local field="$1"
  local config_path="${2:-${MONITORING_CONFIG}}"

  if [[ ! -f "${config_path}" ]]; then
    return 0
  fi

  python3 - "${config_path}" "${field}" <<'PY'
import json
import sys

config_path = sys.argv[1]
field = sys.argv[2]

try:
    with open(config_path, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
except Exception:
    sys.exit(0)

targets = (cfg.get("telemetry_probe") or {}).get("http_targets") or []
if not targets:
    sys.exit(0)

value = targets[0].get(field)
if value is None:
    sys.exit(0)
if isinstance(value, (list, dict)):
    print(json.dumps(value))
else:
    print(value)
PY
}

monitoring_http_target_url() {
  monitoring_http_target_field "url" "${1:-${MONITORING_CONFIG}}"
}

monitoring_http_target_scope() {
  monitoring_http_target_field "scope" "${1:-${MONITORING_CONFIG}}"
}

http_port_from_url() {
  local url="$1"

  if [[ -z "${url}" ]]; then
    return 0
  fi

  python3 - "${url}" <<'PY'
import sys
from urllib.parse import urlparse

url = sys.argv[1].strip()
parsed = urlparse(url)

if not parsed.scheme:
    sys.exit(0)

if parsed.port:
    print(parsed.port)
elif parsed.scheme == "https":
    print(443)
elif parsed.scheme == "http":
    print(80)
PY
}

http_host_from_url() {
  local url="$1"

  if [[ -z "${url}" ]]; then
    return 0
  fi

  python3 - "${url}" <<'PY'
import sys
from urllib.parse import urlparse

url = sys.argv[1].strip()
parsed = urlparse(url)
if parsed.hostname:
    print(parsed.hostname)
PY
}

_nft_fi_table_exists() {
  nft list table ip "${FI_TABLE}" > /dev/null 2>&1
}

create_dns_outage_chain_if_needed() {
  if ! _nft_fi_table_exists; then
    nft add table ip "${FI_TABLE}"
  fi

  nft add chain ip "${FI_TABLE}" "${DNS_OUTAGE_CHAIN}" \
    '{ type filter hook forward priority -1; policy accept; }' 2>/dev/null || true

  nft flush chain ip "${FI_TABLE}" "${DNS_OUTAGE_CHAIN}"
}

attach_dns_outage_chain() {
  nft add rule ip "${FI_TABLE}" "${DNS_OUTAGE_CHAIN}" \
    iifname "${HOTSPOT_IF}" ip saddr "${CLIENT_SUBNET}" udp dport 53 drop
  nft add rule ip "${FI_TABLE}" "${DNS_OUTAGE_CHAIN}" \
    iifname "${HOTSPOT_IF}" ip saddr "${CLIENT_SUBNET}" tcp dport 53 drop
  echo "[INFO] nft DNS outage rules aktif."
  nft list chain ip "${FI_TABLE}" "${DNS_OUTAGE_CHAIN}"
}

detach_dns_outage_chain() {
  nft flush chain ip "${FI_TABLE}" "${DNS_OUTAGE_CHAIN}" 2>/dev/null || true
}

destroy_dns_outage_chain() {
  nft delete table ip "${FI_TABLE}" 2>/dev/null || true
}

create_dns_mark_chain_if_needed() {
  if ! _nft_fi_table_exists; then
    nft add table ip "${FI_TABLE}"
  fi

  nft add chain ip "${FI_TABLE}" "${DNS_MARK_CHAIN}" \
    '{ type filter hook prerouting priority -150; policy accept; }' 2>/dev/null || true

  nft flush chain ip "${FI_TABLE}" "${DNS_MARK_CHAIN}"
}

attach_dns_mark_chain() {
  nft add rule ip "${FI_TABLE}" "${DNS_MARK_CHAIN}" \
    iifname "${HOTSPOT_IF}" ip saddr "${CLIENT_SUBNET}" udp dport 53 meta mark set 53
  nft add rule ip "${FI_TABLE}" "${DNS_MARK_CHAIN}" \
    iifname "${HOTSPOT_IF}" ip saddr "${CLIENT_SUBNET}" tcp dport 53 meta mark set 53
  echo "[INFO] nft DNS mark rules aktif (mark 53)."
  nft list chain ip "${FI_TABLE}" "${DNS_MARK_CHAIN}"
}

detach_dns_mark_chain() {
  nft flush chain ip "${FI_TABLE}" "${DNS_MARK_CHAIN}" 2>/dev/null || true
}

destroy_dns_mark_chain() {
  nft delete chain ip "${FI_TABLE}" "${DNS_MARK_CHAIN}" 2>/dev/null || true
}

rollback_dns_rules() {
  nft delete table ip "${FI_TABLE}" 2>/dev/null || true
}

rollback_tc() {
  remove_tc_root_if_exists "${UPSTREAM_IF}"
}

rollback_all_common() {
  rollback_tc
  remove_tc_root_if_exists "${HOTSPOT_IF}"
  rollback_dns_rules
  ip link set dev "${UPSTREAM_IF}" up > /dev/null 2>&1 || true
}
