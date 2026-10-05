#!/usr/bin/env bash
# kiwi-fox browser — exec Camoufox headfully, with the engine mounted read-only
# and the profile mounted read-write.
#
# No Playwright, no juggler, no automation channel: all spoofing arrives through
# the CAMOU_CONFIG_* / CAMOU_PREFS_* environment this container was started with.
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

# Camoufox omits glxtest/vaapitest from its release zip. `kiwi-fox engine
# helpers` installs Fedora's real ones into the engine directory, which is where
# Firefox spawns them from; a stub there would be worse than nothing, because it
# makes Firefox believe the probe ran and found no GPU.
if [ ! -x "$ENGINE/glxtest" ]; then
    echo "browser: no glxtest in the engine — WebGL falls back to software" >&2
fi

echo "browser: launching camoufox for profile $PROFILE"
exec "$ENGINE/camoufox" \
    -profile "$PROFILE" \
    -no-remote \
    "$@"
