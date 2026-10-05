#!/usr/bin/env bash
# kiwi-fox browser — exec Camoufox headfully, with the engine mounted read-only
# and the profile mounted read-write.
#
# No Playwright, no juggler, no automation channel: all spoofing arrives through
# the CAMOU_CONFIG_* environment this container was started with, and prefs
# through the profile's user.js.
set -euo pipefail

ENGINE="${KF_ENGINE_DIR:-/opt/camoufox}"
PROFILE="${KF_PROFILE_DIR:-/profile}"

[ -x "$ENGINE/camoufox" ] || { echo "browser: no engine at $ENGINE" >&2; exit 2; }

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

echo "browser: launching camoufox for profile $PROFILE"
exec "$ENGINE/camoufox" \
    -profile "$PROFILE" \
    -no-remote \
    "$@"
