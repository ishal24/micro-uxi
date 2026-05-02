#!/usr/bin/env bash
# ============================================================
#  run.sh — Micro-UXI Unified Launcher (Uno Q)
#  Starts: overhead monitor + monitoring controller
#
#  Default behaviour: stream-only, no files written.
#
#  Usage:
#    ./run.sh                        # stream only, no files (default)
#    ./run.sh --save                 # enable file output to ./out/
#    ./run.sh --duration 30m         # stop both after 30 min
#    ./run.sh --no-fast              # disable fast probe
#    ./run.sh --format csv           # save as CSV (requires --save)
#    ./run.sh --verbose              # print full JSON
# ============================================================

set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="/opt/microuxi-venv"
OVERHEAD_DIR="$(dirname "$SCRIPT_DIR")/overhead"
OUT_DIR="$SCRIPT_DIR/out"
LOG_DIR="$OUT_DIR/logs"
OVERHEAD_INTERVAL=5
OVERHEAD_DEVICE_ID=""

# ── Parse own flags; forward the rest to controller ───────────
SAVE_OUTPUT=false
CONTROLLER_ARGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --save)          SAVE_OUTPUT=true;  shift ;;
        *)               CONTROLLER_ARGS+=("$1"); shift ;;
    esac
done
# Stream-only by default
if [[ "$SAVE_OUTPUT" == "false" ]]; then
    CONTROLLER_ARGS+=("--no-output")
fi

# ── Colour helpers ────────────────────────────────────────────
RED='\033[91m'; GRN='\033[92m'; YLW='\033[93m'
RST='\033[0m'  ; GRY='\033[90m'
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
    err "Python3 not found."
    exit 1
fi

# ── Auto-detect device_id ─────────────────────────────────────
CFG="$SCRIPT_DIR/config.json"
if [ -f "$CFG" ]; then
    OVERHEAD_DEVICE_ID=$($PYTHON -c \
        "import json; c=json.load(open('$CFG')); print(c.get('device',{}).get('device_id','uno-q-01'))" \
        2>/dev/null || echo "uno-q-01")
else
    OVERHEAD_DEVICE_ID="uno-q-01"
fi

# ── Output dirs (only needed when --save) ────────────────────
if [[ "$SAVE_OUTPUT" == "true" ]]; then
    mkdir -p "$OUT_DIR/payloads" "$LOG_DIR"
    SESSION=$(date '+%Y%m%dT%H%M%SZ')
    OVERHEAD_LOG="$LOG_DIR/overhead_${SESSION}.log"
    CONTROLLER_LOG="$LOG_DIR/controller_${SESSION}.log"
fi

# ── Signal handling — run cleanup only ONCE ───────────────────
_CLEANING=false

cleanup() {
    # Guard: only execute once regardless of how many signals arrive
    [[ "$_CLEANING" == "true" ]] && return 0
    _CLEANING=true

    echo ""
    warn "Shutting down..."

    # Kill entire process group of this shell script.
    # This also kills the overhead monitor, controller, and any
    # subprocesses they spawned — no matter how deeply nested.
    kill -TERM -- -$$ 2>/dev/null || true

    # Give processes up to 5 s to exit gracefully
    local i=0
    while kill -0 -- -$$ 2>/dev/null && (( i < 10 )); do
        sleep 0.5
        (( i++ ))
    done

    # Force-kill anything still alive
    kill -KILL -- -$$ 2>/dev/null || true

    ok "Shutdown complete."
    # Exit cleanly — use exit code 0 so the shell doesn't print "Killed"
    trap - EXIT
    exit 0
}

# Catch Ctrl+C (INT), TERM, and EXIT (so --duration auto-exit also cleans up)
trap cleanup INT TERM EXIT

# ── Banner ────────────────────────────────────────────────────
echo ""
echo "================================================================"
echo "  Micro-UXI Unified Launcher"
echo "================================================================"
echo "  Device ID   : $OVERHEAD_DEVICE_ID"
echo "  Python      : $($PYTHON --version 2>&1)"
echo "  File output : $([[ "$SAVE_OUTPUT" == "true" ]] && echo "ON → $OUT_DIR" || echo "OFF (stream only)")"
echo "================================================================"
echo ""

# ── Start overhead monitor in background ─────────────────────
OVERHEAD_SCRIPT="$OVERHEAD_DIR/overhead_monitor.py"
if [ ! -f "$OVERHEAD_SCRIPT" ]; then
    warn "overhead_monitor.py not found at: $OVERHEAD_SCRIPT — skipping."
else
    OVERHEAD_CMD="$PYTHON $OVERHEAD_SCRIPT --device-id $OVERHEAD_DEVICE_ID --interval $OVERHEAD_INTERVAL --config $CFG"
    if [[ "$SAVE_OUTPUT" == "true" ]]; then
        $OVERHEAD_CMD >> "$OVERHEAD_LOG" 2>&1 &
        ok "Overhead started (PID $!) → $OVERHEAD_LOG"
    else
        # Redirect to /dev/null so overhead doesn't mix with controller stdout
        $OVERHEAD_CMD > /dev/null 2>&1 &
        ok "Overhead started (PID $!)"
    fi
fi

# Small stagger so overhead registers a heartbeat first
sleep 1

# ── Start controller in foreground ───────────────────────────
# Running in foreground means Ctrl+C reaches it directly AND
# its stdout streams to the terminal without any tee complications.
log "Starting monitoring controller..."
echo ""

if [[ "$SAVE_OUTPUT" == "true" ]]; then
    # tee so output both goes to terminal AND log file
    $PYTHON "$SCRIPT_DIR/controller.py" \
        --config "$CFG" \
        "${CONTROLLER_ARGS[@]}" 2>&1 | tee "$CONTROLLER_LOG"
else
    # Pure foreground — no extra pipes, cleanest possible Ctrl+C
    exec $PYTHON "$SCRIPT_DIR/controller.py" \
        --config "$CFG" \
        "${CONTROLLER_ARGS[@]}"
fi

# exec replaces the shell process, so cleanup runs via EXIT trap when
# the controller exits naturally (e.g. after --duration).
