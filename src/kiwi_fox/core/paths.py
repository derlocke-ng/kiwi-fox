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
    return data_dir() / "modules"


def ensure_tree() -> None:
    for d in (
        data_dir(),
        config_dir(),
        profiles_dir(),
        engines_dir(),
        blocklists_dir(),
        modules_dir(),
        runtime_dir(),
    ):
        d.mkdir(parents=True, exist_ok=True)


def gateway_name(profile_id: str) -> str:
    return f"{PREFIX}-gw-{profile_id[:12]}"


def browser_name(profile_id: str) -> str:
    return f"{PREFIX}-br-{profile_id[:12]}"
