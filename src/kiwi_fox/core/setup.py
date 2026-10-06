"""First-run setup: everything needed before a profile can launch.

Deliberately *not* done at install time — building images and downloading a
~630 MB engine needs network at the wrong moment and would make `kiwi install`
look broken. This is the one command a new user runs.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from . import dns, paths, podman, providers
from .engines import fetch as engine_fetch

IMAGES = (
    ("kiwi-fox/gateway:latest", "gateway"),
    ("kiwi-fox/browser:latest", "browser"),
)

Progress = Callable[[str], None]


class SetupError(RuntimeError):
    pass


def containers_dir() -> Path:
    """Where the Containerfiles live, in a checkout or an installed copy."""
    here = Path(__file__).resolve()
    for candidate in (here.parents[3] / "containers", here.parents[2] / "containers"):
        if (candidate / "gateway" / "Containerfile").exists():
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
    if podman._run(["image", "exists", image], check=False).returncode != 0:
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

    say("Building container images…")
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

    say("Fetching DNS resolver stamps…")
    try:
        dns.sync_stamps()
        steps.append(f"dns: {len(dns.load_stamps())} resolver stamps")
    except Exception as exc:  # noqa: BLE001
        steps.append(f"dns stamps: failed ({exc})")

    say("Downloading the ad-block list…")
    try:
        dns.fetch_blocklist("oisd-big")
        merged = dns.merged_blocklist(["oisd-big"])
        count = sum(1 for _ in merged.open())
        steps.append(f"blocklist: {count} entries")
    except Exception as exc:  # noqa: BLE001
        steps.append(f"blocklist: failed ({exc})")

    modules = providers.discover()
    if modules:
        say("Preparing provider modules…")
        for name in modules:
            try:
                prov, manifest = providers.load(name)
                ctx = providers.context_for(name, manifest)
                prov.setup(ctx)
                steps.append(f"module {name}: image ready")
            except Exception as exc:  # noqa: BLE001 - one module must not fail setup
                steps.append(f"module {name}: setup failed ({exc})")

    say("Done.")
    return steps


def setup_module(name: str, progress: Progress | None = None) -> None:
    """Build/pull a single provider module's image. For `kiwi-fox module setup`."""
    if not podman.available():
        raise SetupError("podman is not installed")
    if not providers.is_installed(name):
        raise SetupError(f"provider module {name!r} is not installed")
    prov, manifest = providers.load(name)
    ctx = providers.context_for(name, manifest)
    if progress:
        progress(f"Preparing provider module {name}…")
    prov.setup(ctx)
