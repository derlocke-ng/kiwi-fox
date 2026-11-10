#!/usr/bin/env bash
# kiwi-fox browser — process 1 of a profile's container: starts the engine
# headfully, with it mounted read-only and the profile mounted read-write. The
# engine and its binary name are passed in: camoufox (the default, so an older
# gateway env still works), firefox, or a Tor Browser binary.
#
# No Playwright, no juggler, no automation channel: Camoufox's spoofing arrives
# through the CAMOU_CONFIG_* environment this container was started with, and
# every engine's prefs through the profile's user.js.
#
# Kiwi Fox mounts this file over the image's own copy, so a change to it needs no
# image rebuild. With KF_CONTROL (a folder shared with the host) it supervises:
#   - the browser starts at once when KF_START_BROWSER=1, and on SIGUSR1;
#     a file "url" in KF_CONTROL, when present, gives the pages it opens with
#   - SIGUSR2 quits the browser; SIGTERM quits it and ends the container
#   - KF_CONTROL/browser says "open PID" or "closed CODE" for the host to read
#   - when the browser ends, so does the container, unless KF_CONTROL/keep exists
# Without KF_CONTROL the engine replaces this script, as before.
set -euo pipefail

ENGINE="${KF_ENGINE_DIR:-/opt/camoufox}"
BIN="${KF_ENGINE_BIN:-camoufox}"
PROFILE="${KF_PROFILE_DIR:-/profile}"

[ -x "$ENGINE/$BIN" ] || { echo "browser: no engine binary at $ENGINE/$BIN" >&2; exit 2; }

# Firefox wants a profile directory that is absolute and already exists, or it
# shows "profile cannot be loaded, missing or inaccessible" and never starts.
mkdir -p "$PROFILE" "$PROFILE/tmp" "$PROFILE/.cache"

export HOME="$PROFILE"
export TMPDIR="$PROFILE/tmp"
export XDG_CACHE_HOME="$PROFILE/.cache"
export MOZ_ENABLE_WAYLAND="${MOZ_ENABLE_WAYLAND:-1}"

# Firefox learns about the GPU from a helper it spawns from its own directory:
# `gfxtest` from 156 on, `glxtest` before. Without one it draws in software. A
# stub would be worse than nothing — Firefox would believe the probe ran and
# found no GPU.
if [ ! -x "$ENGINE/gfxtest" ] && [ ! -x "$ENGINE/glxtest" ]; then
    echo "browser: no GPU probe helper in the engine — drawing falls back to software" >&2
fi

# Tor Browser ships its own fonts and fontconfig and expects to run from its
# Browser/ directory, the way start-tor-browser sets it up. Wire that without
# start-tor-browser (which would try to write into the read-only bundle).
if [ -n "${KF_TORBROWSER:-}" ]; then
    tb_fc="$ENGINE/Browser/TorBrowser/Data/fontconfig"
    if [ -f "$tb_fc/fonts.conf" ]; then
        export FONTCONFIG_PATH="$tb_fc"
        export FONTCONFIG_FILE="$tb_fc/fonts.conf"
    fi
    cd "$ENGINE/Browser" || { echo "browser: no Browser dir at $ENGINE" >&2; exit 2; }
fi

CONTROL="${KF_CONTROL:-}"
if [ -z "$CONTROL" ]; then
    echo "browser: launching $BIN for profile $PROFILE"
    exec "$ENGINE/$BIN" \
        -profile "$PROFILE" \
        -no-remote \
        "$@"
fi

# ------------------------------------------------------------------ supervise
set +e
mkdir -p "$CONTROL"
BASE_ARGS=("$@")
child=""
ending=0
wanted=0

say() { printf '%s\n' "$*" > "$CONTROL/browser.new" && mv -f "$CONTROL/browser.new" "$CONTROL/browser"; }

start_browser() {
    [ -n "$child" ] && return 0
    local extra=()
    if [ -f "$CONTROL/url" ]; then
        mapfile -t extra < "$CONTROL/url"
        rm -f "$CONTROL/url"
    fi
    # No other browser can be running in this container: a lock left by one that
    # crashed would only make Firefox refuse the profile.
    rm -f "$PROFILE/lock" "$PROFILE/.parentlock"
    echo "browser: launching $BIN for profile $PROFILE"
    "$ENGINE/$BIN" -profile "$PROFILE" -no-remote "${BASE_ARGS[@]}" "${extra[@]}" &
    child=$!
    say "open $child"
}

quit_browser() {
    [ -n "$child" ] && kill -TERM "$child" 2>/dev/null
}

trap 'wanted=1' USR1
trap 'quit_browser' USR2
trap 'ending=1; quit_browser' TERM INT

say "closed -"
[ "${KF_START_BROWSER:-1}" = 1 ] && start_browser

while :; do
    if [ "$wanted" = 1 ]; then
        wanted=0
        [ "$ending" = 1 ] || start_browser
    fi
    if [ -n "$child" ]; then
        wait "$child"
        code=$?
        # a trapped signal interrupts wait; the browser may still be running
        if kill -0 "$child" 2>/dev/null; then continue; fi
        child=""
        say "closed $code"
        echo "browser: closed ($code)"
        [ "$ending" = 1 ] && exit 0
        [ -e "$CONTROL/keep" ] || exit "$code"
    else
        [ "$ending" = 1 ] && exit 0
        sleep 1 &
        wait $! 2>/dev/null
    fi
done
