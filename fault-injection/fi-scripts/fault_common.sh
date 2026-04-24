#!/usr/bin/env bash
# =============================================================================
# fault_common.sh
#
# Helper functions + variabel default untuk semua script fault injection.
#
# Sistem ini menggunakan nftables secara native. Semua DNS rules memakai
# perintah `nft` langsung (bukan iptables) karena iptables-nft rules
# dieksekusi SETELAH native nft ACCEPT rules → DROP tidak akan efektif.
# =============================================================================

# Interface hotspot/AP tempat Uno terhubung
HOTSPOT_IF="${HOTSPOT_IF:-ap0}"

# Interface upstream/internet
UPSTREAM_IF="${UPSTREAM_IF:-wlxd037456b1bc8}"

# Subnet Uno Q
CLIENT_SUBNET="${CLIENT_SUBNET:-192.168.12.0/24}"

# ----------------------------- helper umum -----------------------------------

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    echo "[ERROR] Jalankan script ini pakai sudo/root."
    exit 1
  fi
}

show_interfaces() {
  echo "[INFO] HOTSPOT_IF    = ${HOTSPOT_IF}"
  echo "[INFO] UPSTREAM_IF   = ${UPSTREAM_IF}"
  echo "[INFO] CLIENT_SUBNET = ${CLIENT_SUBNET}"
}

check_interface_exists() {
  local dev="$1"
  if ! ip link show "$dev" > /dev/null 2>&1; then
    echo "[ERROR] Interface '$dev' tidak ditemukan."
    exit 1
  fi
}

remove_tc_root_if_exists() {
  local dev="$1"
  tc qdisc del dev "$dev" root > /dev/null 2>&1 || true
}

# ── helper: nft DNS outage (native nft, bukan iptables) ──────────────────────
# Memakai tabel tersendiri `fi_fault` supaya mudah di-flush dan tidak
# bentrok dengan tabel native hotspot (table ip filter).

_nft_fi_table_exists() {
  nft list table ip fi_fault > /dev/null 2>&1
}

create_dns_outage_chain_if_needed() {
  # Buat tabel fi_fault kalau belum ada.
  if ! _nft_fi_table_exists; then
    nft add table ip fi_fault
  fi

  # Buat chain FI_FORWARD yang nge-hook ke forward, priority -1
  # (dieksekusi SEBELUM chain native di priority 0).
  nft add chain ip fi_fault FI_FORWARD \
    '{ type filter hook forward priority -1; policy accept; }' 2>/dev/null || true

  # Flush isi chain supaya konsisten.
  nft flush chain ip fi_fault FI_FORWARD
}

attach_dns_outage_chain() {
  # Tambah rule DROP DNS (UDP+TCP port 53) dari client hotspot.
  nft add rule ip fi_fault FI_FORWARD \
    iifname "${HOTSPOT_IF}" ip saddr "${CLIENT_SUBNET}" udp dport 53 drop
  nft add rule ip fi_fault FI_FORWARD \
    iifname "${HOTSPOT_IF}" ip saddr "${CLIENT_SUBNET}" tcp dport 53 drop
  echo "[INFO] nft DNS outage rules aktif (priority -1, sebelum native chains)."
  nft list chain ip fi_fault FI_FORWARD
}

detach_dns_outage_chain() {
  # Flush rules tapi biarkan chain-nya.
  nft flush chain ip fi_fault FI_FORWARD 2>/dev/null || true
}

destroy_dns_outage_chain() {
  # Hapus seluruh tabel fi_fault (termasuk semua chain dan rules).
  nft delete table ip fi_fault 2>/dev/null || true
}

# ── helper: nft DNS mark (untuk DNS delay / RTT fault) ───────────────────────

create_dns_mark_chain_if_needed() {
  if ! _nft_fi_table_exists; then
    nft add table ip fi_fault
  fi

  # Chain di hook mangle prerouting, priority -150 (sebelum native mangle).
  nft add chain ip fi_fault FI_MANGLE \
    '{ type filter hook prerouting priority -150; policy accept; }' 2>/dev/null || true

  nft flush chain ip fi_fault FI_MANGLE
}

attach_dns_mark_chain() {
  # Tandai trafik DNS dari client hotspot dengan mark 53.
  nft add rule ip fi_fault FI_MANGLE \
    iifname "${HOTSPOT_IF}" ip saddr "${CLIENT_SUBNET}" udp dport 53 meta mark set 53
  nft add rule ip fi_fault FI_MANGLE \
    iifname "${HOTSPOT_IF}" ip saddr "${CLIENT_SUBNET}" tcp dport 53 meta mark set 53
  echo "[INFO] nft DNS mark rules aktif (mark=53 untuk DNS dari ${HOTSPOT_IF})."
  nft list chain ip fi_fault FI_MANGLE
}

detach_dns_mark_chain() {
  nft flush chain ip fi_fault FI_MANGLE 2>/dev/null || true
}

destroy_dns_mark_chain() {
  # Kalau outage chain sudah tidak ada di tabel, hapus seluruh tabel.
  # Kalau masih ada chain lain, cukup hapus FI_MANGLE.
  nft delete chain ip fi_fault FI_MANGLE 2>/dev/null || true
}

# ------------------------------- rollback ------------------------------------

rollback_dns_rules() {
  # Hapus seluruh tabel fi_fault (paling bersih).
  nft delete table ip fi_fault 2>/dev/null || true
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
