"""Where everything lives on disk. XDG, user scope only — no root anywhere."""

from __future__ import annotations

import os
from pathlib import Path

APP = "kiwi-fox"
LABEL = f"app={APP}"
PREFIX = "kf"  # every podman resource name starts with this


def _xdg(var: str, default: str) -> Path:
    return Path(os.environ.get(var) or Path.home() / default)


def data_dir() -> Path:
    return _xdg("XDG_DATA_HOME", ".local/share") / APP


def config_dir() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / APP


def cache_dir() -> Path:
    return _xdg("XDG_CACHE_HOME", ".cache") / APP


def runtime_dir() -> Path:
    rt = os.environ.get("XDG_RUNTIME_DIR")
    return Path(rt) / APP if rt else cache_dir() / "run"


def profiles_dir() -> Path:
    return data_dir() / "profiles"


def profile_dir(profile_id: str) -> Path:
    return profiles_dir() / profile_id


def engines_dir() -> Path:
    return data_dir() / "engines"


def blocklists_dir() -> Path:
    return data_dir() / "blocklists"


def providers_cache() -> Path:
    return data_dir() / "providers.json"


def modules_dir() -> Path:
    """Where provider plugins are installed, one directory per module (tor, vpn,
    9proxy, mysterium). kiwi-updater drops each module's package here; kiwi-fox
    discovers them by scanning this directory."""
    return data_dir() / "modules"


def module_dir(name: str) -> Path:
    return modules_dir() / name


def modules_state_dir() -> Path:
    """Per-module writable runtime state (leases, caches), kept out of the
    read-only installed module directory."""
    return data_dir() / "modules-state"


def module_state_dir(name: str) -> Path:
    return modules_state_dir() / name


# The shared podman network local provider containers and the gateways that use
# them attach to, so a gateway can reach its provider's SOCKS5 while its own
# nftables still permits exactly one destination. Plain (already-remote) SOCKS5
# endpoints never touch it; those gateways stay on pasta.
PROVIDERS_NETWORK = f"{PREFIX}-providers"


def provider_image(name: str) -> str:
    return f"{APP}/{name}:latest"


def provider_container_name(name: str, lease: str | None = None) -> str:
    """A provider container is shared across every profile that uses the same
    module+lease, so its name is keyed on those, not on a profile id."""
    suffix = f"-{lease}" if lease else ""
    raw = f"{PREFIX}-prov-{name}{suffix}"
    # Container names allow [a-zA-Z0-9._-]; a lease like a 9proxy port or a myst
    # provider id is already in that set, but be defensive about separators.
    return "".join(c if (c.isalnum() or c in "._-") else "-" for c in raw)[:63]


def ensure_tree() -> None:
    for d in (
        data_dir(),
        config_dir(),
        profiles_dir(),
        engines_dir(),
        blocklists_dir(),
        modules_dir(),
        modules_state_dir(),
        runtime_dir(),
    ):
        d.mkdir(parents=True, exist_ok=True)


def gateway_name(profile_id: str) -> str:
    return f"{PREFIX}-gw-{profile_id[:12]}"


def browser_name(profile_id: str) -> str:
    return f"{PREFIX}-br-{profile_id[:12]}"
