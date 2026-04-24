#!/usr/bin/env bash
# =============================================================================
# rollback_all_faults.sh
#
# Tujuan:
#   Mengembalikan sistem ke kondisi bersih dari seluruh fault injection script
#   yang ada di folder ini.
#
# Yang dihapus:
#   - root qdisc tc pada interface upstream
#   - chain/rule iptables DNS outage
#   - chain/rule iptables mangle DNS mark
#   - paksa interface upstream kembali UP
#
# Kapan dipakai:
#   - habis eksperimen
#   - sebelum pindah ke fault lain
#   - kalau ada rule/qdisc yang nyangkut
#
# Cara pakai:
#   sudo ./rollback_all_faults.sh
# =============================================================================

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/fault_common.sh"

require_root
show_interfaces
check_interface_exists "${UPSTREAM_IF}"

rollback_all_common

echo "[OK] Rollback selesai."
echo "[INFO] Cek kondisi akhir:"
tc qdisc show dev "${UPSTREAM_IF}" || true
iptables -S "${DNS_OUTAGE_CHAIN}" 2>/dev/null || true
iptables -t mangle -S "${DNS_MARK_CHAIN}" 2>/dev/null || true
ip link show "${UPSTREAM_IF}" | head -n 1
