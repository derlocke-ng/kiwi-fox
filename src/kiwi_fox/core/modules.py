"""Provider modules, as kiwi-fox offers them for an exit.

The modules are kiwi-proxy's (kiwi-plugin-tor, -vpn, -9proxy, -myst install into
its modules directory), and so are the exits made from them (`kiwi-proxy add
NAME --module tor`, or kiwi-proxy's editor from kiwi-fox's dialogs). This is the
little kiwi-fox still needs: what is installed, and how a module exit reads.
"""

from __future__ import annotations

from dataclasses import dataclass

from kiwi_proxy import providers

from .models import Endpoint

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


def exit_label(endpoint: Endpoint) -> str:
    """Where a profile exits, the way a person thinks of it: "tor · DE", not the
    provider's address on the bridge."""
    if not endpoint.module:
        return f"{endpoint.host}:{endpoint.port}"
    bits = [endpoint.module]
    if endpoint.country:
        bits.append(endpoint.country.upper())
    if endpoint.lease:
        bits.append(f"lease {endpoint.lease}")
    return " · ".join(bits)


def install_hint(name: str) -> str:
    app = PLUGIN_APPS.get(name)
    return f"kiwi install {app}" if app else f"install the {name} provider module"
