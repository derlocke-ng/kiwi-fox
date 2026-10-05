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
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/$APP"

if [[ "$KIWI_SCOPE" != user ]]; then
    echo "install.sh: $APP is user-scope only; nothing to do for scope '$KIWI_SCOPE'"
    exit 0
fi

do_install() {
    mkdir -p "$LIBDIR" "$KIWI_PREFIX/bin"
    rm -rf "$LIBDIR/kiwi_fox" "$LIBDIR/containers"
    cp -r "$SRC/src/kiwi_fox" "$LIBDIR/kiwi_fox"
    cp -r "$SRC/containers" "$LIBDIR/containers"

    cat > "$KIWI_PREFIX/bin/$APP" <<EOF
#!/usr/bin/env bash
export PYTHONPATH="$LIBDIR\${PYTHONPATH:+:\$PYTHONPATH}"
exec python3 -m kiwi_fox "\$@"
EOF
    chmod +x "$KIWI_PREFIX/bin/$APP"

    if [[ "${KIWI_GUI:-1}" == 1 ]]; then
        cat > "$KIWI_PREFIX/bin/$APP-gui" <<EOF
#!/usr/bin/env bash
export PYTHONPATH="$LIBDIR\${PYTHONPATH:+:\$PYTHONPATH}"
exec python3 -m kiwi_fox.ui "\$@"
EOF
        chmod +x "$KIWI_PREFIX/bin/$APP-gui"
        install -Dm644 "$SRC/data/$APP.desktop" \
            "$KIWI_PREFIX/share/applications/$APP.desktop" 2>/dev/null || true
        install -Dm644 "$SRC/data/$APP.svg" \
            "$KIWI_PREFIX/share/icons/hicolor/scalable/apps/$APP.svg" 2>/dev/null || true
    fi

    # Blocklist refresh. Images and the engine are NOT built or downloaded here:
    # that is slow, needs network at the wrong moment, and belongs to first run.
    local unitdir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
    mkdir -p "$unitdir"
    cat > "$unitdir/$APP-blocklists.service" <<EOF
[Unit]
Description=Refresh kiwi-fox DNS blocklists
[Service]
Type=oneshot
ExecStart=$KIWI_PREFIX/bin/$APP dns update
EOF
    cat > "$unitdir/$APP-blocklists.timer" <<EOF
[Unit]
Description=Refresh kiwi-fox DNS blocklists daily
[Timer]
OnCalendar=daily
Persistent=true
RandomizedDelaySec=2h
[Install]
WantedBy=timers.target
EOF
    systemctl --user daemon-reload 2>/dev/null || true
    systemctl --user enable --now "$APP-blocklists.timer" 2>/dev/null || true

    echo "installed $APP to $KIWI_PREFIX"
    echo
    echo "First run needs one command — it builds the container images, downloads the"
    echo "browser engine and fetches the blocklists:"
    echo
    echo "    $APP setup"
    echo
    echo "Then create an identity:  $APP new work socks5://host:port"
}

do_update() { do_install; }

do_uninstall() {
    systemctl --user disable --now "$APP-blocklists.timer" 2>/dev/null || true
    rm -f "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/$APP-blocklists."{service,timer}
    systemctl --user daemon-reload 2>/dev/null || true
    rm -f "$KIWI_PREFIX/bin/$APP" "$KIWI_PREFIX/bin/$APP-gui"
    rm -f "$KIWI_PREFIX/share/applications/$APP.desktop"
    rm -f "$KIWI_PREFIX/share/icons/hicolor/scalable/apps/$APP.svg"
    rm -rf "$LIBDIR"

    # An ordinary uninstall leaves profiles, fingerprints and the provider cache
    # alone, so reinstalling resumes where you left off. --purge deletes
    # identities that cannot be regenerated.
    if [[ "${KIWI_PURGE:-0}" == 1 || "${2:-}" == --purge ]]; then
        echo "purging $DATA — profiles and their identities are being deleted"
        "$KIWI_PREFIX/bin/$APP" stop 2>/dev/null || true
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
