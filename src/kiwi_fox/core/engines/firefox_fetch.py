"""Fetch a pinned, signature-verified stock Firefox to a shared engine directory.

Mozilla's own Linux tarball, checked the way Mozilla documents it: the detached
OpenPGP signature over SHA512SUMS is verified against the release signing key,
whose primary fingerprint is pinned here (the key file travels with the
artifacts, so trusting it blindly would verify nothing), and then the tarball's
SHA-512 is checked against its SHA512SUMS line. Updates are turned off in the
bundle's policies.json, because the engine is mounted read-only and pinned.

Verification shells out to gpg/gpgv (both in the base image and on any desktop);
the pure parts — the SHA512SUMS line, the fingerprint match, the policies file —
are separated out so they can be tested without the network.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from .. import paths

# Mozilla's version index and the per-release artifact layout.
VERSIONS_JSON = "https://product-details.mozilla.org/1.0/firefox_versions.json"
RELEASE_BASE = "https://archive.mozilla.org/pub/firefox/releases/{v}"
TARBALL = RELEASE_BASE + "/linux-x86_64/en-US/firefox-{v}.tar.xz"
TARBALL_ASC = TARBALL + ".asc"
SHA512SUMS = RELEASE_BASE + "/SHA512SUMS"
SHA512SUMS_ASC = RELEASE_BASE + "/SHA512SUMS.asc"
KEY_URL = RELEASE_BASE + "/KEY"

# "Mozilla Software Releases <release@mozilla.com>", primary key, created
# 2015-07-17. Pinned so a KEY file fetched beside the artifacts cannot introduce
# an attacker's key; the signing SUBKEY rotates and is not pinned (it is
# certified by this primary). Confirmed from the Mozilla security blog and the
# release KEY file. Compared case-insensitively with spaces stripped.
MOZ_KEY_FINGERPRINT = "14F26682D0916CDD81E37B6D61B7B526D98F0353"

BINARY = "firefox"


class FetchError(RuntimeError):
    pass


def target_dir(version: str) -> Path:
    return paths.engines_dir() / f"firefox-{version}"


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(p) if p.isdigit() else 0 for p in version.split("."))


def installed() -> list[str]:
    root = paths.engines_dir()
    if not root.exists():
        return []
    return sorted(
        (
            d.name.removeprefix("firefox-")
            for d in root.iterdir()
            if d.name.startswith("firefox-") and (d / BINARY).exists()
        ),
        key=_version_key,
    )


def latest_installed() -> str | None:
    have = installed()
    return have[-1] if have else None


# ------------------------------------------------------------------- discovery
def _get(url: str, timeout: int = 60) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
        return resp.read()


def discover(version: str | None = None) -> str:
    """The version to fetch: an explicit one, or Mozilla's current release."""
    if version:
        return version
    data = json.loads(_get(VERSIONS_JSON))
    latest = data.get("LATEST_FIREFOX_VERSION")
    if not latest:
        raise FetchError("firefox_versions.json carried no LATEST_FIREFOX_VERSION")
    return str(latest)


# -------------------------------------------------------------- pure verifiers
def sha512_for(sums_text: str, filename: str) -> str | None:
    """The checksum SHA512SUMS lists for a file (matched on the basename)."""
    for line in sums_text.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and Path(parts[1].strip()).name == filename:
            return parts[0].strip().lower()
    return None


def _normalize_fp(text: str) -> str:
    return text.replace(" ", "").replace("\t", "").upper()


def key_fingerprint(key_bytes: bytes) -> str | None:
    """The primary-key fingerprint of an ASCII-armored public key, via gpg."""
    with tempfile.TemporaryDirectory() as home:
        proc = subprocess.run(
            [
                "gpg",
                "--homedir",
                home,
                "--with-colons",
                "--import-options",
                "show-only",
                "--import",
            ],
            input=key_bytes,
            capture_output=True,
            timeout=30,
        )
        for line in proc.stdout.decode("utf-8", "replace").splitlines():
            field = line.split(":")
            # The fpr record right after the first pub record is the primary key.
            if field[0] == "fpr":
                return _normalize_fp(field[9])
    return None


def _keyring_from(key_bytes: bytes, dest: Path) -> None:
    """A gpgv keyring (dearmored key) from the trusted KEY bytes."""
    proc = subprocess.run(["gpg", "--dearmor"], input=key_bytes, capture_output=True, timeout=30)
    if proc.returncode != 0:
        raise FetchError(
            f"could not dearmor the signing key: {proc.stderr.decode(errors='replace')}"
        )
    dest.write_bytes(proc.stdout)


