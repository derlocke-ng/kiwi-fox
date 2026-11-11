"""The desktop the browser window appears on: what is read from it, and the
entries written to it so GNOME launches a profile like any app."""

from __future__ import annotations

import contextlib
import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from .. import APP_ID
from . import paths
from .models import Profile

# A profile's entry: <app id>.profile-<id[:8]>.desktop, so the prefix finds them all.
ENTRY_PREFIX = f"{APP_ID}.profile-"


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


# ------------------------------------------------------------ profile entries
def entry_path(profile_id: str) -> Path:
    return paths.applications_dir() / f"{ENTRY_PREFIX}{profile_id[:8]}.desktop"


def window_app_id(profile: Profile) -> str:
    """What the profile's browser window announces as its app id (Firefox's
    ``--name`` sets it on Wayland, ``--class`` the X11 WM_CLASS), so GNOME can match
    the window to an entry: the profile's own when it has one, else Kiwi Fox's.
    Without this the window says "camoufox" and the shell shows a blank icon."""
    if profile.desktop_entry:
        return f"{ENTRY_PREFIX}{profile.id[:8]}"
    return APP_ID


def window_args(profile: Profile) -> list[str]:
    """The arguments that give the browser that app id, ahead of anything else."""
    app_id = window_app_id(profile)
    return ["--name", app_id, "--class", app_id]


def launcher() -> str:
    """The kiwi-fox command an entry runs: the installed launcher by absolute
    path, because the app grid need not have ~/.local/bin on its PATH."""
    return shutil.which("kiwi-fox") or "kiwi-fox"


def _exec_arg(value: str) -> str:
    """One Exec= argument, quoted the way the Desktop Entry spec wants when it
    holds a space or a reserved character."""
    if re.search(r"""[\s"'\\><~|&;$*?#()`]""", value):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def _icon(profile: Profile) -> str:
    if not profile.icon:
        return APP_ID
    from . import icons

    found = icons.entry_icon(profile.icon, profile.id)
    if found == APP_ID and (kept := icons.kept_icon(profile.id)):
        return kept  # the engine it came from is gone; the copy stays
    return found


def render_entry(profile: Profile, describe: str) -> str:
    """The entry: the profile's name, the Kiwi Fox icon, `kiwi-fox run <id>`, and a
    Stop action. `describe` is the browser and the proxy, for the comment."""
    cmd = _exec_arg(launcher())
    name = profile.name.replace("\n", " ")
    keywords = [name, *profile.tags]
    keyword = ";".join(k.replace(";", " ") for k in keywords)
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        f"Name={name}",
        "GenericName=Kiwi Fox profile",
        f"Comment={describe} — a Kiwi Fox browser identity",
        f"Exec={cmd} run {profile.id}",
        f"Icon={_icon(profile)}",
        "Terminal=false",
        "Categories=Network;WebBrowser;",
        f"Keywords=kiwi;browser;profile;{keyword};",
        "StartupNotify=false",
        # The window announces this id (window_app_id), so the shell links it here.
        f"StartupWMClass={ENTRY_PREFIX}{profile.id[:8]}",
        f"X-KiwiFox-Profile={profile.id}",
        "Actions=stop;",
        "",
        "[Desktop Action stop]",
        "Name=Stop",
        f"Exec={cmd} stop {profile.id}",
        "",
    ]
    return "\n".join(lines)


def sync_entry(profile: Profile, describe: str) -> bool:
    """Write the profile's entry when it wants one, remove it otherwise; returns
    whether an entry exists afterwards. Best effort: a desktop that cannot take
    the file does not stop a profile from being saved."""
    path = entry_path(profile.id)
    try:
        if profile.desktop_entry:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(render_entry(profile, describe))
            tmp.replace(path)
            return True
        path.unlink(missing_ok=True)
        return False
    except OSError:
        return path.exists()


def remove_entry(profile_id: str) -> None:
    with contextlib.suppress(OSError):
        entry_path(profile_id).unlink(missing_ok=True)


def sync_all(
    profiles: list[Profile], describe: Callable[[Profile], str]
) -> tuple[list[str], list[str]]:
    """Every entry in line with the profiles: written for those that want one (so
    a moved launcher is followed), gone for those that do not or no longer exist.
    Returns the names with an entry and the stale files removed."""
    with_entry = [p.name for p in profiles if sync_entry(p, describe(p))]
    keep = {entry_path(p.id) for p in profiles if p.desktop_entry}
    removed = []
    for stale in sorted(paths.applications_dir().glob(f"{ENTRY_PREFIX}*.desktop")):
        if stale not in keep:
            with contextlib.suppress(OSError):
                stale.unlink()
                removed.append(stale.name)
    return with_entry, removed
