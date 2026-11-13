"""The icon a profile's app-grid entry shows: Kiwi Fox's (the default), a colored
Kiwi Fox from the app's data folder, the icon an installed engine ships (your own
copy of Firefox's, Camoufox's or Tor Browser's: their logos are not ours to
ship), or the icon theme's generic browser."""

from __future__ import annotations

import shutil
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from . import kiwi_icon, paths
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


# ------------------------------------------------------------------- colours
# A profile's Kiwi Fox in a colour of its own, from the kiwi-icons kit
# (kiwi_icon.py, copied unchanged from github.com/derlocke-ng/kiwi-icons, kit/),
# so profiles can be told apart in the app grid, the dash and the list.
COLORS = list(kiwi_icon.COLORWAYS)
# The order new ones get them in: far apart on the colour wheel first, so the
# first few already look different side by side (the kit's own order runs
# through the warm hues first).
SPREAD = [
    c
    for c in (
        "ember",
        "ocean",
        "forest",
        "violet",
        "honey",
        "teal",
        "crimson",
        "indigo",
        "kiwi",
        "orchid",
        "rose",
        "graphite",
    )
    if c in kiwi_icon.COLORWAYS
] + [
    c
    for c in kiwi_icon.COLORWAYS
    if c
    not in {
        "ember",
        "ocean",
        "forest",
        "violet",
        "honey",
        "teal",
        "crimson",
        "indigo",
        "kiwi",
        "orchid",
        "rose",
        "graphite",
    }
]


def color_label(key: str) -> str:
    return kiwi_icon.COLORWAYS[key]["label"] if key in kiwi_icon.COLORWAYS else "Kiwi Fox's own"


def next_color(used: Iterable[str]) -> str:
    """The first colourway no profile has yet; once every one is taken, the
    least used."""
    count = Counter(c for c in used if c)
    return min(SPREAD, key=lambda c: (count[c], SPREAD.index(c)))


def colored_icon(profile) -> Path | None:
    """The profile's coloured Kiwi Fox as a file, rendered once per colour; None
    for Kiwi Fox's own."""
    if profile.color not in kiwi_icon.COLORWAYS:
        return None
    folder = paths.data_dir() / "icons"
    f = folder / f"{profile.id}-{profile.color}.svg"
    if not f.exists():
        try:
            folder.mkdir(parents=True, exist_ok=True)
            for old in folder.glob(f"{profile.id}-*.svg"):
                old.unlink()
            f.write_text(kiwi_icon.render("fox", colorway=profile.color, title=profile.name))
        except OSError:
            return None
    return f


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
