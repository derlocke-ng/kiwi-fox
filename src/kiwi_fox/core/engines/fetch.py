"""Fetch a pinned Camoufox release to a shared, read-only engine directory.

One copy on the host, mounted read-only into every browser container — the
release zip is ~663 MB, so baking it into an image would be absurd.
"""

from __future__ import annotations

import contextlib
import json
import re
import shutil
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .. import paths

API_LATEST = "https://api.github.com/repos/daijro/camoufox/releases/latest"
API_ALL = "https://api.github.com/repos/daijro/camoufox/releases?per_page=30"
ASSET_RE = re.compile(r"^camoufox-(?P<ver>[0-9.]+)-beta\.(?P<beta>\d+)-lin\.x86_64\.zip$")


def _get_json(url: str, timeout: int = 60):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return json.loads(resp.read())


def discover(version: str | None = None, *, allow_prerelease: bool = False) -> tuple[str, str, str]:
    """-> (engine_version, tag, asset_url).

    Note GitHub's `/releases/latest` returns the newest *non-prerelease*, which
    for Camoufox is behind the newest beta. Pin deliberately.
    """
    releases = _get_json(API_ALL) if (version or allow_prerelease) else [_get_json(API_LATEST)]
    for rel in releases:
        if rel.get("draft"):
            continue
        if rel.get("prerelease") and not (allow_prerelease or version):
            continue
        for asset in rel.get("assets", []):
            m = ASSET_RE.match(asset["name"])
            if not m:
                continue
            if version and m["ver"] != version:
                continue
            return m["ver"], rel["tag_name"], asset["browser_download_url"]
    raise RuntimeError(
        f"no Linux x86_64 asset found for version {version or 'latest'}"
        + ("" if allow_prerelease else " (try --prerelease)")
    )


def target_dir(engine_version: str) -> Path:
    return paths.engines_dir() / f"camoufox-{engine_version}"


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) if part.isdigit() else 0 for part in version.split("."))


def installed() -> list[str]:
    root = paths.engines_dir()
    if not root.exists():
        return []
    return sorted(
        (d.name.removeprefix("camoufox-") for d in root.iterdir() if (d / "camoufox").exists()),
        key=_version_key,
    )


def preferred() -> str | None:
    """Which installed engine a new profile should use.

    Not simply the newest: an engine without its GPU probe helpers falls back to
    software rendering, and software-rendering performance against a claimed
    discrete GPU is one of our documented tells. So an engine that can render in
    hardware wins over a newer one that cannot.
    """
    candidates = installed()
    if not candidates:
        return None
    ready = [v for v in candidates if can_render_in_hardware(target_dir(v))]
    return (ready or candidates)[-1]


def fetch(
    version: str | None = None,
    *,
    allow_prerelease: bool = False,
    force: bool = False,
    progress=None,
) -> Path:
    engine_version, tag, url = discover(version, allow_prerelease=allow_prerelease)
    dest = target_dir(engine_version)
    if (dest / "camoufox").exists() and not force:
        return dest
    paths.engines_dir().mkdir(parents=True, exist_ok=True)
    zip_path = paths.cache_dir() / f"camoufox-{tag}.zip"
    zip_path.parent.mkdir(parents=True, exist_ok=True)

    if not zip_path.exists() or force:
        tmp = zip_path.with_suffix(".part")
        with urllib.request.urlopen(url, timeout=120) as resp, tmp.open("wb") as out:  # noqa: S310
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            while chunk := resp.read(1 << 20):
                out.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        tmp.replace(zip_path)

    staging = dest.with_suffix(".incoming")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            zf.extract(info, staging)
            # zipfile drops the exec bit, and the launcher needs it.
            mode = info.external_attr >> 16
            if mode:
                (staging / info.filename).chmod(mode & 0o7777)
    if not (staging / "camoufox").exists():
        shutil.rmtree(staging, ignore_errors=True)
        raise RuntimeError("archive did not contain a camoufox binary")
    for helper in ("camoufox", "camoufox-bin"):
        p = staging / helper
        if p.exists():
            p.chmod(0o755)
    shutil.rmtree(dest, ignore_errors=True)
    staging.replace(dest)
    (dest / ".tag").write_text(tag + "\n")
    # Address-bar search is unusable until this runs; see repair_search.
    with contextlib.suppress(RepairError):
        repair_search(dest)
    return dest


