"""First-run setup: everything needed before a profile can launch.

Deliberately *not* done at install time — building images and downloading a
~630 MB engine needs network at the wrong moment and would make `kiwi install`
look broken. This is the one command a new user runs.

The browser half is done here; the network half — the gateway image, DNS
resolver stamps, the ad-block list, provider module images — is kiwi-proxy's
setup, which this calls, so there is still one command.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from kiwi_proxy import podman
from kiwi_proxy import setup as proxy_setup

from . import paths, store
from .engines import fetch as engine_fetch

IMAGES = (("kiwi-fox/browser:latest", "browser"),)

Progress = Callable[[str], None]


class SetupError(RuntimeError):
    pass


def containers_dir() -> Path:
    """Where the Containerfiles live, in a checkout or an installed copy."""
    here = Path(__file__).resolve()
    for candidate in (here.parents[3] / "containers", here.parents[2] / "containers"):
        if (candidate / "browser" / "Containerfile").exists():
            return candidate
    raise SetupError("cannot find the containers/ directory next to the package")


SOURCE_LABEL = "kiwi-fox.source"


def source_hash(name: str) -> str:
    """A fingerprint of everything an image is built from."""
    import hashlib

    digest = hashlib.sha256()
    root = containers_dir() / name
    for path in sorted(p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
        digest.update(str(path.relative_to(root)).encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()[:16]


def image_state(image: str, name: str) -> str:
    """missing | stale | current. Stale: built from sources an update has since
    replaced — the app is new and the image is not."""
    if not podman.image_exists(image):
        return "missing"
    label = podman._run(
        ["image", "inspect", "--format", f'{{{{index .Labels "{SOURCE_LABEL}"}}}}', image],
        check=False,
    ).stdout.strip()
    return "current" if label == source_hash(name) else "stale"


def build_images(progress: Progress | None = None, force: bool = False) -> list[str]:
    root = containers_dir()
    built = []
    for image, name in IMAGES:
        if image_state(image, name) == "current" and not force:
            continue
        if progress:
            progress(f"Building the {name} image — this takes a few minutes…")
        proc = subprocess.run(  # noqa: S603
            [
                "podman",
                "build",
                "-t",
                image,
                "--label",
                f"{SOURCE_LABEL}={source_hash(name)}",
                "-f",
                str(root / name / "Containerfile"),
                str(root / name),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise SetupError(f"building {image} failed:\n{proc.stderr[-800:]}")
        built.append(image)
    return built


def run(progress: Progress | None = None, *, engine_version: str | None = None) -> list[str]:
    """Idempotent: safe to run again at any time."""

    def say(message: str) -> None:
        if progress:
            progress(message)

    steps: list[str] = []
    paths.ensure_tree()

    if not podman.available():
        raise SetupError("podman is not installed")

    say("Building the browser image…")
    built = build_images(progress)
    steps.append(f"images: {'built ' + ', '.join(built) if built else 'already present'}")

    installed = engine_fetch.installed()
    if engine_version or not installed:
        say("Downloading the browser engine (~630 MB)…")
        path = engine_fetch.fetch(engine_version)
        version = path.name.removeprefix("camoufox-")
        steps.append(f"engine: camoufox {version}")
    else:
        version = engine_fetch.preferred() or installed[-1]
        steps.append(f"engine: camoufox {version} already present")

    engine_dir = engine_fetch.target_dir(version)

    say("Making the engine behave like Firefox…")
    applied = []
    for tweak in engine_fetch.TWEAKS:
        try:
            if engine_fetch.apply_tweak(engine_dir, tweak):
                applied.append(tweak)
        except engine_fetch.RepairError as exc:
            steps.append(f"tweak {tweak}: skipped ({exc})")
    steps.append(f"tweaks: {', '.join(applied) if applied else 'already applied'}")

    try:
        engine_fetch.set_default_search(engine_dir, "ddg")
        steps.append("default search: ddg")
    except engine_fetch.RepairError as exc:
        steps.append(f"default search: skipped ({exc})")

    say("Installing the GPU probe helpers…")
    try:
        added = engine_fetch.install_gl_helpers_from_mozilla(engine_dir, version)
        # Having the helper says nothing about what it will find; the measurement
        # two steps down does.
        steps.append(f"gpu helper: {', '.join(added) if added else 'present'}")
    except engine_fetch.RepairError as exc:
        steps.append(f"gpu helper: unavailable ({exc})")

    say("Checking what the browser will draw with…")
    try:
        from . import gpu

        gpu.measure(engine_dir)
        steps.append(f"rendering: {gpu.describe()}")
    except Exception as exc:  # noqa: BLE001 - never fail setup over a measurement
        steps.append(f"rendering: could not be measured ({exc})")

    # Profiles from before kiwi-proxy get their exit now rather than at their
    # first launch, so `kiwi-proxy list` shows every identity.
    registered = 0
    for profile in store.list_profiles():
        try:
            store.sync_exit(profile)
            registered += 1
        except Exception as exc:  # noqa: BLE001 - one profile must not fail setup
            steps.append(f"exit for {profile.name}: not registered ({exc})")
    steps.append(f"exits: {registered} profile(s) registered with kiwi-proxy")

    # Last, because it ends with its own "Done.".
    try:
        steps += proxy_setup.run(progress)
    except proxy_setup.SetupError as exc:
        raise SetupError(str(exc)) from exc
    return steps


def setup_module(name: str, progress: Progress | None = None) -> None:
    """Build/pull a single provider module's image. For `kiwi-fox module setup`."""
    try:
        proxy_setup.setup_module(name, progress)
    except proxy_setup.SetupError as exc:
        raise SetupError(str(exc)) from exc
