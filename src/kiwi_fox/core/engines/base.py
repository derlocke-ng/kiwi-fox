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


# What each engine is called where a person reads it.
TITLES = {"camoufox": "Camoufox", "firefox": "Firefox", "torbrowser": "Tor Browser"}


def installed_versions(name: str) -> list[str]:
    """The versions of an engine on this machine, oldest first."""
    if name == "camoufox":
        from . import fetch

        return fetch.installed()
    if name == "firefox":
        from . import firefox_fetch

        return firefox_fetch.installed()
    if name == "torbrowser":
        from . import torbrowser_fetch

        return torbrowser_fetch.installed()
    raise ValueError(f"unknown engine {name!r}")


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
