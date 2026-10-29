"""Load and save profiles. One directory per profile, JSON on disk.

Every profile has an exit in kiwi-proxy — the upstream its gateway leaves
through — registered under the profile's own id with owner "kiwi-fox". Once it
exists the exit is where the endpoint and DNS settings live (`kiwi-proxy set`
edits them too): `load` reads them from it, `save` writes them to it, and
profile.json keeps a copy so a profile still loads on its own.
"""

from __future__ import annotations

import datetime as dt
import uuid
from pathlib import Path

from kiwi_proxy import exits
from kiwi_proxy.models import Exit

from . import paths, secrets
from .models import DnsConfig, Endpoint, EngineName, Fingerprint, Profile

OWNER = "kiwi-fox"


class StoreError(RuntimeError):
    pass


def _write_json(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload)
    tmp.replace(path)


def create(
    name: str,
    endpoint: Endpoint,
    fingerprint: Fingerprint | None = None,
    *,
    engine: EngineName = "camoufox",
    engine_version: str | None = None,
    password: str | None = None,
    dns: DnsConfig | None = None,
    notes: str = "",
) -> Profile:
    if find_by_name(name):
        raise StoreError(f"a profile named {name!r} already exists")
    if exits.find_by_name(name):
        raise StoreError(f"kiwi-proxy already has an exit named {name!r}; pick another name")
    # The engine/fingerprint contract, checked before anything is written: a
    # camoufox profile carries a fingerprint, the non-spoofing engines carry none.
    if engine == "camoufox":
        if fingerprint is None:
            raise StoreError("a camoufox profile needs a fingerprint")
    elif fingerprint is not None:
        raise StoreError(f"a {engine} profile has no fingerprint")
    profile = Profile(
        id=str(uuid.uuid4()),
        name=name,
        created=dt.datetime.now(dt.UTC),
        engine=engine,
        engine_version=engine_version,
        endpoint=endpoint,
        dns=dns or DnsConfig(),
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
    if password:
        secrets.store(profile.id, password, label=f"kiwi-fox {name}")
    return profile


def save(profile: Profile) -> None:
    _write_json(paths.profile_dir(profile.id) / "profile.json", profile.model_dump_json(indent=2))
    _write_json(paths.profile_dir(profile.id) / "dns.json", profile.dns.model_dump_json(indent=2))
    sync_exit(profile)


# --------------------------------------------------------------------- exits
def exit_dns(profile: Profile) -> DnsConfig:
    """Tor Browser hands every name to Tor (its proxy settings force remote DNS);
    a resolver in the namespace would answer from somewhere Tor does not choose."""
    if profile.engine == "torbrowser":
        return profile.dns.model_copy(update={"mode": "remote"})
    return profile.dns.model_copy(deep=True)


def exit_socks_auth(profile: Profile) -> str:
    """Tor Browser sends its own per-site SOCKS credentials for circuit isolation;
    the forwarder carries them upstream behind the profile's token."""
    return "passthrough" if profile.engine == "torbrowser" else "inject"


def _exit_name(profile: Profile, current: str | None = None) -> str:
    taken = exits.find_by_name(profile.name)
    if taken is None or taken.id == profile.id:
        return profile.name
    # An exit made with the kiwi-proxy CLI has the name. kiwi-fox finds its exit
    # by id, so the name is only a label there: keep the one it has.
    return current or f"{profile.name}-{profile.id[:8]}"


def sync_exit(profile: Profile) -> Exit:
    """The profile's exit, created or brought in line with the profile."""
    wanted = {
        "endpoint": profile.endpoint.model_copy(deep=True),
        "dns": exit_dns(profile),
        "socks_auth": exit_socks_auth(profile),
    }
    if exits.exists(profile.id):
        ex = exits.load(profile.id)
        updated = ex.model_copy(update={**wanted, "name": _exit_name(profile, ex.name)})
        if updated != ex:
            exits.save(updated)
        return updated
    ex = exits.create(
        _exit_name(profile),
        wanted["endpoint"],
        dns=wanted["dns"],
        exit_id=profile.id,
        owner=OWNER,
    )
    if ex.socks_auth != wanted["socks_auth"]:
        ex.socks_auth = wanted["socks_auth"]  # type: ignore[assignment]
        exits.save(ex)
    return ex


def _from_exit(profile: Profile) -> Profile:
    try:
        ex = exits.load(profile.id)
    except Exception:  # noqa: BLE001 - no exit yet (a profile from before kiwi-proxy), or a broken one
        return profile
    profile.endpoint, profile.dns = ex.endpoint, ex.dns
    return profile


def save_fingerprint(profile_id: str, fp: Fingerprint) -> None:
    _write_json(paths.profile_dir(profile_id) / "fingerprint.json", fp.model_dump_json(indent=2))


def load(profile_id: str) -> Profile:
    path = paths.profile_dir(profile_id) / "profile.json"
    if not path.exists():
        raise StoreError(f"no such profile {profile_id!r}")
    return _from_exit(Profile.model_validate_json(path.read_text()))


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
    import shutil

    secrets.clear(profile_id)
    exits.delete(profile_id)
    pdir = paths.profile_dir(profile_id)
    if purge:
        shutil.rmtree(pdir, ignore_errors=True)
    else:
        shutil.rmtree(pdir / "browser-data", ignore_errors=True)
        (pdir / "retired").write_text(dt.datetime.now(dt.UTC).isoformat())


def touch(profile: Profile) -> None:
    profile.last_used = dt.datetime.now(dt.UTC)
    save(profile)
