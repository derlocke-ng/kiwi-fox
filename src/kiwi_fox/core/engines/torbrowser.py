"""Tor Browser through the tor provider, the Whonix way: no stacked Tor.

The bundled tor is disabled (``TOR_PROVIDER=none``) and Tor Browser is pointed at
the gateway forwarder on 127.0.0.1:1080, which runs in passthrough mode so the
browser's own per-first-party SOCKS credentials reach the tor provider and key a
circuit per site (see docs/decisions.md). Nothing is spoofed and no user.js
beyond the proxy/leak block is written, so Tor Browser keeps its own uniform
fingerprint. DNS is always remote — Tor Browser resolves at the exit, which is
what makes .onion work — regardless of the profile's DNS mode.
"""

from __future__ import annotations

from pathlib import Path

from ..models import ContainerSpec, Fingerprint, Profile
from . import torbrowser_fetch
from .gecko import FORWARDER_HOST, FORWARDER_PORT, base_spec, is_dark, network_prefs

ENGINE_MOUNT = "/opt/torbrowser"
IMAGE = "kiwi-fox/browser:latest"

# The gateway forwarder, as Tor Browser's SOCKS target. TOR_PROVIDER=none makes
# Tor Browser proxy-only (no bundled tor, no control port) and apply these to
# its prefs immediately.
SOCKS_HOST = FORWARDER_HOST
SOCKS_PORT = str(FORWARDER_PORT)

# kiwi-proxy 0.10's gateway filter for Tor's control port (New Identity, the
# circuit display, onion-site keys), on the namespace's loopback.
CONTROL_PORT = "9151"


def _tor_control(profile: Profile) -> dict[str, str]:
    """Tor Browser on its exit's own Tor through the gateway's control filter, when
    the exit has one (kiwi-proxy 0.10); otherwise proxy-only (no control port),
    as before. The filter authenticates to Tor itself: the password here is a
    placeholder it ignores."""
    try:
        from kiwi_proxy import exits, selection

        ex = exits.load(profile.exit) if profile.exit else None
        has = ex is not None and hasattr(selection, "wants_control") and selection.wants_control(ex)
    except Exception:  # noqa: BLE001 - no exit, an older kiwi-proxy
        has = False
    if not has:
        return {"TOR_PROVIDER": "none"}
    return {
        "TOR_SKIP_LAUNCH": "1",
        "TOR_CONTROL_HOST": "127.0.0.1",
        "TOR_CONTROL_PORT": CONTROL_PORT,
        "TOR_CONTROL_PASSWD": "kiwi",
    }


# Only tor exits make sense for Tor Browser; this is the provider module name.
REQUIRED_MODULE = "tor"


class TorBrowser:
    name = "torbrowser"
    binary = torbrowser_fetch.BINARY

    def engine_dir(self, profile: Profile, fp: Fingerprint | None = None) -> Path:
        from ..engine_versions import version_of

        version = version_of(profile)
        if not version:
            raise RuntimeError(
                "no Tor Browser installed; run `kiwi-fox engine fetch --engine torbrowser`"
            )
        return torbrowser_fetch.target_dir(version)

    # ---------------------------------------------------------------- prefs
    def prefs(self, fp: Fingerprint | None, profile: Profile) -> dict[str, object]:
        # Only the proxy/DNS/leak block, DNS forced remote, and the profile's
        # light or dark for the browser's own window. No spoofing, no fingerprint
        # prefs: Tor Browser's own defaults must stand. Pages still see light, as
        # in every Tor Browser (resistFingerprinting reports light).
        prefs = network_prefs(profile, force_remote_dns=True)
        dark = is_dark(profile)
        if dark is not None:
            prefs["ui.systemUsesDarkTheme"] = int(dark)
        return prefs

    def config(
        self, fp: Fingerprint | None, profile: Profile, exit_ip: str | None
    ) -> dict[str, object]:
        return {}

    # ----------------------------------------------------------------- env
    def env(self, profile: Profile) -> dict[str, str]:
        return {
            **_tor_control(profile),
            "TOR_SOCKS_HOST": SOCKS_HOST,
            "TOR_SOCKS_PORT": SOCKS_PORT,
            "MOZ_ENABLE_WAYLAND": "1",
            **({"GTK_THEME": "Adwaita:dark"} if is_dark(profile) else {}),
            # Tor Browser's start-tor-browser sets both; keep its shader cache and
            # gsettings out of the read-only bundle.
            "GSETTINGS_BACKEND": "memory",
            "__GL_SHADER_DISK_CACHE": "0",
            "KF_PROFILE_DIR": "/profile",
            "KF_ENGINE_DIR": ENGINE_MOUNT,
            "KF_ENGINE_BIN": torbrowser_fetch.BINARY,
            # The entrypoint cue: cd into Browser/ and wire Tor Browser's own
            # bundled fontconfig, the way start-tor-browser does.
            "KF_TORBROWSER": "1",
        }

    # ---------------------------------------------------------------- spec
    def build_spec(
        self, profile: Profile, fp: Fingerprint | None, *, gateway: str | None, exit_ip: str | None
    ) -> ContainerSpec:
        return base_spec(
            profile,
            image=IMAGE,
            gateway=gateway,
            engine_dir=self.engine_dir(profile, fp),
            engine_mount=ENGINE_MOUNT,
            env=self.env(profile),
        )
