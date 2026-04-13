#!/bin/bash
# ============================================================
# Micro-UXI — Minimal Tool Installation (Lightweight)
# Target: Arduino Uno Q (Debian, 2 GB RAM)
# ============================================================

set -e

echo "=== Micro-UXI Minimal Setup ==="

if [[ $EUID -ne 0 ]]; then
    echo "Run with sudo"
    exit 1
fi

echo "[1] Update system"
apt-get update -y
apt-get upgrade -y

echo "[2] Install core utilities"
apt-get install -y \
    curl \
    wget \
    jq \
    bc \
    iproute2 \
    net-tools \
    procps

echo "[3] Install network tools (ESSENTIAL ONLY)"
apt-get install -y \
    iputils-ping \
    traceroute \
    dnsutils \
    netcat-openbsd

echo "[4] Install WiFi tools"
apt-get install -y \
    iw \
    wireless-tools \
    wpasupplicant

echo "[5] Install HTTP tools"
apt-get install -y \
    curl

echo "[6] Install system monitoring (lightweight)"
apt-get install -y \
    sysstat

echo "[7] Enable sysstat"
sed -i 's/ENABLED="false"/ENABLED="true"/' /etc/default/sysstat || true
systemctl restart sysstat || true

echo "[8] Install Python + dependencies"
apt-get install -y python3 python3-pip python3-venv

echo "[9] Setup Python virtual environment"
python3 -m venv /opt/microuxi-venv
source /opt/microuxi-venv/bin/activate

pip install --upgrade pip
pip install psutil dnspython

echo "=== DONE ==="
