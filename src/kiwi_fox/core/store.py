"""Load and save profiles. One directory per profile, JSON on disk.

A profile's traffic leaves through a kiwi-proxy exit — a proxy the user defined
there (`kiwi-proxy add`, the Kiwi-Proxy app, or kiwi-fox's own shortcut), shared
with whatever else is on it — or through no proxy at all. The profile keeps only
the exit's id; everything about the exit (endpoint, credentials, DNS, blocklists)
is kiwi-proxy's.

Until 0.3 a profile carried its endpoint itself and owned one exit under its own
id. `load` migrates such a profile the first time it is seen: the exit it owned
becomes the proxy it references, so gateway names and Tor tokens stay what they
were, and its password moves from kiwi-fox's keyring into kiwi-proxy's store.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import uuid
from pathlib import Path

from kiwi_proxy import exits
from kiwi_proxy import secrets as proxy_secrets
from kiwi_proxy.models import Exit

from . import desktop, paths, secrets
from .models import DnsConfig, EngineName, Fingerprint, Profile

OWNER = "kiwi-fox"
# Tor Browser exits only through the tor module: its per-site circuits are the
# SOCKS credentials the forwarder passes through, and .onion resolves only at a
# Tor exit.
TOR_MODULE = "tor"


class StoreError(RuntimeError):
    pass


def _write_json(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload)
    tmp.replace(path)


# --------------------------------------------------------------------- exits
def exit_of(profile: Profile) -> Exit | None:
    """The kiwi-proxy exit the profile uses, or None for no proxy."""
    if not profile.exit:
        return None
    try:
        return exits.load(profile.exit)
    except exits.ExitError as exc:
        raise StoreError(
            f"{profile.name}: its exit ({profile.exit[:8]}) is gone from kiwi-proxy; give it "
            f"another with `kiwi-fox set {profile.name} --exit NAME`, or --no-proxy"
        ) from exc


def exit_label(ex: Exit | None) -> str:
    """Where a profile exits, the way a person reads it: the proxy's name, or none."""
    return ex.name if ex else "no proxy"


def describe_exit(ex: Exit | None) -> str:
    """The proxy and what is behind it: "kiwi-master-tor · 10.8.0.1:9050 · dns remote"."""
    if ex is None:
        return "no proxy — this machine's own connection"
    from . import modules

    bits = [ex.name, modules.exit_label(ex.endpoint), f"dns {ex.dns.mode}"]
    bits.append(f"lists {','.join(ex.dns.blocklists)}" if ex.dns.blocklists else "no ad-blocking")
    return " · ".join(bits)


def check_tor_exit(ex: Exit | None) -> None:
    """A browser rule, beside kiwi-proxy's own: Tor Browser needs an exit on the tor
    module that passes its per-site SOCKS credentials through."""
    if ex is None or ex.endpoint.module != TOR_MODULE:
        raise StoreError(
            "a Tor Browser profile exits only through the tor module: use an exit on it "
            "(--module tor creates one; so does `kiwi-proxy add NAME --module tor`)"
        )
    if ex.socks_auth != "passthrough":
        raise StoreError(
            f"exit {ex.name!r} does not pass SOCKS auth through, which Tor Browser's per-site "
            f"circuits need: kiwi-proxy set {ex.name} --socks-auth passthrough"
        )


def normalize_tags(values: list[str]) -> list[str]:
    """Tags as typed — comma-separated or one per value, a leading # allowed —
    trimmed, empty ones dropped, duplicates (case-insensitively) dropped, the
    first spelling kept."""
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        for raw in value.split(","):
            tag = raw.strip().lstrip("#").strip()
            if tag and tag.lower() not in seen:
                seen.add(tag.lower())
                out.append(tag)
    return out


def profiles_on(exit_id: str) -> list[Profile]:
    return [p for p in list_profiles() if p.exit == exit_id]


def _drop_exit_if_unused(exit_id: str, *, leaving: str) -> bool:
    """An exit kiwi-fox registered itself (0.3 made one per profile, owner
    kiwi-fox) goes with its last profile; the user's own, made in kiwi-proxy,
    stay. kiwi-fox makes no exits any more."""
    try:
        ex = exits.load(exit_id)
    except exits.ExitError:
        return False
    if ex.owner != OWNER or any(p.id != leaving for p in profiles_on(exit_id)):
        return False
    exits.delete(exit_id)
    return True


# ------------------------------------------------------------------ profiles
def create(
    name: str,
    exit_id: str | None,
    fingerprint: Fingerprint | None = None,
    *,
    engine: EngineName = "camoufox",
    engine_version: str | None = None,
    notes: str = "",
) -> Profile:
    if find_by_name(name):
        raise StoreError(f"a profile named {name!r} already exists")
    ex = None
    if exit_id:
        try:
            ex = exits.load(exit_id)
        except exits.ExitError as exc:
            raise StoreError(f"kiwi-proxy has no exit {exit_id!r}") from exc
    # The engine/fingerprint contract, checked before anything is written: a
    # camoufox profile carries a fingerprint, the non-spoofing engines carry none.
    if engine == "camoufox":
        if fingerprint is None:
            raise StoreError("a camoufox profile needs a fingerprint")
    elif fingerprint is not None:
        raise StoreError(f"a {engine} profile has no fingerprint")
    if engine == "torbrowser":
        check_tor_exit(ex)
    profile = Profile(
        id=str(uuid.uuid4()),
        name=name,
        created=dt.datetime.now(dt.UTC),
        engine=engine,
        engine_version=engine_version,
        exit=ex.id if ex else None,
        notes=notes,
    )
    pdir = paths.profile_dir(profile.id)
    for sub in ("browser-data", "downloads"):
        (pdir / sub).mkdir(parents=True, exist_ok=True)
    # The fingerprint first: list_profiles keys on profile.json, so a crash
    # between the two writes leaves a camoufox profile invisible rather than one
    # that loads but has no fingerprint.
    if fingerprint is not None:
        save_fingerprint(profile.id, fingerprint)
    save(profile)
    return profile


