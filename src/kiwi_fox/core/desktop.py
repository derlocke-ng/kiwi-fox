"""What can be read from the desktop the browser window will appear on."""

from __future__ import annotations

import subprocess


def prefers_dark() -> bool | None:
    """The desktop's colour scheme, or None when it cannot be read.

    Stock Firefox follows the desktop. Inside the container it cannot see the
    desktop at all — no settings portal, no gsettings — so it would stay light on
    a dark desktop. The launcher reads the preference here and hands it over.
    """
    try:
        out = subprocess.run(  # noqa: S603
            ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    if "dark" in out:
        return True
    if "light" in out or "default" in out:
        return False
    return None
