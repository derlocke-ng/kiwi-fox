"""Load and save profiles. One directory per profile, JSON on disk."""

from __future__ import annotations

import datetime as dt
import json
import uuid
from pathlib import Path

from . import paths, secrets
from .models import DnsConfig, Endpoint, Fingerprint, Profile, ProviderRecord


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
    fingerprint: Fingerprint,
    *,
    password: str | None = None,
    dns: DnsConfig | None = None,
    notes: str = "",
) -> Profile:
    if find_by_name(name):
        raise StoreError(f"a profile named {name!r} already exists")
    profile = Profile(
        id=str(uuid.uuid4()),
        name=name,
        created=dt.datetime.now(dt.UTC),
        endpoint=endpoint,
        dns=dns or DnsConfig(),
        notes=notes,
    )
    pdir = paths.profile_dir(profile.id)
    for sub in ("browser-data", "downloads"):
        (pdir / sub).mkdir(parents=True, exist_ok=True)
    save(profile)
    save_fingerprint(profile.id, fingerprint)
    if password:
        secrets.store(profile.id, password, label=f"kiwi-fox {name}")
    return profile


def save(profile: Profile) -> None:
    _write_json(paths.profile_dir(profile.id) / "profile.json", profile.model_dump_json(indent=2))
    _write_json(paths.profile_dir(profile.id) / "dns.json", profile.dns.model_dump_json(indent=2))


def save_fingerprint(profile_id: str, fp: Fingerprint) -> None:
    _write_json(paths.profile_dir(profile_id) / "fingerprint.json", fp.model_dump_json(indent=2))


def load(profile_id: str) -> Profile:
    path = paths.profile_dir(profile_id) / "profile.json"
    if not path.exists():
        raise StoreError(f"no such profile {profile_id!r}")
    return Profile.model_validate_json(path.read_text())


def load_fingerprint(profile_id: str) -> Fingerprint:
    path = paths.profile_dir(profile_id) / "fingerprint.json"
    if not path.exists():
        raise StoreError(f"profile {profile_id!r} has no fingerprint")
    return Fingerprint.model_validate_json(path.read_text())


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
    pdir = paths.profile_dir(profile_id)
    if purge:
        shutil.rmtree(pdir, ignore_errors=True)
    else:
        shutil.rmtree(pdir / "browser-data", ignore_errors=True)
        (pdir / "retired").write_text(dt.datetime.now(dt.UTC).isoformat())


def touch(profile: Profile) -> None:
    profile.last_used = dt.datetime.now(dt.UTC)
    save(profile)


# ------------------------------------------------------------ provider cache
def load_providers() -> list[ProviderRecord]:
    path = paths.providers_cache()
    if not path.exists():
        return []
    return [ProviderRecord.model_validate(r) for r in json.loads(path.read_text())]


def record_provider(record: ProviderRecord) -> None:
    """Provider-reported geo is self-reported; this is what we measured."""
    kept = [
        r for r in load_providers() if not (r.module == record.module and r.lease == record.lease)
    ]
    kept.append(record)
    _write_json(
        paths.providers_cache(),
        json.dumps([json.loads(r.model_dump_json()) for r in kept], indent=2),
    )
