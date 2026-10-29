"""Stock Firefox: Mozilla's own build, no spoofing.

A firefox profile shows this machine's real values — the point is a coherent,
ordinary Firefox when uniqueness is not what is wanted, not a disguise. So there
is no fingerprint, no ``CAMOU_CONFIG`` and no per-profile fontconfig. kiwi-fox
sets only what the container and the proxy require, plus the few comfort prefs
that no page can observe: the proxy and leak prevention (shared with every
engine), WebRTC candidates confined so the host address cannot leak around the
proxy, hardware rendering, and the appearance. Updates are turned off through
the bundle's policies.json at fetch time, not here.
"""

from __future__ import annotations

from pathlib import Path

from .. import gpu
from ..models import ContainerSpec, Fingerprint, Profile
from . import firefox_fetch
from .gecko import accelerated, base_spec, is_dark, network_prefs

ENGINE_MOUNT = "/opt/firefox"
# A static fontconfig shipped in the image (containers/browser): it exposes a
# plain Linux font set so Firefox has fonts, and is kept off Camoufox's path, so
# this changes nothing about Camoufox's per-profile fonts.
FONTCONFIG_MOUNT = "/etc/kf-firefox-fonts.conf"

IMAGE = "kiwi-fox/browser:latest"


class Firefox:
    name = "firefox"
    binary = firefox_fetch.BINARY

    def engine_dir(self, profile: Profile, fp: Fingerprint | None = None) -> Path:
        version = profile.engine_version or firefox_fetch.latest_installed()
        if not version:
            raise RuntimeError("no Firefox engine installed; run `kiwi-fox engine fetch firefox`")
        return firefox_fetch.target_dir(version)

    # ---------------------------------------------------------------- prefs
    def prefs(self, fp: Fingerprint | None, profile: Profile) -> dict[str, object]:
        accel = accelerated(profile)
        dark = is_dark(profile)
        prefs: dict[str, object] = {
            # Proxy, DNS and leak prevention — shared with every Gecko engine.
            **network_prefs(profile),
            # WebRTC: never gather a host candidate, and only the default route's
            # address. The firewall already drops the UDP, but a page granted
            # getUserMedia could otherwise read the host address string out of an
            # ICE candidate. Camoufox hides this by spoofing; stock Firefox must
            # confine it instead.
            "media.peerconnection.ice.no_host": True,
            "media.peerconnection.ice.default_address_only": True,
            "media.peerconnection.ice.proxy_only_if_behind_proxy": True,
            # Rendering: real hardware GL where the host can give it, in-process
            # software WebRender where it cannot (the GPU process crash-loops
            # without a render node). None of this is web-observable.
            "gfx.webrender.all": True,
            "gfx.webrender.software": not accel,
            "gfx.webrender.compositor": accel,
            "layers.gpu-process.enabled": accel,
            "media.gpu-process-decoder": accel,
            "gfx.x11-egl.force-enabled": accel,
            # VA-API only exists on the Mesa paths; forcing it where the NVIDIA
            # driver is in use points the decoder at nothing.
            "media.hardware-video-decoding.force-enabled": accel
            and gpu.plan().kind.startswith("mesa"),
            # Comfort only, not observable by a site.
            "browser.startup.page": 3,
            "browser.sessionstore.resume_from_crash": True,
            "browser.shell.checkDefaultBrowser": False,
        }
        if dark is not None:
            # Light or dark, for the chrome and prefers-color-scheme alike.
            prefs["ui.systemUsesDarkTheme"] = int(dark)
        return prefs

    # --------------------------------------------------------------- config
    def config(
        self, fp: Fingerprint | None, profile: Profile, exit_ip: str | None
    ) -> dict[str, object]:
        # No CAMOU_CONFIG: stock Firefox is not spoofed.
        return {}

    # ----------------------------------------------------------------- env
    def env(self, profile: Profile) -> dict[str, str]:
        env = {
            "LANG": "en-US.UTF-8",
            "MOZ_ENABLE_WAYLAND": "1",
            **({"MOZ_WEBRENDER": "1"} if accelerated(profile) else {}),
            **({"GTK_THEME": "Adwaita:dark"} if is_dark(profile) else {}),
            "FONTCONFIG_FILE": FONTCONFIG_MOUNT,
            "KF_PROFILE_DIR": "/profile",
            "KF_ENGINE_DIR": ENGINE_MOUNT,
            "KF_ENGINE_BIN": firefox_fetch.BINARY,
        }
        return env

    # ---------------------------------------------------------------- spec
    def build_spec(
        self, profile: Profile, fp: Fingerprint | None, *, gateway: str, exit_ip: str | None
    ) -> ContainerSpec:
        return base_spec(
            profile,
            image=IMAGE,
            gateway=gateway,
            engine_dir=self.engine_dir(profile, fp),
            engine_mount=ENGINE_MOUNT,
            env=self.env(profile),
        )
