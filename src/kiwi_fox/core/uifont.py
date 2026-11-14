"""The desktop's interface font, for the browser's own interface.

A browser in a container has no desktop settings to read, so GTK falls back to
"Sans 10" and tabs, menus and the address bar come out smaller than every other
window (13.3 px where GNOME's default is 14.7 or 16). Each launch hands the
container a GTK settings file with the desktop's font and text scaling.

Pages do not read this. Measured on the dev VM (2026-11-14) through Marionette:
with the interface at "Sans 10", a page in Camoufox read 12 px Segoe UI for
`font: menu` and the other system fonts (the Windows identity), and in Tor
Browser 15 px Arimo (its own fixed answer); the same after the change.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

SETTINGS_MOUNT = "/etc/gtk-3.0/settings.ini"
# The image's own setting (containers/browser/Containerfile): PNG icons only.
BASE = "[Settings]\ngtk-icon-theme-name=AdwaitaLegacy\n"
FIREFOX_FONT_MOUNT = "/usr/share/kf-firefox-fonts/host-ui"


def _gsetting(key: str) -> str:
    if not shutil.which("gsettings"):
        return ""
    try:
        out = subprocess.run(  # noqa: S603
            ["gsettings", "get", "org.gnome.desktop.interface", key],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError, AttributeError):
        return ""
    return out.strip().strip("'")


def parse(name: str) -> tuple[str, float] | None:
    """("Adwaita Sans", 12.0) from "Adwaita Sans 12"; None when there is no size."""
    m = re.fullmatch(r"\s*(.+?)\s+(\d+(?:\.\d+)?)\s*", name or "")
    if not m or not 6 <= float(m.group(2)) <= 40:
        return None
    return m.group(1).rstrip(","), float(m.group(2))


def host_font() -> tuple[str, float, float] | None:
    """The desktop's interface font: (family, points, text scaling). KF_UI_FONT
    ("Family 12") says it for a session without a desktop."""
    found = parse(os.environ.get("KF_UI_FONT") or _gsetting("font-name"))
    if found is None:
        return None
    try:
        scale = float(_gsetting("text-scaling-factor") or 1)
    except ValueError:
        scale = 1.0
    return found[0], found[1], scale if 0.5 <= scale <= 3 else 1.0


def gtk_settings(font: tuple[str, float, float] | None) -> str:
    if font is None:
        return BASE
    family, points, scale = font
    size = f"{points:g}"
    lines = [BASE.rstrip("\n"), f"gtk-font-name={family} {size}"]
    if scale != 1.0:
        lines.append(f"gtk-xft-dpi={round(96 * 1024 * scale)}")
    return "\n".join(lines) + "\n"


def font_dirs(family: str) -> list[Path]:
    """The folders the desktop keeps that family's files in (fontconfig says)."""
    if not shutil.which("fc-list"):
        return []
    try:
        out = subprocess.run(  # noqa: S603
            ["fc-list", "-f", "%{file}\n", f":family={family}"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError, AttributeError):
        return []
    dirs = sorted({Path(line).parent for line in out.splitlines() if line.strip()})
    return [d for d in dirs if d.is_dir()][:2]


def volumes(profile_dir: Path, engine: str) -> list[tuple[str, str, str]]:
    """The mounts a launch adds: the GTK settings, and for stock Firefox (this
    machine's own values) the font's files as well. Camoufox and Tor Browser get
    the size only: their fonts are a fixed set a page can enumerate, and the
    desktop's font must not join it."""
    font = host_font()
    if font is None:
        return []
    ini = profile_dir / "gtk-settings.ini"
    try:
        ini.write_text(gtk_settings(font))
    except OSError:
        return []
    out = [(str(ini), SETTINGS_MOUNT, "ro,z")]
    if engine == "firefox":
        for n, d in enumerate(font_dirs(font[0])):
            out.append((str(d), f"{FIREFOX_FONT_MOUNT}-{n}", "ro"))
    return out
