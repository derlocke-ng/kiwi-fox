"""Kiwi Fox's own preferences (the General page): what happens when a browser
quits, and whether leftovers are repaired when the app starts.

Kept in ``~/.config/kiwi-fox/settings.json``; a missing or broken file means the
defaults.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from . import paths


@dataclass
class Settings:
    # When the browser quits: False stops its container (and lets go of the exit,
    # which Kiwi Proxy takes down when nothing else uses it); True keeps it running.
    keep_container: bool = False
    # Before anything starts: remove this app's containers an unclean shutdown
    # left, clear stale profile locks, start a watcher for each running container.
    repair_on_start: bool = True
    # What the New profile dialog starts with: an engine, and an exit id, "none"
    # for no proxy, or "" to leave the choice to the dialog (its first exit).
    new_engine: str = "camoufox"
    new_exit: str = ""


def path():
    return paths.config_dir() / "settings.json"


def load() -> Settings:
    try:
        data = json.loads(path().read_text())
    except (OSError, ValueError):
        return Settings()
    known = Settings.__dataclass_fields__
    try:
        return Settings(**{k: v for k, v in data.items() if k in known})
    except TypeError:
        return Settings()


def save(s: Settings) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(s), indent=2) + "\n")
    tmp.replace(p)
