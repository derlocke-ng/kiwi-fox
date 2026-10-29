#!/usr/bin/env bash
# install.sh — kiwi-fox, installed by `kiwi` (see kiwi.manifest)
#
# User scope only: rootless podman needs no root, so a plain user install is
# fully functional and nothing outside $HOME is ever written.
#
#   KIWI_SCOPE  user        KIWI_PREFIX  ~/.local
#   KIWI_ACTION install|update|uninstall
#   KIWI_GUI    0 on a headless machine
#   KIWI_PURGE  1 only when the user asked for --purge
set -euo pipefail

KIWI_SCOPE="${KIWI_SCOPE:-user}"
KIWI_PREFIX="${KIWI_PREFIX:-$HOME/.local}"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP=kiwi-fox
LIBDIR="$KIWI_PREFIX/lib/$APP"
# The proxy engine: gateways, providers, DNS. A separate kiwi app (DEPENDS),
# whose package the launchers put on the path.
PROXY_LIB="$KIWI_PREFIX/lib/kiwi-proxy"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/$APP"
UNITDIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

if [[ "$KIWI_SCOPE" != user ]]; then
    echo "install.sh: $APP is user-scope only; nothing to do for scope '$KIWI_SCOPE'"
    exit 0
fi

# The launcher's icon is replaced on update (it comes from kiwi-icons), and an
# icon-theme.cache that predates it keeps the old one in the app grid until the
# cache is rebuilt — the same refresh kiwi-updater does for its own icon.
# kiwi-fox refreshed DNS blocklists itself until 0.3.0; kiwi-proxy's timer
# does it now, so the old units go.
retire_blocklist_timer() {
    [[ -e "$UNITDIR/$APP-blocklists.timer" || -e "$UNITDIR/$APP-blocklists.service" ]] || return 0
    systemctl --user disable --now "$APP-blocklists.timer" 2>/dev/null || true
    rm -f "$UNITDIR/$APP-blocklists."{service,timer}
    systemctl --user daemon-reload 2>/dev/null || true
}

refresh_desktop_caches() {
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -qtf "$KIWI_PREFIX/share/icons/hicolor" 2>/dev/null || true
    fi
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database -q "$KIWI_PREFIX/share/applications" 2>/dev/null || true
    fi
}

do_install() {
    mkdir -p "$LIBDIR" "$KIWI_PREFIX/bin"
    rm -rf "$LIBDIR/kiwi_fox" "$LIBDIR/containers"
    cp -r "$SRC/src/kiwi_fox" "$LIBDIR/kiwi_fox"
    cp -r "$SRC/containers" "$LIBDIR/containers"

    cat > "$KIWI_PREFIX/bin/$APP" <<EOF
#!/usr/bin/env bash
export PYTHONPATH="$LIBDIR:$PROXY_LIB\${PYTHONPATH:+:\$PYTHONPATH}"
exec python3 -m kiwi_fox "\$@"
EOF
    chmod +x "$KIWI_PREFIX/bin/$APP"

    if [[ "${KIWI_GUI:-1}" == 1 ]]; then
        cat > "$KIWI_PREFIX/bin/$APP-gui" <<EOF
#!/usr/bin/env bash
export PYTHONPATH="$LIBDIR:$PROXY_LIB\${PYTHONPATH:+:\$PYTHONPATH}"
exec python3 -m kiwi_fox.ui "\$@"
EOF
        chmod +x "$KIWI_PREFIX/bin/$APP-gui"
        install -Dm644 "$SRC/data/$APP.desktop" \
            "$KIWI_PREFIX/share/applications/$APP.desktop" 2>/dev/null || true
        install -Dm644 "$SRC/data/$APP.svg" \
            "$KIWI_PREFIX/share/icons/hicolor/scalable/apps/$APP.svg" 2>/dev/null || true
        refresh_desktop_caches
    fi

    # Images and the engine are NOT built or downloaded here: that is slow,
    # needs network at the wrong moment, and belongs to first run.
    retire_blocklist_timer

    if [[ ! -f "$PROXY_LIB/kiwi_proxy/gateway.py" ]]; then
        echo "note: kiwi-proxy is not installed at $PROXY_LIB — $APP needs it:"
        echo "    kiwi install kiwi-proxy"
    fi

    echo "installed $APP to $KIWI_PREFIX"
    echo
    echo "First run:  $APP setup"
    echo "  the browser image and Camoufox (~630 MB), then kiwi-proxy's setup: the"
    echo "  gateway image, DNS data and the images of any provider modules"
    echo
    if [[ "${KIWI_GUI:-1}" == 1 ]]; then
        echo "Then create a profile in Kiwi-Fox (app grid, or $APP-gui), or here:"
    else
        echo "Then create a profile:"
    fi
    echo "  $APP new work socks5://user:pass@host:port       Camoufox, a Windows 11 identity"
    echo "  $APP new work --module tor --country de          through a provider module"
    echo "  $APP new plain HOST:PORT --engine firefox        stock Firefox"
    echo "  $APP new anon --engine torbrowser --module tor   Tor Browser"
    echo
    echo "Firefox / Tor Browser:  $APP engine fetch --engine firefox   (or torbrowser)"
    echo "Provider modules:       kiwi install kiwi-plugin-tor   (or -vpn, -9proxy, -myst)"
}

do_update() { do_install; }

# The network half of every identity: the exits kiwi-fox registered in
# kiwi-proxy, and their gateways. Only with --purge, with the identities.
purge_exits() {
    [[ -f "$PROXY_LIB/kiwi_proxy/exits.py" ]] || return 0
    PYTHONPATH="$PROXY_LIB" python3 - <<'EOF' || true
from kiwi_proxy import exits, gateway

for ex in exits.list_exits():
    if ex.owner == "kiwi-fox":
        gateway.down(ex.id)
        exits.delete(ex.id)
EOF
}

do_uninstall() {
    local purge=0
    [[ "${KIWI_PURGE:-0}" == 1 || "${2:-}" == --purge ]] && purge=1
    # While the command still exists: close every window, release its gateway.
    "$KIWI_PREFIX/bin/$APP" stop >/dev/null 2>&1 || true
    retire_blocklist_timer
    rm -f "$KIWI_PREFIX/bin/$APP" "$KIWI_PREFIX/bin/$APP-gui"
    rm -f "$KIWI_PREFIX/share/applications/$APP.desktop"
    rm -f "$KIWI_PREFIX/share/icons/hicolor/scalable/apps/$APP.svg"
    refresh_desktop_caches
    rm -rf "$LIBDIR"

    # An ordinary uninstall leaves profiles, fingerprints and their exits alone,
    # so reinstalling resumes where you left off. --purge deletes identities
    # that cannot be regenerated.
    if (( purge )); then
        echo "purging $DATA — profiles and their identities are being deleted"
        purge_exits
        rm -rf "$DATA"
    else
        echo "kept $DATA (pass --purge to remove profiles and identities)"
    fi
    echo "uninstalled $APP"
}

case "${1:-install}" in
    install)   do_install ;;
    update)    do_update ;;
    uninstall) do_uninstall "$@" ;;
    *) echo "usage: $0 install|update|uninstall [--purge]" >&2; exit 1 ;;
esac
