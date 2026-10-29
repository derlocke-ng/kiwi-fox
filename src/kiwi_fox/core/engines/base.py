"""One interface per engine: profile -> ContainerSpec.

Camoufox needs a Fingerprint (the frozen Windows identity); the non-spoofing
engines do not, so ``fp`` is optional across the protocol and is None for them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ..models import ContainerSpec, Fingerprint, Profile


class Engine(Protocol):
    name: str
    binary: str  # the executable inside engine_dir, e.g. "camoufox", "firefox"

    def engine_dir(self, profile: Profile, fp: Fingerprint | None) -> Path:
        """Where this engine is installed on the host (mounted read-only)."""
        ...

    def prefs(self, fp: Fingerprint | None, profile: Profile) -> dict[str, object]: ...

    def config(
        self, fp: Fingerprint | None, profile: Profile, exit_ip: str | None
    ) -> dict[str, object]: ...

    def build_spec(
        self, profile: Profile, fp: Fingerprint | None, *, gateway: str, exit_ip: str | None
    ) -> ContainerSpec: ...


def get_engine(name: str) -> Engine:
    if name == "camoufox":
        from .camoufox import Camoufox

        return Camoufox()
    if name == "firefox":
        from .firefox import Firefox

        return Firefox()
    if name == "torbrowser":
        from .torbrowser import TorBrowser

        return TorBrowser()
    raise ValueError(f"unknown engine {name!r}")
