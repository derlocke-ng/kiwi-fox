"""The real browser window: how big it opens, and what it was left at.

Reported window sizes are real — the engine does not spoof `outerWidth` and
friends — so the only way to keep them consistent with the claimed screen is to
open the real window at a size that screen could hold.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import paths
from .fingerprint import windows11 as w11
from .models import Fingerprint, Profile

XULSTORE_KEY = "chrome://browser/content/browser.xhtml"


def remembered(data_dir: Path) -> tuple[int, int] | None:
    """The size Firefox saved when the window was last resized, if any."""
    try:
        saved = json.loads((data_dir / "xulstore.json").read_text())[XULSTORE_KEY]["main-window"]
        size = int(float(saved["width"])), int(float(saved["height"]))
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return size if min(size) > 0 else None


def opening_size(profile: Profile, fp: Fingerprint) -> tuple[tuple[int, int], str]:
    """-> ((width, height), how) for the next launch.

    how: "remembered" — as the window was left; "fitted" — as it was left, made
    smaller because the claimed screen could not hold it; "default" — what a fresh
    Firefox picks on that screen.
    """
    saved = remembered(paths.profile_dir(profile.id) / "browser-data")
    size = w11.window_size(fp.screen, saved)
    if not saved:
        return size, "default"
    return size, "remembered" if size == saved else "fitted"


def prepare(profile: Profile, fp: Fingerprint, data_dir: Path | None = None) -> None:
    """Before a launch: leave Firefox a saved window state the engine's startup
    resize cannot trip over.

    Two states do trip it, both measured on 156.0.1. With no saved size at all,
    Firefox's first-run rule *maximises* on a small screen (a claimed 1366x768);
    and a window the user maximised comes back maximised. Either way the engine
    un-maximises during startup and then asks for the size the window already
    nominally has, which is dropped as no change — and the window is left about
    500x200. So the saved state always says: this size, not maximised.
    """
    if not w11.engine_sizes_window(fp.engine_version):
        return
    (width, height), _how = opening_size(profile, fp)
    path = (data_dir or paths.profile_dir(profile.id) / "browser-data") / "xulstore.json"
    try:
        store = json.loads(path.read_text())
    except (OSError, ValueError):
        store = {}
    if not isinstance(store, dict):
        store = {}
    window = store.setdefault(XULSTORE_KEY, {}).setdefault("main-window", {})
    window.update({"width": str(width), "height": str(height), "sizemode": "normal"})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, indent=1))


def describe(profile: Profile, fp: Fingerprint) -> str:
    """One line for a person: how big the window opens, and why that size."""
    if not w11.engine_sizes_window(fp.engine_version):
        return "1280x1040 — fixed by this engine version"
    (width, height), how = opening_size(profile, fp)
    why = {
        "remembered": "as you left it",
        "fitted": "as you left it, made smaller to fit the claimed screen",
        "default": "what a fresh Firefox picks on this screen",
    }[how]
    return f"opens {width}x{height} — {why}"