def gpgv_ok(keyring: Path, signature: Path, data: Path) -> bool:
    proc = subprocess.run(
        ["gpgv", "--keyring", str(keyring), str(signature), str(data)],
        capture_output=True,
        timeout=60,
    )
    return proc.returncode == 0


def sha512_of(path: Path) -> str:
    import hashlib

    h = hashlib.sha512()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest().lower()


# ------------------------------------------------------------------- policies
# Written host-side before the engine is mounted read-only. Update is off
# (the engine is pinned and the mount is read-only), telemetry and studies off,
# and the first-run and post-update pages suppressed. Every key is one the
# installed Firefox's Policies module honours; see docs/decisions.md.
POLICIES: dict[str, object] = {
    "policies": {
        "DisableAppUpdate": True,
        "DisableTelemetry": True,
        "DisableFirefoxStudies": True,
        "DontCheckDefaultBrowser": True,
        "OverrideFirstRunPage": "",
        "OverridePostUpdatePage": "",
        "SkipTermsOfUse": True,
        "UserMessaging": {
            "ExtensionRecommendations": False,
            "FeatureRecommendations": False,
            "UrlbarInterventions": False,
            "SkipOnboarding": True,
            "MoreFromMozilla": False,
            "Locked": True,
        },
    }
}


def write_policies(engine_dir: Path) -> Path:
    path = engine_dir / "distribution" / "policies.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(POLICIES, indent=2) + "\n")
    return path


# ----------------------------------------------------------------- extraction
def _safe_extract(tar_path: Path, staging: Path) -> None:
    """Extract firefox/* into staging, refusing any path escape.

    The tarball has a single top-level firefox/ directory; nothing is trusted to
    stay inside it, so each member is checked before extraction (the tarfile
    'data' filter on 3.12+ also rejects traversal, used when available).
    """
    import tarfile

    staging.mkdir(parents=True, exist_ok=True)
    root = staging.resolve()
    with tarfile.open(tar_path) as tf:
        members = tf.getmembers()
        for m in members:
            dest = (staging / m.name).resolve()
            if not str(dest).startswith(str(root) + "/") and dest != root:
                raise FetchError(f"refusing path traversal in tarball: {m.name!r}")
        try:
            tf.extractall(staging, members=members, filter="data")
        except TypeError:  # Python without the filter argument
            tf.extractall(staging, members=members)  # noqa: S202


def fetch(
    version: str | None = None,
    *,
    force: bool = False,
    progress=None,
) -> Path:
    """Download, verify and install Firefox <version> (or the current release)."""
    if shutil.which("gpg") is None or shutil.which("gpgv") is None:
        raise FetchError("gpg and gpgv are required to verify the Firefox download")
    ver = discover(version)
    dest = target_dir(ver)
    if (dest / BINARY).exists() and not force:
        return dest

    cache = paths.cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    tar_path = cache / f"firefox-{ver}.tar.xz"

    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        key_bytes = _get(KEY_URL.format(v=ver))
        got_fp = key_fingerprint(key_bytes)
        if got_fp != MOZ_KEY_FINGERPRINT:
            raise FetchError(
                f"Firefox signing key is {got_fp}, not the pinned {MOZ_KEY_FINGERPRINT}"
            )
        keyring = work / "moz.gpg"
        _keyring_from(key_bytes, keyring)

        sums = work / "SHA512SUMS"
        sums_asc = work / "SHA512SUMS.asc"
        sums.write_bytes(_get(SHA512SUMS.format(v=ver)))
        sums_asc.write_bytes(_get(SHA512SUMS_ASC.format(v=ver)))
        if not gpgv_ok(keyring, sums_asc, sums):
            raise FetchError("SHA512SUMS signature did not verify against the pinned key")

        want = sha512_for(sums.read_text(), f"firefox-{ver}.tar.xz")
        if not want:
            raise FetchError(f"SHA512SUMS has no line for firefox-{ver}.tar.xz")

        if not tar_path.exists() or force or sha512_of(tar_path) != want:
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
        if sha512_of(tar_path) != want:
            tar_path.unlink(missing_ok=True)
            raise FetchError("firefox tarball SHA-512 did not match SHA512SUMS")

        staging = dest.with_suffix(".incoming")
        shutil.rmtree(staging, ignore_errors=True)
        _safe_extract(tar_path, staging)
        bundle = staging / "firefox"
        if not (bundle / BINARY).exists():
            shutil.rmtree(staging, ignore_errors=True)
            raise FetchError("tarball did not contain a firefox binary")
        write_policies(bundle)
        paths.engines_dir().mkdir(parents=True, exist_ok=True)
        shutil.rmtree(dest, ignore_errors=True)
        bundle.replace(dest)
        shutil.rmtree(staging, ignore_errors=True)
        (dest / ".version").write_text(ver + "\n")
    return dest
