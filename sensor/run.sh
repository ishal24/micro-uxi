#!/usr/bin/env bash
# ============================================================
#  run.sh — Micro-UXI Unified Launcher (Uno Q)
#  Starts: overhead monitor + monitoring controller
#
#  Usage:
#    ./run.sh                        # run both, indefinitely
#    ./run.sh --duration 30m         # stop both after 30 min
#    ./run.sh --no-fast              # disable fast probe
#    ./run.sh --format csv           # save output as CSV
#    ./run.sh --verbose              # print full JSON
# ============================================================

set -euo pipefail

# ── Config ────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="/opt/microuxi-venv"
OVERHEAD_DIR="$(dirname "$SCRIPT_DIR")/overhead"
OUT_DIR="$SCRIPT_DIR/out"
LOG_DIR="$OUT_DIR/logs"

# Overhead monitor settings
OVERHEAD_INTERVAL=5          # seconds between overhead samples
OVERHEAD_DEVICE_ID=""        # auto-detect from config.json if empty

# Parse args to pass through to controller
CONTROLLER_ARGS=("$@")

# ── Colour helpers ────────────────────────────────────────────
RED='\033[91m'; GRN='\033[92m'; YLW='\033[93m'
CYN='\033[96m'; GRY='\033[90m'; RST='\033[0m'
log()  { echo -e "${GRY}[$(date '+%H:%M:%S')]${RST} $*"; }
ok()   { echo -e "${GRN}[$(date '+%H:%M:%S')] ✓${RST} $*"; }
warn() { echo -e "${YLW}[$(date '+%H:%M:%S')] ⚠${RST} $*"; }
err()  { echo -e "${RED}[$(date '+%H:%M:%S')] ✗${RST} $*" >&2; }

# ── Find Python ───────────────────────────────────────────────
if [ -x "$VENV/bin/python3" ]; then
    PYTHON="$VENV/bin/python3"
elif command -v python3 &>/dev/null; then
    PYTHON="python3"
else
    err "Python3 not found. Install it or create venv at $VENV"
    exit 1
fi

ok "Python: $($PYTHON --version 2>&1)"

# ── Auto-detect device_id from config.json ────────────────────
if [ -z "$OVERHEAD_DEVICE_ID" ]; then
    CFG="$SCRIPT_DIR/config.json"
    if [ -f "$CFG" ]; then
        OVERHEAD_DEVICE_ID=$($PYTHON -c \
            "import json,sys; c=json.load(open('$CFG')); print(c.get('device',{}).get('device_id','uno-q-01'))" \
            2>/dev/null || echo "uno-q-01")
    else
        OVERHEAD_DEVICE_ID="uno-q-01"
    fi
fi

# ── Setup output dirs ─────────────────────────────────────────
mkdir -p "$OUT_DIR/payloads" "$LOG_DIR"

SESSION=$(date '+%Y%m%dT%H%M%SZ')
OVERHEAD_LOG="$LOG_DIR/overhead_${SESSION}.log"
CONTROLLER_LOG="$LOG_DIR/controller_${SESSION}.log"

# ── PID tracking ──────────────────────────────────────────────
OVERHEAD_PID=""
CONTROLLER_PID=""

cleanup() {
    echo ""
    warn "Shutting down..."
    [ -n "$OVERHEAD_PID" ]    && kill "$OVERHEAD_PID"    2>/dev/null && log "Overhead stopped (PID $OVERHEAD_PID)"
    [ -n "$CONTROLLER_PID" ]  && kill "$CONTROLLER_PID"  2>/dev/null && log "Controller stopped (PID $CONTROLLER_PID)"
    wait 2>/dev/null
    ok "All processes stopped. Logs saved to: $LOG_DIR"
    exit 0
}
trap cleanup INT TERM

# ── Banner ────────────────────────────────────────────────────
echo ""
echo "================================================================"
echo "  Micro-UXI Unified Launcher"
echo "================================================================"
echo "  Device ID   : $OVERHEAD_DEVICE_ID"
echo "  Script dir  : $SCRIPT_DIR"
echo "  Output dir  : $OUT_DIR"
echo "  Session     : $SESSION"
echo "  Python      : $PYTHON"
echo "================================================================"
echo ""

# ── Start overhead monitor ────────────────────────────────────
OVERHEAD_SCRIPT="$OVERHEAD_DIR/overhead_monitor.py"
if [ ! -f "$OVERHEAD_SCRIPT" ]; then
    warn "overhead_monitor.py not found at: $OVERHEAD_SCRIPT"
    warn "Overhead monitoring will be skipped."
else
    log "Starting overhead monitor (interval=${OVERHEAD_INTERVAL}s)..."
    $PYTHON "$OVERHEAD_SCRIPT" \
        --device-id "$OVERHEAD_DEVICE_ID" \
        --interval  "$OVERHEAD_INTERVAL"  \
        --config    "$SCRIPT_DIR/config.json" \
        >> "$OVERHEAD_LOG" 2>&1 &
    OVERHEAD_PID=$!
    ok "Overhead monitor started  (PID $OVERHEAD_PID) → $OVERHEAD_LOG"
fi

# ── Short pause so overhead registers first ───────────────────
sleep 1

# ── Start monitoring controller ───────────────────────────────
log "Starting monitoring controller..."
$PYTHON "$SCRIPT_DIR/controller.py" \
    --config "$SCRIPT_DIR/config.json" \
    "${CONTROLLER_ARGS[@]}" \
    2>&1 | tee "$CONTROLLER_LOG" &
CONTROLLER_PID=$!
ok "Controller started  (PID $CONTROLLER_PID) → $CONTROLLER_LOG"

echo ""
echo "================================================================"
echo "  Both processes running. Press Ctrl+C to stop."
echo "  Overhead log : $OVERHEAD_LOG"
echo "  Monitor log  : $CONTROLLER_LOG"
echo "================================================================"
echo ""

# ── Wait for controller (it exits on --duration) ──────────────
wait $CONTROLLER_PID
log "Controller finished."
cleanup
