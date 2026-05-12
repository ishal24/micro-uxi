#!/usr/bin/env bash
# Bersihkan seluruh fault injection state dari folder fi-scripts.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/fault_common.sh"

require_root
show_interfaces
check_interface_exists "${UPSTREAM_IF}"
check_interface_exists "${HOTSPOT_IF}"

rollback_all_common

echo "[OK] Rollback selesai."
echo "[INFO] Kondisi qdisc ${UPSTREAM_IF}:"
tc qdisc show dev "${UPSTREAM_IF}" || true
echo "[INFO] Kondisi qdisc ${HOTSPOT_IF}:"
tc qdisc show dev "${HOTSPOT_IF}" || true
echo "[INFO] Kondisi nft table ${FI_TABLE}:"
nft list table ip "${FI_TABLE}" 2>/dev/null || echo "[INFO] table ${FI_TABLE} tidak ada."
echo "[INFO] Link ${UPSTREAM_IF}:"
ip link show "${UPSTREAM_IF}" | head -n 1
