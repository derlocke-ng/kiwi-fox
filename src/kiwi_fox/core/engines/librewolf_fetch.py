"""Fetch a signature-verified LibreWolf to a shared engine directory.

LibreWolf's own Linux tarball (`librewolf-<version>-linux-x86_64-package.tar.xz`,
listed by its releases on Codeberg, served from dl.librewolf.net) with its
detached OpenPGP signature. The signature is checked against the LibreWolf
Maintainers key, whose primary fingerprint is pinned here. The key itself comes
from keys.openpgp.org by that fingerprint: the copy on repo.librewolf.net lacks
the subkey the tarballs are signed with (seen 2026-11-20, 160.0.1-1).

The tarball already carries LibreWolf's own policies.json and librewolf.cfg
(updates off, telemetry off, its hardening); they are left as they are.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import urllib.request
from pathlib import Path

from .. import paths
from .firefox_fetch import FetchError, _get, _keyring_from, _safe_extract, gpgv_ok, key_fingerprint

RELEASES = "https://codeberg.org/api/v1/repos/librewolf/bsys6/releases?limit=30"
TARBALL = "https://dl.librewolf.net/librewolf/{v}/librewolf-{v}-linux-x86_64-package.tar.xz"
SIGNATURE = TARBALL + ".sig"
# LibreWolf Maintainers <gpg@librewolf.net>
KEY_FINGERPRINT = "662E3CDD6FE329002D0CA5BB40339DD82B12EF16"
KEY_URL = f"https://keys.openpgp.org/vks/v1/by-fingerprint/{KEY_FINGERPRINT}"

BINARY = "librewolf"
PREFIX = "librewolf-"
_VERSION = re.compile(r"^\d+(\.\d+){1,3}-\d+$")  # 160.0.1-1: Firefox's version, LibreWolf's build


def target_dir(version: str) -> Path:
    return paths.engines_dir() / f"{PREFIX}{version}"


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", version))


def installed() -> list[str]:
    root = paths.engines_dir()
    if not root.exists():
        return []
    return sorted(
        (
            d.name.removeprefix(PREFIX)
            for d in root.iterdir()
            if d.name.startswith(PREFIX) and (d / BINARY).exists()
        ),
        key=_version_key,
    )


def latest_installed() -> str | None:
    have = installed()
    return have[-1] if have else None


def versions(listing: object) -> list[str]:
    """The Linux releases in Codeberg's answer, newest first: tags shaped like a
    version that are no draft or pre-release and have the Linux tarball."""
    out = []
    for rel in listing if isinstance(listing, list) else []:
        tag = str(rel.get("tag_name") or "")
        if not _VERSION.match(tag) or rel.get("draft") or rel.get("prerelease"):
            continue
        want = f"librewolf-{tag}-linux-x86_64-package.tar.xz"
        if any(a.get("name") == want for a in rel.get("assets") or []):
            out.append(tag)
    return sorted(out, key=_version_key, reverse=True)


def releases() -> list[str]:
    return versions(json.loads(_get(RELEASES)))


def discover(version: str | None = None) -> str:
    if version:
        if not _VERSION.match(version):
            raise FetchError(f"{version!r} is not a LibreWolf version (like 160.0.1-1)")
        return version
    found = releases()
    if not found:
        raise FetchError("LibreWolf's release list has no Linux download")
    return found[0]


def fetch(version: str | None = None, *, force: bool = False, progress=None) -> Path:
    """Download, verify and install LibreWolf <version> (or the newest release)."""
    if shutil.which("gpg") is None or shutil.which("gpgv") is None:
        raise FetchError("gpg and gpgv are required to verify the LibreWolf download")
    ver = discover(version)
    dest = target_dir(ver)
    if (dest / BINARY).exists() and not force:
        return dest

    cache = paths.cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    tar_path = cache / f"librewolf-{ver}.tar.xz"

    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        key_bytes = _get(KEY_URL)
        got = key_fingerprint(key_bytes)
        if got != KEY_FINGERPRINT:
            raise FetchError(f"LibreWolf signing key is {got}, not the pinned {KEY_FINGERPRINT}")
        keyring = work / "librewolf.gpg"
        _keyring_from(key_bytes, keyring)
        sig = work / "tarball.sig"
        sig.write_bytes(_get(SIGNATURE.format(v=ver)))

        if not tar_path.exists() or force or not gpgv_ok(keyring, sig, tar_path):
            tmp = tar_path.with_suffix(".part")
            with urllib.request.urlopen(TARBALL.format(v=ver), timeout=300) as resp:  # noqa: S310
                total = int(resp.headers.get("Content-Length") or 0)
                done = 0
                with tmp.open("wb") as out:
                    while chunk := resp.read(1 << 20):
                        out.write(chunk)
                        done += len(chunk)
                        if progress:
                            progress(done, total)
            tmp.replace(tar_path)
        if not gpgv_ok(keyring, sig, tar_path):
            tar_path.unlink(missing_ok=True)
            raise FetchError(
                "the LibreWolf tarball's signature did not verify against the pinned key"
            )

        staging = dest.with_suffix(".incoming")
        shutil.rmtree(staging, ignore_errors=True)
        _safe_extract(tar_path, staging)
        bundle = staging / "librewolf"
        if not (bundle / BINARY).exists():
            shutil.rmtree(staging, ignore_errors=True)
            raise FetchError("tarball did not contain a librewolf binary")
        paths.engines_dir().mkdir(parents=True, exist_ok=True)
        shutil.rmtree(dest, ignore_errors=True)
        bundle.replace(dest)
        shutil.rmtree(staging, ignore_errors=True)
        (dest / ".version").write_text(ver + "\n")
    return dest
