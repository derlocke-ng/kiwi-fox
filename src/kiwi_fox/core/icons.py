"""The icon a profile's app-grid entry shows: Kiwi Fox's (the default), a colored
Kiwi Fox from the app's data folder, the icon an installed engine ships (your own
copy of Firefox's, Camoufox's or Tor Browser's: their logos are not ours to
ship), or the icon theme's generic browser."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from . import paths
from .engines import TITLES, installed_versions

APP_ID = "eu.kiwinetwork.KiwiFox"
ENGINE_ICONS = {
    "firefox": "browser/chrome/icons/default/default128.png",
    "camoufox": "browser/chrome/icons/default/default128.png",
    "torbrowser": "Browser/browser/chrome/icons/default/default128.png",
}


@dataclass(frozen=True)
class Icon:
    key: str
    title: str
    name: str = ""  # an icon-theme name
    file: Path | None = None  # or a file


def _variants_dir() -> Path | None:
    here = Path(__file__).resolve()
    for candidate in (
        here.parents[3] / "data" / "profile-icons",
        here.parents[2] / "data" / "profile-icons",
    ):
        if candidate.is_dir():
            return candidate
    return None


def choices() -> list[Icon]:
    out = [Icon("", "Kiwi Fox", name=APP_ID)]
    if folder := _variants_dir():
        for f in sorted(folder.glob("kiwi-fox-*.*")):
            if f.suffix in (".svg", ".png"):
                out.append(Icon(f.stem, f.stem.replace("-", " ").title(), file=f))
    for engine, rel in ENGINE_ICONS.items():
        have = installed_versions(engine)
        if have:
            f = paths.engines_dir() / f"{engine}-{have[-1]}" / rel
            if f.is_file():
                out.append(Icon(engine, TITLES[engine], file=f))
    out.append(Icon("web-browser", "Generic browser", name="web-browser"))
    return out


def entry_icon(key: str, profile_id: str) -> str:
    """What the entry's Icon= says for a choice: a theme name, or a copy of the
    file kept with the app (an engine can be removed later)."""
    found = {i.key: i for i in choices()}.get(key or "")
    if found is None or (found.file is None and not found.name):
        return APP_ID
    if found.name:
        return found.name
    dest = paths.data_dir() / "icons" / f"{profile_id}{found.file.suffix}"
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists() or dest.read_bytes() != found.file.read_bytes():
            shutil.copyfile(found.file, dest)
    except OSError:
        return APP_ID
    return str(dest)


def kept_icon(profile_id: str) -> str | None:
    """The copy made for a profile earlier, when its source is gone."""
    for suffix in (".png", ".svg"):
        f = paths.data_dir() / "icons" / f"{profile_id}{suffix}"
        if f.exists():
            return str(f)
    return None
