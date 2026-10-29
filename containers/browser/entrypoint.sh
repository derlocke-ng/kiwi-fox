#!/usr/bin/env bash
# kiwi-fox browser — exec the engine headfully, with it mounted read-only and the
# profile mounted read-write. The engine and its binary name are passed in:
# camoufox (the default, so an older gateway env still works), firefox, or a Tor
# Browser binary.
#
# No Playwright, no juggler, no automation channel: Camoufox's spoofing arrives
# through the CAMOU_CONFIG_* environment this container was started with, and
# every engine's prefs through the profile's user.js.
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

echo "browser: launching $BIN for profile $PROFILE"
exec "$ENGINE/$BIN" \
    -profile "$PROFILE" \
    -no-remote \
    "$@"