def version_of(engine_dir: Path) -> str | None:
    tag = engine_dir / ".tag"
    return tag.read_text().strip() if tag.exists() else None


# --------------------------------------------------------------- search repair
# Camoufox's no-search-engines.patch injects an unconditional early return into
# SearchEngineSelector.#getConfiguration() that hands back a *v1-format* config
# (`webExtension: {id: "none@mozilla.org"}`). Firefox 152 expects
# search-config-v2 records carrying `recordType`, so the Rust search component
# dies with "missing field `recordType`" and the search service never starts —
# which is why the address bar cannot search and why no search WebExtension can
# register, however well formed it is.
#
# The packaged config dump is untouched (157 records, 154 engines), so deleting
# the injected stub lets the original code path load it and search works exactly
# as stock Firefox. This edits JavaScript inside omni.ja, which is a zip, so no
# compiler and no Firefox build is involved.
SEARCH_SELECTOR = "moz-src/toolkit/components/search/SearchEngineSelector.sys.mjs"
STUB_MARKER = "none@mozilla.org"
STUB_RE = re.compile(
    r"\n[ \t]*if \(true\) \{[ \t]*\n[ \t]*return \[.*?"
    + re.escape(STUB_MARKER)
    + r".*?\];[ \t]*\n[ \t]*\}\n",
    re.DOTALL,
)


class RepairError(RuntimeError):
    pass


def search_is_disabled(engine_dir: Path) -> bool:
    jar = engine_dir / "omni.ja"
    if not jar.exists():
        return False
    with zipfile.ZipFile(jar) as z:
        if SEARCH_SELECTOR not in z.namelist():
            return False
        return STUB_MARKER in z.read(SEARCH_SELECTOR).decode("utf-8", "replace")


def repair_search(engine_dir: Path, *, backup: bool = True) -> bool:
    """Re-enable address-bar search. Idempotent; returns True if it changed anything."""
    jar = engine_dir / "omni.ja"
    if not jar.exists():
        raise RepairError(f"no omni.ja in {engine_dir}")
    with zipfile.ZipFile(jar) as z:
        if SEARCH_SELECTOR not in z.namelist():
            raise RepairError(f"{SEARCH_SELECTOR} not found; engine layout changed")
        source = z.read(SEARCH_SELECTOR).decode("utf-8")
    if STUB_MARKER not in source:
        return False  # already repaired, or a build without the patch

    patched, count = STUB_RE.subn("\n", source, count=1)
    if count != 1:
        raise RepairError(
            "could not locate the injected stub; the patch shape changed — inspect "
            f"{SEARCH_SELECTOR} by hand rather than guessing"
        )
    # Sanity: the real implementation must still be there and the stub gone.
    if STUB_MARKER in patched or "async #getConfiguration(" not in patched:
        raise RepairError("patched source failed its sanity check; refusing to write")
    if "let result = [];" not in patched:
        raise RepairError("the original implementation is missing after patching")

    if backup:
        orig = jar.with_suffix(".ja.orig")
        if not orig.exists():
            shutil.copy2(jar, orig)

    tmp = jar.with_suffix(".ja.new")
    with zipfile.ZipFile(jar) as src, zipfile.ZipFile(tmp, "w") as dst:
        for info in src.infolist():
            data = patched.encode("utf-8") if info.filename == SEARCH_SELECTOR else src.read(info)
            # Preserve each entry's own compression: omni.ja mixes stored and
            # deflated members and Firefox reads both.
            out = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            out.compress_type = info.compress_type
            out.external_attr = info.external_attr
            out.internal_attr = info.internal_attr
            out.create_system = info.create_system
            dst.writestr(out, data)
    tmp.replace(jar)
    return True


def restore_search(engine_dir: Path) -> bool:
    """Put the untouched omni.ja back."""
    jar = engine_dir / "omni.ja"
    orig = jar.with_suffix(".ja.orig")
    if not orig.exists():
        return False
    shutil.copy2(orig, jar)
    return True


