"""LibreWolf: the hardened Firefox build of the LibreWolf project, as it comes.

Like stock Firefox, a LibreWolf profile is not spoofed by kiwi-fox: there is no
fingerprint and no ``CAMOU_CONFIG``. What a page sees is decided by LibreWolf's
own settings (its librewolf.cfg: fingerprinting resistance on, WebGL off,
telemetry off, uBlock Origin installed by its policies). kiwi-fox adds what the
container and the proxy need, exactly as for Firefox.
"""

from __future__ import annotations

from pathlib import Path

from ..models import Fingerprint, Profile
from . import librewolf_fetch
from .firefox import Firefox

ENGINE_MOUNT = "/opt/librewolf"


class LibreWolf(Firefox):
    name = "librewolf"
    binary = librewolf_fetch.BINARY
    engine_mount = ENGINE_MOUNT

    def engine_dir(self, profile: Profile, fp: Fingerprint | None = None) -> Path:
        from ..engine_versions import version_of

        version = version_of(profile)
        if not version:
            raise RuntimeError(
                "no LibreWolf installed; run `kiwi-fox engine fetch --engine librewolf`"
            )
        return librewolf_fetch.target_dir(version)
