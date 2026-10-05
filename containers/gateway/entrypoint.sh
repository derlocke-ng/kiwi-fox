#!/usr/bin/env bash
# kiwi-fox gateway — build a network namespace whose only exit is this profile's
# SOCKS5 endpoint, then hold it open for the browser container to join.
#
# The browser joins with --network container:<this> and so has no network
# namespace, no routing table and no interfaces of its own. If this container
# dies the profile loses connectivity: the kill switch is the absence of a
# route, not software that has to notice.
set -euo pipefail

: "${KF_ENDPOINT_IP:?KF_ENDPOINT_IP is required}"
: "${KF_ENDPOINT_PORT:?KF_ENDPOINT_PORT is required}"
KF_FORWARDER_PORT="${KF_FORWARDER_PORT:-1080}"
KF_DNS_MODE="${KF_DNS_MODE:-resolver}"
RESOLVER_CFG=/run/kf/dnscrypt-proxy.toml

log() { printf 'gateway: %s\n' "$*"; }
die() { printf 'gateway: FATAL: %s\n' "$*" >&2; exit 1; }

case "$KF_ENDPOINT_IP" in
  *[a-zA-Z]*) die "endpoint must be a literal address (resolution happens on the host)";;
esac

# ---------------------------------------------------------------- firewall
# Rules key on destination, not on sending uid: a uid-matched exemption breaks
# silently if a relay drops privileges differently than expected.
log "firewall: default drop, permitting only ${KF_ENDPOINT_IP}:${KF_ENDPOINT_PORT}"
nft -f - <<EOF
flush ruleset

table inet kiwifox {
  chain output {
    type filter hook output priority filter; policy drop;

    ct state established,related accept
    oif "lo" accept

    # The one permitted destination.
    ip daddr ${KF_ENDPOINT_IP} tcp dport ${KF_ENDPOINT_PORT} accept

    # Everything else is dropped: no direct TCP, no UDP (so no QUIC and no
    # WebRTC media), no plaintext DNS, no ICMP, no IPv6.
    counter comment "kf-dropped"
  }

  chain input {
    type filter hook input priority filter; policy drop;
    ct state established,related accept
    iif "lo" accept
  }
}
EOF

# --------------------------------------------------------------- forwarder
log "forwarder: starting on 127.0.0.1:${KF_FORWARDER_PORT}"
python3 /usr/local/bin/kf-forwarder &
FORWARDER_PID=$!

# The gate must not open before the relay accepts connections, or there is a
# window where traffic is redirected into a dead port.
ready=false
for _ in $(seq 1 100); do
    kill -0 "$FORWARDER_PID" 2>/dev/null || die "forwarder exited during startup"
    if (exec 3<>"/dev/tcp/127.0.0.1/${KF_FORWARDER_PORT}") 2>/dev/null; then
        ready=true; break
    fi
    sleep 0.1
done
[ "$ready" = true ] || die "forwarder never listened on :${KF_FORWARDER_PORT}"
log "forwarder: listening"

# ---------------------------------------------------------------- resolver
RESOLVER_PID=""
if [ "$KF_DNS_MODE" = resolver ]; then
    [ -f "$RESOLVER_CFG" ] || die "resolver mode but $RESOLVER_CFG is missing"
    log "resolver: dnscrypt-proxy on 127.0.0.2:53, upstream DoH through the forwarder"
    dnscrypt-proxy -config "$RESOLVER_CFG" &
    RESOLVER_PID=$!
    for _ in $(seq 1 100); do
        kill -0 "$RESOLVER_PID" 2>/dev/null || die "dnscrypt-proxy exited during startup"
        if getent hosts -s dns example.com >/dev/null 2>&1; then break; fi
        sleep 0.2
    done
    log "resolver: up"
else
    log "resolver: disabled (remote DNS at the proxy)"
fi

cleanup() {
    log "shutting down"
    [ -n "$RESOLVER_PID" ] && kill "$RESOLVER_PID" 2>/dev/null || true
    kill "$FORWARDER_PID" 2>/dev/null || true
    wait 2>/dev/null || true
    exit 0
}
trap cleanup SIGTERM SIGINT

log "ready — the namespace is sealed"

# Hold the namespace open, and die if either service dies so the browser loses
# its route rather than silently running without one.
while true; do
    sleep 5
    kill -0 "$FORWARDER_PID" 2>/dev/null || die "forwarder died"
    if [ -n "$RESOLVER_PID" ]; then
        kill -0 "$RESOLVER_PID" 2>/dev/null || die "resolver died"
    fi
done
