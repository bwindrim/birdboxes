#!/bin/bash
# SPDX-License-Identifier: GPL-2.0
#
# Copyright (C) 2015-2020 Jason A. Donenfeld <Jason@zx2c4.com>. All Rights Reserved.
# Extended to maintain endpoint host route strictly via ppp0

set -e
shopt -s nocasematch
shopt -s extglob
export LC_ALL=C

CONFIG_FILE="$1"
[[ $CONFIG_FILE =~ ^[a-zA-Z0-9_=+.-]{1,15}$ ]] && CONFIG_FILE="/etc/wireguard/$CONFIG_FILE.conf"
[[ $CONFIG_FILE =~ /?([a-zA-Z0-9_=+.-]{1,15})\.conf$ ]]
INTERFACE="${BASH_REMATCH[1]}"

LTE_IF="ppp0"

process_peer() {
    [[ $PEER_SECTION -ne 1 || -z $PUBLIC_KEY || -z $ENDPOINT ]] && return 0

    HOST="${ENDPOINT%:*}"
    PORT="${ENDPOINT##*:}"

    NEW_IP=$(getent ahostsv4 "$HOST" | awk '{print $1; exit}')
    [[ -z "$NEW_IP" ]] && return 0

    CURRENT_ENDPOINT=$(wg show "$INTERFACE" endpoints | awk -v key="$PUBLIC_KEY" '$1==key {print $2}')
    CURRENT_IP="${CURRENT_ENDPOINT%:*}"

    # Respect original handshake timeout logic
    if [[ $(wg show "$INTERFACE" latest-handshakes) =~ ${PUBLIC_KEY//+/\\+}\ ([0-9]+) ]]; then
        LAST_HANDSHAKE=${BASH_REMATCH[1]}
        (( ($(date +%s) - LAST_HANDSHAKE) < 135 )) && return 0
    fi

    if [[ "$NEW_IP" != "$CURRENT_IP" ]]; then
        echo "Updating endpoint for $PUBLIC_KEY to $NEW_IP:$PORT"

        # Update WireGuard endpoint
        wg set "$INTERFACE" peer "$PUBLIC_KEY" endpoint "$NEW_IP:$PORT"

        # Remove old host route if present
        if [[ -n "$CURRENT_IP" ]]; then
            ip route del "$CURRENT_IP" dev "$LTE_IF" 2>/dev/null || true
        fi

        # Add/replace route strictly via LTE
        ip route replace "$NEW_IP" dev "$LTE_IF"
    fi

    reset_peer_section
}

reset_peer_section() {
    PEER_SECTION=0
    PUBLIC_KEY=""
    ENDPOINT=""
}

reset_peer_section
while read -r line || [[ -n $line ]]; do
    stripped="${line%%\#*}"
    key="${stripped%%=*}"; key="${key##*([[:space:]])}"; key="${key%%*([[:space:]])}"
    value="${stripped#*=}"; value="${value##*([[:space:]])}"; value="${value%%*([[:space:]])}"
    [[ $key == "["* ]] && { process_peer; reset_peer_section; }
    [[ $key == "[Peer]" ]] && PEER_SECTION=1
    if [[ $PEER_SECTION -eq 1 ]]; then
        case "$key" in
            PublicKey) PUBLIC_KEY="$value"; continue ;;
                Endpoint) ENDPOINT="$value"; continue ;;
        esac
    fi
done < "$CONFIG_FILE"
process_peer


