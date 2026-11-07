#!/usr/bin/env bash
# The browser image, inspected from inside: what a successful build must have
# left there. 0.3.1's Containerfile built on Fedora 42 and failed on 43 over a
# font package's new name, with the error hidden by 2>/dev/null, and an earlier
# one produced an empty GPU-helpers directory with a successful build — so this
# checks results, not steps, and nothing short of the real image can pass it.
#
#   tests/smoke/browser-image.sh [IMAGE]      default kiwi-fox/browser:smoke
#
# ci.yml builds the image with --no-cache first; `make smoke` builds it with the
# cache and runs this. The engine mount the entrypoint needs is not involved.
set -euo pipefail

IMAGE="${1:-kiwi-fox/browser:smoke}"
podman image exists "$IMAGE" || { echo "smoke: no image $IMAGE; build it first (make smoke)" >&2; exit 1; }
echo "== $IMAGE, from inside"
podman run --rm -i --entrypoint sh "$IMAGE" -s <<'IN_IMAGE'
set -u
fail=0
check() {  # WHAT COMMAND...
    what=$1; shift
    if "$@" >/dev/null 2>&1; then echo "ok    $what"; else echo "FAIL  $what"; fail=1; fi
}
nonempty() { [ -n "$(ls -A "$1" 2>/dev/null)" ]; }
empty() { [ -z "$(ls -A "$1" 2>/dev/null)" ]; }
count() { "$@" | wc -l; }

# The stock-firefox engine's font set: the step that failed on Fedora 43.
check "the firefox engine's font set has TrueType fonts" \
    test -n "$(find /usr/share/kf-firefox-fonts -name '*.ttf' | head -1)"
check "its fontconfig resolves them (fc-list)" \
    test "$(FONTCONFIG_FILE=/etc/kf-firefox-fonts.conf count fc-list)" -gt 0
# Camoufox must see no fonts but its own: the default search path is empty.
check "/usr/share/fonts is empty" empty /usr/share/fonts
check "the default fontconfig view is empty (fc-list)" test "$(count fc-list)" -eq 0
# The fingerprint fonts, per family, outside the default path.
for family in open-sans lato source-sans; do
    check "kf-fonts/$family is non-empty" nonempty /usr/share/kf-fonts/$family
done
# Firefox's GPU probe helpers, lifted from Fedora's firefox in a build stage.
check "a GPU probe helper (glxtest/vaapitest/gfxtest) is present" \
    test -n "$(find /usr/libexec/kf -type f -perm -u+x | head -1)"
check "the helpers' firefox version is recorded" test -s /usr/libexec/kf/.firefox-version
# The rest of what the Containerfile promises.
check "kf-browser is the executable entrypoint" test -x /usr/local/bin/kf-browser
check "bwrap is the shim" test "$(readlink /usr/bin/bwrap)" = /usr/local/bin/bwrap-shim
check "the shim and the real bwrap are executable" test -x /usr/local/bin/bwrap-shim -a -x /usr/bin/bwrap.real
check "GTK is pinned to the raster icon theme" grep -q AdwaitaLegacy /etc/gtk-3.0/settings.ini
check "the search-provider addon is there" nonempty /opt/kf-addons
check "/profile and /downloads exist" test -d /profile -a -d /downloads
check "the firefox engine's fontconfig file is there" test -s /etc/kf-firefox-fonts.conf

[ "$fail" -eq 0 ] || { echo "smoke: the image is not what the Containerfile promises"; exit 1; }
echo "ok: the browser image has everything the Containerfile promises"
IN_IMAGE
