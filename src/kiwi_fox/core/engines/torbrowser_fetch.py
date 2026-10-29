"""Fetch a pinned, signature-verified Tor Browser bundle, Whonix-style.

The tarball comes from dist.torproject.org and its detached OpenPGP signature is
verified against the Tor Browser Developers signing key, whose primary
fingerprint is pinned here. The key itself is fetched from the Tor Project WKD
endpoint and only trusted once its fingerprint matches the pin, so no key blob
has to be vendored and a wrong key cannot slip in. The version index at
aus1.torproject.org is unsigned, so it is treated as a hint and a hardcoded
minimum version guards against a rollback.

The bundle is left stock — no user.js, no prefs — so Tor Browser keeps its own
uniform fingerprint; an `is-packaged-app` marker is dropped so it does not try
to write into the read-only mount. Verification shells out to gpg/gpgv.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import urllib.request
from pathlib import Path

from .. import paths
from .firefox_fetch import (
    FetchError,
    _keyring_from,
    _safe_extract,
    gpgv_ok,
    key_fingerprint,
    sha512_of,  # noqa: F401 (re-exported convenience)
)

# The per-platform release index (what Whonix's tb-updater reads) and the dist
# layout. The index is unsigned — a hint only.
VERSION_JSON = "https://aus1.torproject.org/torbrowser/update_3/release/download-linux-x86_64.json"
TARBALL = "https://dist.torproject.org/torbrowser/{v}/tor-browser-linux-x86_64-{v}.tar.xz"
TARBALL_ASC = TARBALL + ".asc"

# The Tor Browser signing key is published at this WKD address (named on the Tor
# Project's verify-signature page). It is fetched and trusted only when its
# primary fingerprint matches the pin below.
WKD_KEY = (
    "https://openpgpkey.torproject.org/.well-known/openpgpkey/torproject.org/hu/"
    "kounek7zrdx745qydx6p59t9mqjpuhdf"
)
# "Tor Browser Developers (signing key) <torbrowser@torproject.org>", primary,
# created 2014-12-15. The signing subkey rotates and is certified by this.
TBB_KEY_FINGERPRINT = "EF6E286DDA85EA2A4BA7DE684E2C6E8793298290"

# A rollback/freeze floor: the index is unsigned, so never accept a version lower
# than this. Bump it as Tor Browser advances.
MIN_VERSION = "15.0"

# Inside the bundle (one top-level tor-browser/ folder, flattened to the engine
# dir): the launcher that execs firefox.real.
BINARY = "Browser/firefox"


def target_dir(version: str) -> Path:
    return paths.engines_dir() / f"torbrowser-{version}"


def _version_key(version: str) -> tuple[int, ...]:
    out = []
    for part in version.replace("a", ".").split("."):
        out.append(int(part) if part.isdigit() else 0)
    return tuple(out)


def installed() -> list[str]:
    root = paths.engines_dir()
    if not root.exists():
        return []
    return sorted(
        (
            d.name.removeprefix("torbrowser-")
            for d in root.iterdir()
            if d.name.startswith("torbrowser-") and (d / BINARY).exists()
        ),
        key=_version_key,
    )


def latest_installed() -> str | None:
    have = installed()
    return have[-1] if have else None


def _get(url: str, timeout: int = 60) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
        return resp.read()


def discover(version: str | None = None) -> str:
    """The version to fetch: an explicit one, or the current release from the
    (unsigned) index, refused if it is below the floor."""
    if version:
        chosen = version
    else:
        data = json.loads(_get(VERSION_JSON))
        chosen = str(data.get("version") or "")
        if not chosen:
            raise FetchError("the Tor Browser version index carried no version")
    if _version_key(chosen) < _version_key(MIN_VERSION):
        raise FetchError(f"Tor Browser {chosen} is below the {MIN_VERSION} floor; refusing")
    return chosen


def _mark_packaged(bundle: Path) -> None:
    """Turn portable mode off so Tor Browser uses -profile and $HOME instead of
    writing into Browser/TorBrowser/Data — which a read-only mount forbids."""
    (bundle / "Browser" / "is-packaged-app").write_bytes(b"")


def fetch(version: str | None = None, *, force: bool = False, progress=None) -> Path:
    if shutil.which("gpg") is None or shutil.which("gpgv") is None:
        raise FetchError("gpg and gpgv are required to verify the Tor Browser download")
    ver = discover(version)
    dest = target_dir(ver)
    if (dest / BINARY).exists() and not force:
        return dest

    cache = paths.cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    tar_path = cache / f"tor-browser-{ver}.tar.xz"
    asc_path = cache / f"tor-browser-{ver}.tar.xz.asc"

    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        key_bytes = _get(WKD_KEY)
        got_fp = key_fingerprint(key_bytes)
        if got_fp != TBB_KEY_FINGERPRINT:
            raise FetchError(
                f"Tor Browser signing key is {got_fp}, not the pinned {TBB_KEY_FINGERPRINT}"
            )
        keyring = work / "tbb.gpg"
        _keyring_from(key_bytes, keyring)

        if not tar_path.exists() or force:
            tmp = tar_path.with_suffix(".part")
            with urllib.request.urlopen(TARBALL.format(v=ver), timeout=600) as resp:  # noqa: S310
                total = int(resp.headers.get("Content-Length") or 0)
                done = 0
                with tmp.open("wb") as out:
                    while chunk := resp.read(1 << 20):
                        out.write(chunk)
                        done += len(chunk)
                        if progress:
                            progress(done, total)
            tmp.replace(tar_path)
        asc_path.write_bytes(_get(TARBALL_ASC.format(v=ver)))

        if not gpgv_ok(keyring, asc_path, tar_path):
            # A bad signature must never leave a trusted-looking file behind.
            tar_path.unlink(missing_ok=True)
            asc_path.unlink(missing_ok=True)
            raise FetchError("Tor Browser tarball signature did not verify against the pinned key")

        staging = dest.with_suffix(".incoming")
        shutil.rmtree(staging, ignore_errors=True)
        _safe_extract(tar_path, staging)
        bundle = staging / "tor-browser"
        if not (bundle / BINARY).exists():
            shutil.rmtree(staging, ignore_errors=True)
            raise FetchError("tarball did not contain Browser/firefox")
        _mark_packaged(bundle)
        paths.engines_dir().mkdir(parents=True, exist_ok=True)
        shutil.rmtree(dest, ignore_errors=True)
        bundle.replace(dest)
        shutil.rmtree(staging, ignore_errors=True)
        (dest / ".version").write_text(ver + "\n")
    return dest
