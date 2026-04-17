#!/usr/bin/env bash
# =============================================================================
# inject_s2.sh — S2: DNS Outage Burst Fault Injection
# =============================================================================
# Topology: Internet → Ubuntu Laptop (hotspot) → Uno Q
#
# Mechanism: DROP inbound DNS queries (port 53 UDP+TCP) from the Uno Q
#            at the laptop's INPUT chain, in repeating on/off bursts.
#
# Ground truth is logged to: logs/ground_truth_s2_<timestamp>.csv
#
# Usage:
#   sudo ./inject_s2.sh --target 10.64.88.174
#   sudo ./inject_s2.sh --target 10.64.88.174 --bursts 12 --on 15 --off 45
#   sudo ./inject_s2.sh --target 10.64.88.174 --dry-run
# =============================================================================

set -euo pipefail

# ── Defaults ────────────────────────────────────────────────────────────────
TARGET_IP=""
BURST_COUNT=10       # number of injection bursts
BURST_ON=15          # seconds DNS is BLOCKED per burst
BURST_OFF=45         # seconds DNS is RESTORED between bursts
DRY_RUN=false
LOG_DIR="$(dirname "$0")/../logs"

# ── Colors ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GRN='\033[0;32m'; YLW='\033[1;33m'
CYN='\033[0;36m'; BLD='\033[1m'; RST='\033[0m'

# ── Argument parsing ─────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --target|-t)  TARGET_IP="$2";    shift 2 ;;
        --bursts|-n)  BURST_COUNT="$2";  shift 2 ;;
        --on)         BURST_ON="$2";     shift 2 ;;
        --off)        BURST_OFF="$2";    shift 2 ;;
        --dry-run)    DRY_RUN=true;      shift   ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

# ── Validation ───────────────────────────────────────────────────────────────
if [[ -z "$TARGET_IP" ]]; then
    echo -e "${RED}Error: --target <UNO_Q_IP> is required.${RST}"
    echo "  Example: sudo $0 --target 10.64.88.174"
    exit 1
fi

if [[ "$EUID" -ne 0 && "$DRY_RUN" == "false" ]]; then
    echo -e "${RED}Error: must run as root (sudo).${RST}"
    exit 1
fi

# ── Setup log directory ───────────────────────────────────────────────────────
mkdir -p "$LOG_DIR"
SESSION_TS=$(date -u +"%Y%m%dT%H%M%SZ")
GT_FILE="${LOG_DIR}/ground_truth_s2_${SESSION_TS}.csv"

# ── Ground truth logger ───────────────────────────────────────────────────────
gt_log() {
    local event="$1"
    local burst_id="$2"
    local note="${3:-}"
    local ts
    ts=$(date -u +"%Y-%m-%dT%H:%M:%S.%3NZ")
    echo "${ts},${burst_id},${event},${note}" | tee -a "$GT_FILE"
}

# ── iptables helpers ─────────────────────────────────────────────────────────
IPT_RULES_ADDED=()

ipt_add() {
    local rule="-s ${TARGET_IP} -p $1 --dport 53 -j DROP"
    if [[ "$DRY_RUN" == "true" ]]; then
        echo -e "  ${CYN}[DRY-RUN] iptables -I INPUT ${rule}${RST}"
    else
        iptables -I INPUT $rule
        IPT_RULES_ADDED+=("$1")
    fi
}

ipt_del() {
    local rule="-s ${TARGET_IP} -p $1 --dport 53 -j DROP"
    if [[ "$DRY_RUN" == "true" ]]; then
        echo -e "  ${CYN}[DRY-RUN] iptables -D INPUT ${rule}${RST}"
    else
        iptables -D INPUT $rule 2>/dev/null || true
    fi
}

# ── Cleanup on exit (Ctrl+C or error) ────────────────────────────────────────
cleanup() {
    echo ""
    echo -e "${YLW}[!] Caught exit signal — removing iptables rules...${RST}"
    ipt_del udp
    ipt_del tcp
    gt_log "SESSION_END" "N/A" "cleanup_on_exit"
    echo -e "${GRN}[✓] iptables rules removed. DNS restored.${RST}"
    echo -e "${BLD}Ground truth log: ${GT_FILE}${RST}"
    exit 0
}
trap cleanup SIGINT SIGTERM EXIT

# ── Pre-flight connectivity check ─────────────────────────────────────────────
echo -e "${BLD}${CYN}"
echo "══════════════════════════════════════════════════════"
echo "  S2 — DNS Outage Burst Injector"
echo "══════════════════════════════════════════════════════${RST}"
echo -e "  Target Uno Q IP : ${BLD}${TARGET_IP}${RST}"
echo -e "  Burst pattern   : ${BLD}${BURST_ON}s BLOCK / ${BURST_OFF}s RESTORE × ${BURST_COUNT} bursts${RST}"
echo -e "  Total duration  : ~$((( BURST_ON + BURST_OFF ) * BURST_COUNT ))s"
echo -e "  Dry run         : ${DRY_RUN}"
echo -e "  Ground truth    : ${GT_FILE}"
echo ""

# Verify target is reachable before starting
if ! ping -c1 -W2 "$TARGET_IP" &>/dev/null; then
    echo -e "${RED}[!] Warning: ${TARGET_IP} is not responding to ping.${RST}"
    echo -e "${YLW}    If Uno Q is connected, this is unusual. Continue? [y/N]${RST}"
    read -r ans
    [[ "${ans,,}" == "y" ]] || exit 1
fi

# Verify iptables is available
if [[ "$DRY_RUN" == "false" ]]; then
    command -v iptables &>/dev/null || { echo "iptables not found"; exit 1; }
fi

echo -e "${GRN}[✓] Pre-flight OK. Starting in 3 seconds...${RST}"
echo -e "    (Ctrl+C at any time to stop and restore DNS)\n"
sleep 3

# Write CSV header
echo "utc_timestamp,burst_id,event,note" > "$GT_FILE"
gt_log "SESSION_START" "0" "target=${TARGET_IP},on=${BURST_ON}s,off=${BURST_OFF}s,bursts=${BURST_COUNT}"

# ── Main injection loop ───────────────────────────────────────────────────────
for (( i=1; i<=BURST_COUNT; i++ )); do

    # ── BLOCK phase ────────────────────────────────────────────────────────
    echo -e "${RED}[BURST ${i}/${BURST_COUNT}] $(date -u '+%H:%M:%S')  BLOCKING DNS for ${BURST_ON}s...${RST}"
    gt_log "BURST_START" "$i" "blocking_dns"

    ipt_add udp
    ipt_add tcp

    sleep "$BURST_ON"

    # ── RESTORE phase ───────────────────────────────────────────────────────
    ipt_del udp
    ipt_del tcp

    gt_log "BURST_END" "$i" "dns_restored"
    echo -e "${GRN}[BURST ${i}/${BURST_COUNT}] $(date -u '+%H:%M:%S')  DNS RESTORED, gap ${BURST_OFF}s...${RST}"

    # Don't sleep after the last burst
    if (( i < BURST_COUNT )); then
        sleep "$BURST_OFF"
    fi

done

gt_log "SESSION_END" "N/A" "all_bursts_complete"
echo ""
echo -e "${BLD}${GRN}══════════════════════════════════════════════════════"
echo -e "  Injection complete — ${BURST_COUNT} bursts finished."
echo -e "  Ground truth log: ${GT_FILE}"
echo -e "══════════════════════════════════════════════════════${RST}"

# Trap will clean up on exit — IPTS already removed above via ipt_del
# Reset trap to avoid double-cleanup message
trap - EXIT