# ------------------------------------------------------------- engine tweaks
# Camoufox's patches split in two. The C++ ones are compiled into libxul and are
# the whole point of the engine — navigator, screen, WebGL, fonts, timezone,
# locale, audio and WebRTC spoofing — so they are untouchable and we want them.
# The JS/CSS/prefs ones are data on disk (omni.ja is a zip, chrome.css a plain
# file), tuned for watching an automated browser rather than using one. Those we
# revert selectively, reversibly, and only where the fingerprint cost is
# understood. Every tweak records that assessment next to the change.


@dataclass(frozen=True)
class Tweak:
    name: str
    what: str
    fingerprint: str


TWEAKS: dict[str, Tweak] = {
    "search": Tweak(
        "search",
        "re-enable address-bar search (undo the v1-shaped config stub that stops "
        "the search service starting at all)",
        "none: the search service is browser chrome. The engine list a site can "
        "observe is unchanged.",
    ),
    "chrome": Tweak(
        "chrome",
        "neutralise the bundled minimalisticfox chrome.css, restoring stock tab "
        "and toolbar geometry, close buttons, bookmark star and window controls",
        "safe, and arguably better: outerHeight-innerHeight returns to stock "
        "Firefox proportions. We spoof window.* explicitly anyway, so reported "
        "values do not depend on it.",
    ),
    "window-rounding": Tweak(
        "window-rounding",
        "undo the forced resistFingerprinting window-size rounding in "
        "browser-init.js, which prevents a normally maximised window",
        "we set screen and window values from config, so rounding adds nothing "
        "and fights the maximised geometry seeded into xulstore.json.",
    ),
    "policies": Tweak(
        "policies",
        "relax the enterprise policy: stop removing DuckDuckGo and pinning a dummy "
        '"None" search engine, and stop forcing HardwareAcceleration off',
        "none, and it removes a tell: software-rendering performance contradicts a "
        "claimed discrete GPU. The search default is only observable once the user "
        "actually searches.",
    ),
    "urlbar-tips": Tweak(
        "urlbar-tips",
        "re-enable urlbar intervention tips",
        "cosmetic chrome behaviour; not web-observable.",
    ),
}

# Regex, not literals: the injected `if (true ||` sits on its own line in some
# files and inline in others, and a literal match silently reports "already
# stock" when it is really just whitespace that differs.
_JS_EDITS: dict[str, tuple[str, str, re.Pattern[str], str]] = {
    # name -> (jar, member, pattern, replacement)
    "window-rounding": (
        "browser/omni.ja",
        "chrome/browser/content/browser/browser-init.js",
        re.compile(r"if \(\s*true\s*\|\|\s*(ChromeUtils\.shouldResistFingerprinting\()"),
        r"if (\1",
    ),
    "urlbar-tips": (
        "omni.ja",
        "moz-src/browser/components/urlbar/UrlbarProviderInterventions.sys.mjs",
        re.compile(r"if \(\s*true\s*\|\|\s*(!queryContext\.searchString)"),
        r"if (\1",
    ),
}


def _rewrite_jar(engine_dir: Path, jar: str, member: str, transform) -> bool:
    path = engine_dir / jar
    if not path.exists():
        raise RepairError(f"{jar} not found in {engine_dir}")
    with zipfile.ZipFile(path) as z:
        if member not in z.namelist():
            raise RepairError(f"{member} not in {jar}; engine layout changed")
        before = z.read(member).decode("utf-8")
    after = transform(before)
    if after is None or after == before:
        return False
    backup = path.with_suffix(path.suffix + ".orig")
    if not backup.exists():
        shutil.copy2(path, backup)
    tmp = path.with_suffix(path.suffix + ".new")
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(tmp, "w") as dst:
        for info in src.infolist():
            data = after.encode("utf-8") if info.filename == member else src.read(info)
            out = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            out.compress_type = info.compress_type
            out.external_attr = info.external_attr
            out.internal_attr = info.internal_attr
            out.create_system = info.create_system
            dst.writestr(out, data)
    tmp.replace(path)
    return True


KF_CHROME_MARKER = "neutralised by kiwi-fox"


