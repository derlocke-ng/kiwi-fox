"""Kiwi Fox profiles in the snapshot folder that kiwi-proxy keeps.

The folder, its encryption and the passphrase are kiwi-proxy's (``kiwi_proxy.
snapshots``); this module says what a profile's snapshot holds, when one is taken,
and how one is put back.

A profile's snapshot holds its whole folder — ``profile.json``, the fingerprint,
the browser data — except what the browser rebuilds or downloads again (caches,
safe-browsing lists, remote settings, crash reports, lock files) and the
downloads. ff1 on the developer's desktop: 243 MB on disk, 9 MB as a snapshot.

When: after the profile ran and stopped, after its settings changed while it is
stopped, and when asked. Never while its browser runs: a running Firefox has its
databases open.
"""

from __future__ import annotations

import contextlib
import fnmatch
import os
import shutil
import tarfile
from dataclasses import dataclass
from pathlib import Path

import kiwi_proxy

from .. import __version__
from . import launch, paths, store
from .models import Profile

# The snapshot library, its screens' "Snapshot everything now" row and the cancel
# answer of the newer-copy question are kiwi-proxy 0.8.1's.
NEEDS_PROXY = (0, 8, 1)


def _version(text: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in text.split(".")[:3])
    except ValueError:
        return (0,)


try:
    from kiwi_proxy import snapshots as snap
except ImportError:  # pragma: no cover - an older kiwi-proxy
    snap = None  # type: ignore[assignment]
if _version(getattr(kiwi_proxy, "__version__", "0")) < NEEDS_PROXY:
    snap = None  # type: ignore[assignment]

KIND = "profile"
NEEDS = "snapshots need kiwi-proxy 0.8.1 or later (kiwi update kiwi-proxy)"

# Top-level entries of the profile folder that stay on this device.
SKIP_TOP = ("downloads", "retired")
# Top-level entries of browser-data the browser rebuilds or fetches again, plus
# what only makes sense on the device it was written on.
SKIP_BROWSER = (
    "cache2",
    "startupCache",
    ".cache",
    "shader-cache",
    "safebrowsing",
    "remote-settings",
    "settings",
    "security_state",
    "suggest.sqlite*",
    "gmp-*",
    "thumbnails",
    "tmp",
    "minidumps",
    "crashes",
    "datareporting",
    "Downloads",
    "lock",
    ".parentlock",
    ".startup-incomplete",
    "Telemetry.ShutdownTime.txt",
)


def available() -> bool:
    return snap is not None


def _require() -> None:
    if snap is None:
        raise store.StoreError(NEEDS)


def skipped(relative: str) -> bool:
    """Whether a path inside the profile folder stays out of its snapshot."""
    parts = relative.split("/")
    if parts[0] in SKIP_TOP:
        return True
    if parts[0] == "browser-data" and len(parts) > 1:
        return any(fnmatch.fnmatch(parts[1], pattern) for pattern in SKIP_BROWSER)
    return False


