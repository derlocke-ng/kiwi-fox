"""One interface per engine: profile -> ContainerSpec.

Camoufox needs a Fingerprint (the frozen Windows identity); the non-spoofing
engines do not, so ``fp`` is optional across the protocol and is None for them.
"""

from __future__ import annotations

from typing import Protocol

from ..models import ContainerSpec, Fingerprint, Profile


class Engine(Protocol):
    name: str

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
    # firefox and torbrowser are valid EngineName values but are added in later
    # changes; until then nothing creates such a profile, so this is unreachable
    # in normal use and exists to fail loudly rather than silently mis-dispatch.
    if name in ("firefox", "torbrowser"):
        raise ValueError(f"the {name!r} engine is not available in this build yet")
    raise ValueError(f"unknown engine {name!r}")