def chrome_css_is_minimal(engine_dir: Path) -> bool:
    """True while the engine's own minimalistic chrome styling is still active.

    Detected by a positive marker, not by naming the upstream theme: the first
    version of this looked for "minimalisticfox", which the replacement comment
    itself contained, so a neutralised file reported as still minimal.
    """
    css = engine_dir / "chrome.css"
    if not css.exists():
        return False
    text = css.read_text(errors="replace")
    if KF_CHROME_MARKER in text:
        return False
    return "--tab-min-height" in text or "tabbrowser-tab" in text


def apply_tweak(engine_dir: Path, name: str) -> bool:
    """Returns True if something changed. Idempotent."""
    if name == "search":
        return repair_search(engine_dir)
    if name == "chrome":
        css = engine_dir / "chrome.css"
        if not css.exists():
            raise RepairError("no chrome.css in the engine directory")
        if not chrome_css_is_minimal(engine_dir):
            return False
        backup = css.with_suffix(".css.orig")
        if not backup.exists():
            shutil.copy2(css, backup)
        css.write_text(
            f"/* {KF_CHROME_MARKER}: the bundled theme hid tab close buttons, the\n"
            "   bookmark star, the extensions button, the bookmarks toolbar and the\n"
            "   window controls, and shrank tabs to 25px. Original kept alongside\n"
            "   as chrome.css.orig; restore with `kiwi-fox engine restore`. */\n"
        )
        return True
    if name == "policies":
        return relax_policies(engine_dir)
    if name in _JS_EDITS:
        jar, member, pattern, replacement = _JS_EDITS[name]

        def transform(text: str) -> str | None:
            patched, count = pattern.subn(replacement, text, count=1)
            return patched if count else None  # already applied, or shape changed

        return _rewrite_jar(engine_dir, jar, member, transform)
    raise RepairError(f"unknown tweak {name!r}")


def tweak_state(engine_dir: Path) -> dict[str, bool]:
    """name -> True when the stock-Firefox behaviour is in place."""
    state = {"search": not search_is_disabled(engine_dir)}
    state["chrome"] = not chrome_css_is_minimal(engine_dir)
    state["policies"] = not policies_are_restrictive(engine_dir)
    for name, (jar, member, pattern, _replacement) in _JS_EDITS.items():
        path = engine_dir / jar
        try:
            with zipfile.ZipFile(path) as z:
                state[name] = not pattern.search(z.read(member).decode("utf-8", "replace"))
        except Exception:
            state[name] = False
    return state


def restore_engine(engine_dir: Path) -> list[str]:
    """Put every backed-up original back."""
    restored = []
    for backup in sorted(engine_dir.glob("*.orig")) + sorted(engine_dir.glob("*/*.orig")):
        target = backup.with_name(backup.name.removesuffix(".orig"))
        shutil.copy2(backup, target)
        restored.append(str(target.relative_to(engine_dir)))
    return restored


KNOWN_HELPERS = ("glxtest", "vaapitest", "gfxtest")
BROWSER_IMAGE = "kiwi-fox/browser:latest"


def expected_gl_helpers(engine_dir: Path) -> list[str]:
    """Which probe helpers this engine build actually spawns.

    Firefox 156 merged glxtest and vaapitest into a single `gfxtest`, so the name
    depends on the engine's base version. Read it out of libxul rather than
    assuming: a helper under the wrong name is never found, and a *stub* under
    the right name is worse than nothing because Firefox then believes the probe
    ran and found no GPU.
    """
    lib = engine_dir / "libxul.so"
    if not lib.exists():
        return []
    blob = lib.read_bytes()
    return [h for h in KNOWN_HELPERS if b"\x00" + h.encode() + b"\x00" in blob]


def gl_helpers_installed(engine_dir: Path) -> list[str]:
    return [h for h in KNOWN_HELPERS if (engine_dir / h).exists()]


def can_render_in_hardware(engine_dir: Path) -> bool:
    """Every helper this build spawns must be present, not merely some helper.

    An engine directory can end up holding a helper it never calls — a `gfxtest`
    left by a build that wanted `glxtest` — and counting that as ready silently
    selects an engine that falls back to software.
    """
    expected = expected_gl_helpers(engine_dir)
    return bool(expected) and all((engine_dir / h).exists() for h in expected)


