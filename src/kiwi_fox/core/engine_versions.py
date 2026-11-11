"""Engine versions: what each engine has released, what is installed, which
profiles use what, pins, the version new profiles get, and new releases.

- **Camoufox** profiles carry their version in their fingerprint; a profile stays
  on it until moved (:func:`move`, checked by the fingerprint validator).
- **Firefox and Tor Browser** profiles either follow (``engine_version`` None:
  the engine's default from the preferences, else the newest installed) or are
  pinned to one version (:func:`pin`).
- **Tor Browser** is never offered or installed below ``torbrowser_fetch.MIN_VERSION``;
  pinning an older one than the newest installed comes with a warning.
- **New releases** (:func:`news`): the preference says tell (default), install
  by itself, or nothing. The release lists are cached for six hours.

A version some profile uses cannot be removed. Installing never removes one.
"""

from __future__ import annotations

import json
import re
import shutil
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import paths, settings, store
from .engines import TITLES, firefox_fetch, installed_versions, torbrowser_fetch
from .engines import fetch as camoufox_fetch
from .models import Profile

ENGINES = ("camoufox", "firefox", "torbrowser")
CACHE_SECONDS = 6 * 3600
FIREFOX_RELEASES = "https://product-details.mozilla.org/1.0/firefox.json"
TORBROWSER_DIST = "https://dist.torproject.org/torbrowser/"
SHOWN = 15  # releases per engine the list keeps


class VersionError(RuntimeError):
    pass


def key(version: str) -> tuple[int, ...]:
    return tuple(int(p) if p.isdigit() else 0 for p in re.split(r"[.a-z]", version))


# ------------------------------------------------------------------ releases
@dataclass
class Release:
    version: str
    beta: bool = False


def _get(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "kiwi-fox"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return resp.read()


def _fetch_releases(engine: str) -> list[Release]:
    if engine == "camoufox":
        out = []
        for rel in camoufox_fetch._get_json(camoufox_fetch.API_ALL):
            if rel.get("draft"):
                continue
            for asset in rel.get("assets", []):
                m = camoufox_fetch.ASSET_RE.match(asset.get("name", ""))
                if m:
                    out.append(Release(m["ver"], beta=bool(rel.get("prerelease"))))
        return out
    if engine == "firefox":
        data = json.loads(_get(FIREFOX_RELEASES))
        out = []
        for info in (data.get("releases") or {}).values():
            if info.get("category") in ("major", "stability") and info.get("version"):
                out.append(Release(str(info["version"])))
        return out
    if engine == "torbrowser":
        html = _get(TORBROWSER_DIST).decode("utf-8", "replace")
        found = set(re.findall(r'href="(\d+\.\d+(?:\.\d+)?)/"', html))
        floor = torbrowser_fetch._version_key(torbrowser_fetch.MIN_VERSION)
        return [Release(v) for v in found if torbrowser_fetch._version_key(v) >= floor]
    raise VersionError(f"unknown engine {engine!r}")


def _cache() -> Path:
    return paths.cache_dir() / "engine-releases.json"


def releases(engine: str, *, refresh: bool = False) -> list[Release]:
    """The engine's releases, newest first (at most SHOWN, plus every installed
    one); cached six hours, a stale cache when the network is away, [] with
    neither."""
    cache = _cache()
    data: dict = {}
    try:
        data = json.loads(cache.read_text())
    except (OSError, ValueError):
        data = {}
    entry = data.get(engine) or {}
    fresh = entry and time.time() - entry.get("at", 0) < CACHE_SECONDS
    if refresh or not fresh:
        try:
            found = _fetch_releases(engine)
            if found:
                entry = {"at": time.time(), "releases": [[r.version, r.beta] for r in found]}
                data[engine] = entry
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps(data))
        except Exception:  # noqa: BLE001 - the network, an API change
            pass
    found = [Release(v, b) for v, b in entry.get("releases", [])]
    unique = {r.version: r for r in found}
    ordered = sorted(unique.values(), key=lambda r: key(r.version), reverse=True)[:SHOWN]
    have = {r.version for r in ordered}
    ordered += [Release(v) for v in installed_versions(engine) if v not in have]
    return sorted(ordered, key=lambda r: key(r.version), reverse=True)


