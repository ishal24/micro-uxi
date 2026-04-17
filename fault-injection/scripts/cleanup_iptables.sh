#!/usr/bin/env bash
# =============================================================================
# cleanup_iptables.sh — Remove ALL S2 iptables rules for a given target IP
# Run this if inject_s2.sh was killed without cleanup
# Usage: sudo ./cleanup_iptables.sh --target 10.64.88.174
# =============================================================================
TARGET_IP="${2:-}"
[[ "$1" == "--target" ]] && TARGET_IP="$2"
[[ -z "$TARGET_IP" ]] && { echo "Usage: sudo $0 --target <IP>"; exit 1; }

echo "Removing all DROP rules for $TARGET_IP on port 53..."
for proto in udp tcp; do
    while iptables -D INPUT -s "$TARGET_IP" -p "$proto" --dport 53 -j DROP 2>/dev/null; do
        echo "  Removed: INPUT $proto port 53 DROP for $TARGET_IP"
    done
done
echo "Done. DNS should be restored."