def install_gl_helpers(engine_dir: Path, image: str = BROWSER_IMAGE) -> list[str]:
    """Copy Firefox's GPU probe helpers into the engine directory.

    Firefox spawns `glxtest` by absolute path from its application directory, so
    a PATH entry or a tmpfs copy will not do — it has to sit next to the binary.
    The engine directory is host-side and mounted read-only into containers, so
    this writes it there, extracting from the browser image which carries
    Fedora's copies.
    """
    import subprocess

    wanted = expected_gl_helpers(engine_dir)
    if not wanted:
        raise RepairError("could not determine which probe helpers this engine spawns")
    installed, missing = [], []
    for helper in wanted:
        dest = engine_dir / helper
        if dest.exists():
            continue
        proc = subprocess.run(  # noqa: S603
            ["podman", "run", "--rm", "--entrypoint", "cat", image, f"/usr/libexec/kf/{helper}"],
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0 or not proc.stdout:
            missing.append(helper)
            continue
        dest.write_bytes(proc.stdout)
        dest.chmod(0o755)
        installed.append(helper)
    if missing:
        raise RepairError(
            f"this engine spawns {', '.join(missing)}, which the distro's Firefox no "
            f"longer ships (156 merged them into gfxtest). Hardware rendering needs an "
            f"engine whose base version matches the distro's Firefox — pin a 156 "
            f"Camoufox build — or a Camoufox release that includes its own helpers."
        )
    return installed


def remove_gl_helpers(engine_dir: Path) -> list[str]:
    removed = []
    for helper in KNOWN_HELPERS:
        path = engine_dir / helper
        if path.exists():
            path.unlink()
            removed.append(helper)
    return removed


# ----------------------------------------------------------- default search
SEARCH_CONFIG = "defaults/settings/main/search-config-v2.json"


def search_engine_ids(engine_dir: Path) -> list[str]:
    with zipfile.ZipFile(engine_dir / "browser/omni.ja") as z:
        doc = json.loads(z.read(SEARCH_CONFIG))
    return sorted(r["identifier"] for r in doc.get("data", []) if r.get("recordType") == "engine")


def current_default_search(engine_dir: Path) -> str | None:
    try:
        with zipfile.ZipFile(engine_dir / "browser/omni.ja") as z:
            doc = json.loads(z.read(SEARCH_CONFIG))
    except Exception:
        return None
    for record in doc.get("data", []):
        if record.get("recordType") == "defaultEngines":
            return record.get("globalDefault")
    return None


def set_default_search(engine_dir: Path, identifier: str = "ddg") -> bool:
    """Choose the default search engine.

    Firefox 152 takes the default from the packaged search config's
    `defaultEngines` record, not from a pref — `browser.search.defaultenginename`
    is not read any more — so this edits that record. Region-specific defaults are
    cleared too, otherwise the locale would override the choice. Not a fingerprint
    surface: the default engine is only observable once the user actually searches.
    """
    available = search_engine_ids(engine_dir)
    if identifier not in available:
        raise RepairError(
            f"no engine {identifier!r} in the packaged config; available: "
            + ", ".join(available[:12])
            + (" …" if len(available) > 12 else "")
        )

    def transform(text: str) -> str | None:
        doc = json.loads(text)
        changed = False
        for record in doc.get("data", []):
            if record.get("recordType") != "defaultEngines":
                continue
            if record.get("globalDefault") != identifier:
                record["globalDefault"] = identifier
                changed = True
            if record.get("specificDefaults"):
                record["specificDefaults"] = []
                changed = True
        return json.dumps(doc, separators=(",", ":")) if changed else None

    return _rewrite_jar(engine_dir, "browser/omni.ja", SEARCH_CONFIG, transform)


# ------------------------------------------------------------------ policies
# distribution/policies.json is an enterprise policy file, and it outranks every
# pref we can set from a profile. Camoufox uses it to remove the real search
# engines (DuckDuckGo by name), install a dummy "None" engine as the default, and
# turn hardware acceleration off outright. None of that is a fingerprint measure:
# the search default is only observable once the user searches, and hardware vs
# software rendering is a performance tell *against* us, since software
# performance contradicts a claimed discrete GPU.
POLICIES = "distribution/policies.json"
SEARCH_EXTENSION_IDS = (
    "google@search.mozilla.org",
    "bing@search.mozilla.org",
    "amazondotcom@search.mozilla.org",
    "ebay@search.mozilla.org",
    "twitter@search.mozilla.org",
)


def policies_are_restrictive(engine_dir: Path) -> bool:
    path = engine_dir / POLICIES
    if not path.exists():
        return False
    try:
        pol = json.loads(path.read_text()).get("policies", {})
    except Exception:
        return False
    return (
        "SearchEngines" in pol
        or pol.get("HardwareAcceleration") is False
        or pol.get("DisplayBookmarksToolbar") == "never"
    )


def relax_policies(engine_dir: Path) -> bool:
    """Drop the policy entries that make this unusable as a browser."""
    path = engine_dir / POLICIES
    if not path.exists():
        raise RepairError(f"no {POLICIES} in {engine_dir}")
    doc = json.loads(path.read_text())
    pol = doc.get("policies", {})
    before = json.dumps(pol, sort_keys=True)

    # Removes DuckDuckGo et al by name and pins a dummy "None" engine as default.
    pol.pop("SearchEngines", None)
    # A policy "false" cannot be overridden by any pref, so the GPU never engages.
    pol["HardwareAcceleration"] = True
    # Let the profile's own pref decide.
    pol.pop("DisplayBookmarksToolbar", None)
    # Vestigial in 152 (engines come from the config now), but it uninstalls the
    # search extensions, so leaving it only invites confusion.
    uninstall = pol.get("Extensions", {}).get("Uninstall")
    if uninstall:
        kept = [e for e in uninstall if e not in SEARCH_EXTENSION_IDS]
        if kept != uninstall:
            pol["Extensions"]["Uninstall"] = kept

    if json.dumps(pol, sort_keys=True) == before:
        return False
    backup = path.with_suffix(".json.orig")
    if not backup.exists():
        shutil.copy2(path, backup)
    doc["policies"] = pol
    path.write_text(json.dumps(doc, indent=2) + "\n")
    return True


# ----------------------------------------------------- version-matched helpers
MOZ_RELEASE = (
    "https://ftp.mozilla.org/pub/firefox/releases/{v}/linux-x86_64/en-US/firefox-{v}.tar.xz"
)


def install_gl_helpers_from_mozilla(engine_dir: Path, version: str) -> list[str]:
    """Take glxtest/vaapitest from Mozilla's own release tarball.

    The distro's Firefox is the wrong source: Fedora 43 ships 156, which renamed
    the helpers to a single `gfxtest`, while Camoufox 152 *and* 156 both still
    spawn `glxtest` and `vaapitest`. Mozilla's tarball for the engine's own base
    version has exactly the right binaries by definition.
    """
    import tarfile
    import urllib.request

    wanted = expected_gl_helpers(engine_dir) or ["glxtest", "vaapitest"]
    missing = [h for h in wanted if not (engine_dir / h).exists()]
    if not missing:
        return []

    url = MOZ_RELEASE.format(v=version)
    cached = paths.cache_dir() / f"firefox-{version}.tar.xz"
    cached.parent.mkdir(parents=True, exist_ok=True)
    if not cached.exists():
        tmp = cached.with_suffix(".part")
        try:
            with urllib.request.urlopen(url, timeout=120) as resp, tmp.open("wb") as out:  # noqa: S310
                shutil.copyfileobj(resp, out)
        except Exception as exc:
            tmp.unlink(missing_ok=True)
            raise RepairError(f"could not download {url}: {exc}") from exc
        tmp.replace(cached)

    installed = []
    with tarfile.open(cached) as tf:
        for helper in missing:
            try:
                member = tf.getmember(f"firefox/{helper}")
            except KeyError:
                continue
            src = tf.extractfile(member)
            if src is None:
                continue
            dest = engine_dir / helper
            dest.write_bytes(src.read())
            dest.chmod(0o755)
            installed.append(helper)
    if not installed:
        raise RepairError(f"firefox-{version} tarball contained none of {', '.join(missing)}")
    return installed