def newest(engine: str) -> str | None:
    """The newest stable release (Camoufox betas are not offered as an update)."""
    stable = [r for r in releases(engine) if not r.beta]
    return stable[0].version if stable else None


# -------------------------------------------------------------- what is used
def version_of(profile: Profile) -> str | None:
    """The engine version the profile starts with now (None: none installed)."""
    if profile.engine == "camoufox":
        fp = store.fingerprint_of(profile)
        return fp.engine_version if fp else None
    if profile.engine_version:
        return profile.engine_version
    default = default_for(profile.engine)
    have = installed_versions(profile.engine)
    if default and default in have:
        return default
    return have[-1] if have else None


def pinned(profile: Profile) -> bool:
    return profile.engine == "camoufox" or bool(profile.engine_version)


def users(engine: str, version: str) -> list[Profile]:
    return [p for p in store.list_profiles() if p.engine == engine and version_of(p) == version]


def default_for(engine: str) -> str:
    """What the preferences say new (Camoufox) or unpinned (Firefox, Tor
    Browser) profiles use; "" for the engine's own choice."""
    return getattr(settings.load(), f"{engine}_default", "") or ""


def set_default(engine: str, version: str) -> None:
    if version and version not in installed_versions(engine):
        raise VersionError(f"{TITLES[engine]} {version} is not installed")
    s = settings.load()
    setattr(s, f"{engine}_default", version)
    settings.save(s)


def for_new_profile(engine: str) -> str | None:
    """The version a new profile is made with: Camoufox's default (else the
    preferred installed one); None for Firefox and Tor Browser, which follow."""
    if engine != "camoufox":
        return None
    default = default_for("camoufox")
    if default and default in installed_versions("camoufox"):
        return default
    return camoufox_fetch.preferred()


# ------------------------------------------------------------ install/remove
def target_dir(engine: str, version: str) -> Path:
    return {
        "camoufox": camoufox_fetch.target_dir,
        "firefox": firefox_fetch.target_dir,
        "torbrowser": torbrowser_fetch.target_dir,
    }[engine](version)


def install(engine: str, version: str | None = None, *, progress=None) -> str:
    """Download, verify and install; the version installed."""
    if engine == "camoufox":
        from .setup import prepare_camoufox

        path = camoufox_fetch.fetch(version, allow_prerelease=bool(version), progress=progress)
        installed = path.name.removeprefix("camoufox-")
        prepare_camoufox(installed)
        return installed
    if engine == "firefox":
        return firefox_fetch.fetch(version, progress=progress).name.removeprefix("firefox-")
    if engine == "torbrowser":
        return torbrowser_fetch.fetch(version, progress=progress).name.removeprefix("torbrowser-")
    raise VersionError(f"unknown engine {engine!r}")


def remove(engine: str, version: str) -> None:
    """Remove an installed version no profile uses; the error names the ones that do."""
    if version not in installed_versions(engine):
        raise VersionError(f"{TITLES[engine]} {version} is not installed")
    if used := users(engine, version):
        names = ", ".join(p.name for p in used)
        raise VersionError(f"{TITLES[engine]} {version} is in use: {names}")
    if default_for(engine) == version:
        set_default(engine, "")
    shutil.rmtree(target_dir(engine, version))


# ---------------------------------------------------------------- per profile
def pin(profile: Profile, version: str | None) -> tuple[Profile, list[str]]:
    """Pin a Firefox or Tor Browser profile to an installed version, or let it
    follow (None). Warnings to show (an old Tor Browser)."""
    if profile.engine == "camoufox":
        raise VersionError("a Camoufox profile moves with its fingerprint: use Move to version")
    warnings: list[str] = []
    if version is not None:
        if version not in installed_versions(profile.engine):
            raise VersionError(f"{TITLES[profile.engine]} {version} is not installed")
        if profile.engine == "torbrowser":
            if torbrowser_fetch._version_key(version) < torbrowser_fetch._version_key(
                torbrowser_fetch.MIN_VERSION
            ):
                raise VersionError(
                    f"Tor Browser {version} is below the {torbrowser_fetch.MIN_VERSION} floor"
                )
            newest_here = installed_versions("torbrowser")[-1]
            if key(version) < key(newest_here):
                warnings.append(
                    f"Tor Browser {version} is older than {newest_here}: it stands out among Tor "
                    "users and misses security fixes"
                )
    updated = profile.model_copy(update={"engine_version": version})
    store.save(updated)
    return updated, warnings