def _fill(profile: Profile):
    folder = paths.profile_dir(profile.id)

    def keep(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
        relative = info.name.removeprefix("profile").lstrip("/")
        if relative and skipped(relative):
            return None
        if not (info.isfile() or info.isdir() or info.issym()):
            return None  # sockets, fifos: nothing a profile needs
        return info

    def fill(tar: tarfile.TarFile) -> None:
        tar.add(folder, arcname="profile", filter=keep)

    return fill


def engine_version(profile: Profile) -> str | None:
    """The engine version the profile runs: the fingerprint's for Camoufox, the
    pinned or newest installed one otherwise."""
    from .engines import installed_versions

    if profile.engine == "camoufox":
        try:
            return store.load_fingerprint(profile.id).engine_version
        except store.StoreError:
            return None
    if profile.engine_version:
        return profile.engine_version
    have = installed_versions(profile.engine)
    return have[-1] if have else None


def _extra(profile: Profile) -> dict:
    ex = None
    if profile.exit:
        try:
            ex = store.exit_of(profile)
        except store.StoreError:
            ex = None
    return {
        "engine": profile.engine,
        "engine_version": engine_version(profile),
        "exit": profile.exit,
        "exit_name": ex.name if ex else None,
        "tags": list(profile.tags),
    }


# --------------------------------------------------------------------- take
def take(profile: Profile, *, aside: bool = False, supersede=None):
    """Snapshot a stopped profile now."""
    _require()
    if launch.running(profile):
        raise snap.SnapshotError(f"{profile.name} is running; stop it first")
    return snap.take(
        KIND,
        profile.id,
        profile.name,
        _fill(profile),
        extra=_extra(profile),
        aside=aside,
        supersede=supersede,
        app="kiwi-fox",
        version=__version__,
    )


def _settings():
    return snap.load_settings() if snap is not None else None


def after_stop(profile: Profile) -> str | None:
    """The profile's browser has stopped: say so in the folder, and snapshot the
    profile when it ran (or changed) since its last snapshot. A line to show when
    something did not work; never raises."""
    s = _settings()
    if s is None:
        return None
    with contextlib.suppress(snap.SnapshotError, OSError):
        snap.clear_in_use(KIND, profile.id)
    if not s.automatic or launch.running(profile):
        return None
    try:
        rel = snap.relation(KIND, profile.id, here=True)
        if rel.state in ("same", "folder_newer"):
            return None  # nothing new here
        take(profile)
    except snap.Locked:
        return f"{profile.name}: no snapshot taken, snapshots are locked on this device"
    except (snap.SnapshotError, OSError) as exc:
        return f"{profile.name}: no snapshot taken: {exc}"
    return None


def changed(profile: Profile) -> str | None:
    """The profile's settings changed: snapshot it now if it is stopped (the next
    stop does it otherwise)."""
    if _settings() is None:
        return None
    snap.mark_changed(KIND, profile.id)
    if launch.running(profile):
        return None
    return after_stop(profile)


def started(profile: Profile) -> None:
    """The browser is starting: this copy changes from now on, and the folder may
    say where it is in use. Best effort; a start never fails on snapshots."""
    if _settings() is None:
        return
    snap.mark_changed(KIND, profile.id)
    with contextlib.suppress(snap.SnapshotError, OSError):
        snap.mark_in_use(KIND, profile.id)


@dataclass
class StartCheck:
    """What the folder says before a profile starts."""

    relation: object | None = None  # kiwi_proxy.snapshots.Relation
    in_use: list = None  # [(device, since)]

    @property
    def newer_elsewhere(self) -> bool:
        return bool(self.relation and self.relation.newer_elsewhere)

    @property
    def needs_asking(self) -> bool:
        return self.newer_elsewhere or bool(self.in_use)


def before_start(profile: Profile) -> StartCheck:
    """Look before starting: a newer copy in the folder, or the profile in use on
    another device. Nothing when snapshots are off, locked or not set up."""
    s = _settings()
    if s is None:
        return StartCheck(None, [])
    try:
        rel = snap.relation(KIND, profile.id, here=True)
        in_use = snap.in_use_elsewhere(KIND, profile.id)
    except (snap.SnapshotError, OSError):
        return StartCheck(None, [])
    return StartCheck(rel if s.ask_older else None, in_use)


def keep_mine(profile: Profile, check: StartCheck):
    """ "Keep this device's": snapshot this copy over the other device's lines."""
    rel = check.relation
    return take(profile, supersede=getattr(rel, "heads", None))


# ------------------------------------------------------------------- restore
class RestoreError(store.StoreError):
    pass


def missing_exit(meta) -> str | None:
    """The exit a snapshot's profile uses, when this device does not have it."""
    from kiwi_proxy import exits

    exit_id = meta.extra.get("exit")
    if exit_id and not exits.exists(exit_id):
        return meta.extra.get("exit_name") or exit_id[:8]
    return None


def restore(profile_id: str, sid: str) -> Profile:
    """Put snapshot `sid` of a profile in place. Refused while the profile runs,
    and when its exit is not on this device (Kiwi Proxy restores exits, Kiwi Fox
    does not). This device's copy, when it has changes no snapshot holds, is kept
    as a snapshot first. The downloads folder stays as it is."""
    _require()
    metas = snap.history(KIND, profile_id)
    meta = next((m for m in metas if m.id == sid or m.id.startswith(sid)), None)
    if meta is None:
        raise RestoreError(f"no snapshot {sid} of this profile in the folder")
    if name := missing_exit(meta):
        raise RestoreError(
            f"{meta.name} goes out through the exit {name}, which is not on this device: "
            f"restore {name} in Kiwi Proxy first"
        )
    target = paths.profile_dir(profile_id)
    here = (target / "profile.json").is_file()
    if here:
        current = store.load(profile_id)
        if launch.running(current):
            raise RestoreError(f"{current.name} is running; stop it first")

    def apply(staging: Path, _meta) -> None:
        incoming = staging / "profile"
        if not (incoming / "profile.json").is_file():
            raise RestoreError("the snapshot holds no profile")
        downloads = target / "downloads"
        if downloads.is_dir():
            os.rename(downloads, incoming / "downloads")
        else:
            (incoming / "downloads").mkdir(exist_ok=True)
        old = target.with_name(f".{target.name}.old-{os.urandom(4).hex()}")
        if target.exists():
            os.rename(target, old)
        try:
            os.rename(incoming, target)
        except OSError:
            if old.exists():
                os.rename(old, target)
            raise
        shutil.rmtree(old, ignore_errors=True)

    keep = (lambda: take(store.load(profile_id), aside=True)) if here else None
    paths.profiles_dir().mkdir(parents=True, exist_ok=True)
    snap.restore(
        KIND,
        profile_id,
        meta.id,
        apply,
        here=here,
        keep_current=keep,
        staging_root=paths.data_dir(),
    )
    profile = store.load(profile_id)
    store.save(profile)  # its app-grid entry follows it
    return profile


def missing_engine(profile: Profile) -> tuple[str, str] | None:
    """(engine, version) the profile needs and this device lacks."""
    from .engines import installed_versions

    version = engine_version(profile)
    if profile.engine == "camoufox":
        if version and version not in installed_versions("camoufox"):
            return "camoufox", version
        return None
    have = installed_versions(profile.engine)
    if profile.engine_version and profile.engine_version not in have:
        return profile.engine, profile.engine_version
    if not have:
        return profile.engine, profile.engine_version or "newest"
    return None


def fetch_hint(engine: str, version: str) -> str:
    """The command that installs it."""
    if engine == "camoufox":
        return f"kiwi-fox engine fetch {version}"
    if version == "newest":
        return f"kiwi-fox engine fetch --engine {engine}"
    return f"kiwi-fox engine fetch {version} --engine {engine}"


def fetch_engine(engine: str, version: str, progress=None) -> None:
    """Download and verify an engine version (the same as `kiwi-fox engine
    fetch`)."""
    from .engines import fetch as camoufox_fetch
    from .engines import firefox_fetch, torbrowser_fetch

    wanted = None if version == "newest" else version
    if engine == "camoufox":
        camoufox_fetch.fetch(wanted)
    elif engine == "firefox":
        firefox_fetch.fetch(wanted, progress=progress)
    else:
        torbrowser_fetch.fetch(wanted, progress=progress)


# ------------------------------------------------------------------- listing
def away() -> list[tuple[str, str, list]]:
    """Profiles in the folder that are not on this device: (id, name, snapshots
    newest first)."""
    if _settings() is None:
        return []
    here = {p.id for p in store.list_profiles()}
    out = []
    for (kind, item), metas in snap.catalog((KIND,)).items():
        if kind == KIND and item not in here:
            out.append((item, metas[0].name, metas))
    return sorted(out, key=lambda a: a[1])


def find_in_folder(ref: str) -> tuple[str, str]:
    """A profile in the folder by name or id prefix: (id, name)."""
    _require()
    metas = [m for m in snap.folder().metas() if m.kind == KIND]
    named = [m for m in metas if m.name == ref] or [m for m in metas if m.item.startswith(ref)]
    items = {m.item for m in named}
    if not items:
        raise RestoreError(f"no profile {ref!r} in the snapshot folder")
    if len(items) > 1:
        raise RestoreError(
            f"{ref!r} names {len(items)} different profiles in the folder; use its id"
        )
    return named[0].item, named[0].name
