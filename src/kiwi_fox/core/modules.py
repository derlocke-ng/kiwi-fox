"""Provider modules, as kiwi-fox offers them for an exit.

The modules are kiwi-proxy's (kiwi-plugin-tor, -vpn, -9proxy, -myst install into
its modules directory); this is the little the CLI and the GUI both need: what
is installed, what each can offer, and an endpoint from one.
"""

from __future__ import annotations

from dataclasses import dataclass

from kiwi_proxy import providers

from .models import Endpoint, Lease

# The kiwi app that installs each first-party module, for a hint when one is missing.
PLUGIN_APPS = {
    "tor": "kiwi-plugin-tor",
    "vpn": "kiwi-plugin-vpn",
    "9proxy": "kiwi-plugin-9proxy",
    "mysterium": "kiwi-plugin-myst",
}


@dataclass(frozen=True)
class Module:
    name: str  # also Endpoint.module
    title: str
    description: str
    needs_account: bool
    produces_endpoint: bool  # runs its own container; False: tags a remote SOCKS5


def installed() -> list[Module]:
    """Every module that loads. A broken one is left out, not fatal."""
    out = []
    for name in providers.discover():
        try:
            _prov, m = providers.load(name)
        except providers.ProviderError:
            continue
        out.append(Module(name, m.title, m.description, m.needs_account, m.runs_container))
    return out


def install_hint(name: str) -> str:
    app = PLUGIN_APPS.get(name)
    return f"kiwi install {app}" if app else f"install the {name} provider module"


def leases(name: str) -> list[Lease]:
    """The exits a module can pin. Empty: it only has its default."""
    prov, manifest = providers.load(name)
    return prov.leases(providers.context_for(name, manifest))


def endpoint_from(name: str, *, lease: str | None = None, country: str | None = None) -> Endpoint:
    """Let a module produce the endpoint by bringing itself up."""
    if not providers.is_installed(name):
        raise providers.ProviderError(
            f"provider module {name!r} is not installed ({install_hint(name)})"
        )
    prov, manifest = providers.load(name)
    if not manifest.runs_container:
        raise providers.ProviderError(f"{name!r} does not produce its own endpoint; give one")
    return prov.up(providers.context_for(name, manifest), lease=lease, country=country)