def move(profile: Profile, version: str) -> tuple[list[str], list[str]]:
    """Move a Camoufox profile to another installed version: its fingerprint is
    checked against that version first. -> (errors that refused it, warnings)."""
    from .fingerprint import edit, validate
    from .fingerprint.validator import errors

    if profile.engine != "camoufox":
        raise VersionError("only a Camoufox profile moves; pin a Firefox or Tor Browser profile")
    if version not in installed_versions("camoufox"):
        raise VersionError(f"Camoufox {version} is not installed")
    fp = store.fingerprint_of(profile)
    if fp is None:
        raise VersionError(f"{profile.name} has no fingerprint")
    from .fingerprint import windows11 as w11

    # the user agent names the engine's major version: it moves with it
    new = fp.model_copy(update={"engine_version": version, "ua": w11.ua_for(version)})
    issues = validate(new, engine_version=version)
    hard = [str(i) for i in errors(issues)]
    warn = [str(i) for i in issues if i.level == "warn"]
    if profile.user_agent:
        warn += [
            f"custom user agent: {n}" for n in edit.check_user_agent(profile.user_agent, version)
        ]
    if hard:
        return hard, warn
    store.save_fingerprint(profile.id, new)
    return [], warn


def downgrading(profile: Profile, version: str) -> bool:
    """The profile's browser data was last used by a newer version than this one
    (Firefox then refuses it unless told to allow the downgrade)."""
    ini = paths.profile_dir(profile.id) / "browser-data" / "compatibility.ini"
    try:
        for line in ini.read_text().splitlines():
            if line.startswith("LastVersion="):
                last = line.split("=", 1)[1].split("_", 1)[0]
                return key(last)[:3] > key(version)[:3]
    except OSError:
        pass
    return False


# ------------------------------------------------------------------ updates
@dataclass
class News:
    engine: str
    version: str
    installed: bool = False  # installed by itself (mode "auto")
    error: str = ""


@dataclass
class Check:
    news: list[News] = field(default_factory=list)
    checked: bool = False  # False: not due yet, or the mode is off


def _state() -> Path:
    return paths.config_dir() / "engine-news.json"


def news(*, force: bool = False, install_auto: bool = True) -> Check:
    """New stable releases of engines this device has, at most once a day unless
    forced. Mode "auto" installs them (when `install_auto`); "tell" reports them
    once per version; "off" does nothing."""
    mode = settings.load().engine_updates
    if mode == "off" and not force:
        return Check()
    try:
        state = json.loads(_state().read_text())
    except (OSError, ValueError):
        state = {}
    if not force and time.time() - state.get("at", 0) < 24 * 3600:
        return Check()
    out = Check(checked=True)
    told = set(state.get("told", []))
    for engine in ENGINES:
        have = installed_versions(engine)
        if not have:
            continue  # an engine this device does not use
        latest = (
            newest(engine) if not force else (releases(engine, refresh=True) and newest(engine))
        )
        if not latest or latest in have or key(latest) <= key(have[-1]):
            continue
        item = News(engine, latest)
        if mode == "auto" and install_auto:
            try:
                install(engine, latest)
                item.installed = True
            except Exception as exc:  # noqa: BLE001 - a download, a signature
                item.error = str(exc)
        elif f"{engine}-{latest}" in told and not force:
            continue
        told.add(f"{engine}-{latest}")
        out.news.append(item)
    state = {"at": time.time(), "told": sorted(told)}
    _state().parent.mkdir(parents=True, exist_ok=True)
    _state().write_text(json.dumps(state))
    return out
