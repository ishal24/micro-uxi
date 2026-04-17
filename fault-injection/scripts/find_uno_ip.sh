#!/usr/bin/env bash
# =============================================================================
# find_uno_ip.sh — Discover the Uno Q's IP on the hotspot subnet
# Usage: ./find_uno_ip.sh [subnet, default: 10.64.88.0/24]
# =============================================================================
SUBNET="${1:-10.64.88.0/24}"

echo "Scanning ${SUBNET} for connected devices..."
echo "(Requires nmap — apt install nmap)"
echo ""

# Method 1: nmap ping scan
if command -v nmap &>/dev/null; then
    echo "=== nmap scan ==="
    nmap -sn "$SUBNET" 2>/dev/null | grep -E "Nmap scan|MAC|latency"
fi

echo ""
echo "=== ARP table ==="
arp -n 2>/dev/null | grep -v "incomplete"

echo ""
echo "=== DHCP leases (NetworkManager) ==="
# NetworkManager dnsmasq leases
for f in /var/lib/NetworkManager/*.lease \
          /var/lib/NetworkManager/dnsmasq-*.conf \
          /var/lib/misc/dnsmasq.leases \
          /run/dnsmasq/*.leases; do
    [[ -f "$f" ]] && echo "--- $f ---" && cat "$f"
done

echo ""
echo "Tip: The Uno Q hostname or MAC may appear in the lease.  "
echo "     Once found, pass the IP to inject_s2.sh with --target <IP>"