def entry_description(profile: Profile) -> str:
    """The browser and the proxy, for the profile's desktop entry."""
    from .engines import TITLES

    try:
        where = exit_label(exit_of(profile))
    except StoreError:
        where = "proxy missing"
    return f"{TITLES[profile.engine]} · {where}"


def save(profile: Profile) -> None:
    _write_json(paths.profile_dir(profile.id) / "profile.json", profile.model_dump_json(indent=2))
    # The app-grid entry follows the profile: written while it wants one (a rename
    # rewrites it), removed as soon as it does not.
    desktop.sync_entry(profile, entry_description(profile))


def save_fingerprint(profile_id: str, fp: Fingerprint) -> None:
    _write_json(paths.profile_dir(profile_id) / "fingerprint.json", fp.model_dump_json(indent=2))


def load(profile_id: str) -> Profile:
    path = paths.profile_dir(profile_id) / "profile.json"
    if not path.exists():
        raise StoreError(f"no such profile {profile_id!r}")
    return _migrate(Profile.model_validate_json(path.read_text()))


def _migrate(profile: Profile) -> Profile:
    """A profile from before 0.4: endpoint and DNS on the profile, an exit under its
    own id (0.3 registered it at setup or at launch; one that never got it gets it
    now). That exit becomes the proxy the profile references, named as it is, so
    nothing in podman changes: the gateway is still kf-gw-<profile id[:12]> and the
    Tor token kf-<profile id[:16]>. The password moves from kiwi-fox's keyring into
    kiwi-proxy's store under the exit's id, where every exit's lives."""
    if profile.exit or profile.endpoint is None:
        return profile
    tor_browser = profile.engine == "torbrowser"
    if not exits.exists(profile.id):
        name = profile.name
        if exits.find_by_name(name) is not None:
            name = f"{profile.name}-{profile.id[:8]}"
        dns = profile.dns or DnsConfig()
        if tor_browser:
            dns = dns.model_copy(update={"mode": "remote"})
        exits.create(
            name,
            profile.endpoint,
            dns=dns,
            exit_id=profile.id,
            owner=OWNER,
            socks_auth="passthrough" if tor_browser else None,
        )
    with contextlib.suppress(Exception):  # a keyring hiccup must not stop a load
        password = secrets.lookup(profile.id)
        if password and not proxy_secrets.lookup(profile.id, kind="endpoint"):
            proxy_secrets.store(
                profile.id, password, kind="endpoint", label=f"kiwi-proxy {profile.name}"
            )
    profile.exit = profile.id
    profile.endpoint = None
    profile.dns = None
    (paths.profile_dir(profile.id) / "dns.json").unlink(missing_ok=True)
    save(profile)
    return profile


def load_fingerprint(profile_id: str) -> Fingerprint:
    path = paths.profile_dir(profile_id) / "fingerprint.json"
    if not path.exists():
        raise StoreError(f"profile {profile_id!r} has no fingerprint")
    return Fingerprint.model_validate_json(path.read_text())


def fingerprint_of(profile: Profile) -> Fingerprint | None:
    """The profile's fingerprint, or None for a non-spoofing engine.

    A camoufox profile with its fingerprint.json missing still raises (via
    load_fingerprint): that is a broken profile, not a fingerprint-less one.
    """
    if profile.engine != "camoufox":
        return None
    return load_fingerprint(profile.id)


def list_profiles() -> list[Profile]:
    root = paths.profiles_dir()
    if not root.exists():
        return []
    out = []
    for d in sorted(root.iterdir()):
        if (d / "profile.json").exists():
            try:
                out.append(load(d.name))
            except Exception:  # noqa: BLE001 - a broken profile must not hide the others
                continue
    return sorted(out, key=lambda p: p.name)


def find_by_name(name: str) -> Profile | None:
    return next((p for p in list_profiles() if p.name == name), None)


def resolve_ref(ref: str) -> Profile:
    """Accept a name or an id prefix, the way git accepts a short sha."""
    if found := find_by_name(ref):
        return found
    matches = [p for p in list_profiles() if p.id.startswith(ref)]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise StoreError(f"no profile matches {ref!r}")
    raise StoreError(f"{ref!r} is ambiguous: {[p.name for p in matches]}")


def delete(profile_id: str, *, purge: bool = False) -> None:
    """The profile goes; an exit kiwi-fox 0.3 registered for it goes with its last
    profile, one the user made in kiwi-proxy stays."""
    import shutil

    exit_id = None
    with contextlib.suppress(Exception):  # a broken profile is still deletable
        exit_id = load(profile_id).exit
    secrets.clear(profile_id)  # a 0.3 keyring entry, if one is left
    desktop.remove_entry(profile_id)
    if exit_id:
        _drop_exit_if_unused(exit_id, leaving=profile_id)
    pdir = paths.profile_dir(profile_id)
    if purge:
        shutil.rmtree(pdir, ignore_errors=True)
    else:
        shutil.rmtree(pdir / "browser-data", ignore_errors=True)
        (pdir / "retired").write_text(dt.datetime.now(dt.UTC).isoformat())


def touch(profile: Profile) -> None:
    profile.last_used = dt.datetime.now(dt.UTC)
    save(profile)
