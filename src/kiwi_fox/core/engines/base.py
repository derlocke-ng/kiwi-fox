"""One interface per engine: profile -> ContainerSpec."""

from __future__ import annotations

from typing import Protocol

from ..models import ContainerSpec, Fingerprint, Profile


class Engine(Protocol):
    name: str

    def prefs(self, fp: Fingerprint, profile: Profile) -> dict[str, object]: ...

    def config(
        self, fp: Fingerprint, profile: Profile, exit_ip: str | None
    ) -> dict[str, object]: ...

    def build_spec(
        self, profile: Profile, fp: Fingerprint, *, gateway: str, exit_ip: str | None
    ) -> ContainerSpec: ...


def get_engine(name: str) -> Engine:
    if name == "camoufox":
        from .camoufox import Camoufox

        return Camoufox()
    raise ValueError(f"unknown engine {name!r}")
