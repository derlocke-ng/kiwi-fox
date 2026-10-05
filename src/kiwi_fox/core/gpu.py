"""The host's graphics hardware, and how a container gets to draw on it.

A browser that draws in software is the classic virtual-machine signature: the
frame comes out of llvmpipe whatever the profile claims, and sites can read frames.
So this is not a performance detail. Whether the browser really reaches a GPU is
decided here, and it is *measured* — with the engine's own probe, in a throwaway
container, with no window — rather than assumed from a device node existing.

That assumption was the bug. On a hybrid laptop whose panel hangs off the NVIDIA
card, the desktop tells every client to use that GPU; a container holding only
Mesa and the integrated GPU's node cannot open it, and Mesa silently falls back
to software. Measured on such a machine: integrated node alone, llvmpipe; both
nodes plus DRI_PRIME, the integrated GPU; the host's NVIDIA driver injected
through CDI, the NVIDIA GPU.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
from pathlib import Path
from typing import NamedTuple

DRM = Path("/sys/class/drm")
DEV = Path("/dev/dri")

# PCI vendor ids.
PCI_VENDORS = {"0x1002": "amd", "0x8086": "intel", "0x10de": "nvidia"}

# The browser image carries Mesa and nothing else, so a node bound to the
# proprietary NVIDIA driver has no userspace there unless the host injects it.
PROPRIETARY = {"nvidia"}

# Where nvidia-container-toolkit writes the description of what to inject.
CDI_SPECS = (Path("/etc/cdi/nvidia.yaml"), Path("/var/run/cdi/nvidia.yaml"))
CDI_DEVICE = "nvidia.com/gpu=all"

SOFTWARE_RENDERERS = ("llvmpipe", "softpipe", "swrast", "SwiftShader")
MEASUREMENT_FILE = "host-gpu.json"


class Node(NamedTuple):
    path: str  # /dev/dri/renderD128
    driver: str | None
    vendor: str | None  # PCI ids, as sysfs spells them: "0x1002"
    device: str | None
    primary: bool  # the GPU the desktop itself runs on

    @property
    def family(self) -> str | None:
        return PCI_VENDORS.get(self.vendor or "")


class Plan(NamedTuple):
    """What the browser container is given so it can draw.

    mesa        one node the image's own drivers can use
    mesa-prime  the desktop's GPU is proprietary: its node is passed too, so Mesa
                can open the device the desktop names, and DRI_PRIME moves the
                drawing to the GPU Mesa can drive
    nvidia      the host's NVIDIA driver, injected by nvidia-container-toolkit
    software    nothing usable — the browser will draw in software, and say so
    """

    kind: str
    devices: tuple[str, ...]
    env: dict[str, str]
    family: str | None
    note: str


def _read(path: Path) -> str | None:
    try:
        return path.read_text().strip() or None
    except OSError:
        return None


def _driver(pci: Path) -> str | None:
    link = pci / "driver"
    try:
        return link.resolve().name if link.exists() else None
    except OSError:
        return None


def _drives_a_display(pci: Path) -> bool:
    if _read(pci / "boot_vga") == "1":
        return True
    return any(_read(status) == "connected" for status in pci.glob("drm/card*/card*-*/status"))


def nodes() -> list[Node]:
    out = []
    for node in sorted(DRM.glob("renderD*")):
        dev = DEV / node.name
        if not dev.exists():
            continue
        pci = node / "device"
        out.append(
            Node(
                str(dev),
                _driver(pci),
                (_read(pci / "vendor") or "").lower() or None,
                (_read(pci / "device") or "").lower() or None,
                _drives_a_display(pci),
            )
        )
    return out


def cdi_nvidia() -> bool:
    return any(spec.exists() for spec in CDI_SPECS)


def plan(prefer: str | None = None) -> Plan:
    """How to reach a GPU from the browser container on this host.

    `prefer` (or $KIWI_FOX_GPU) forces one path: mesa, nvidia or software. The
    default follows the GPU the desktop runs on, because that is the one path
    where drawing and showing happen on the same card.
    """
    prefer = (prefer or os.environ.get("KIWI_FOX_GPU") or "auto").lower()
    found = nodes()
    if prefer == "software":
        return Plan("software", (), {}, None, "software rendering was asked for")
    if not found:
        return Plan("software", (), {}, None, "this machine exposes no GPU render node")

    usable = [n for n in found if n.driver not in PROPRIETARY]
    nvidia = [n for n in found if n.driver == "nvidia"]
    primary = next((n for n in found if n.primary), found[0])

    wants_nvidia = prefer == "nvidia" or (prefer == "auto" and primary.driver == "nvidia")
    if wants_nvidia and nvidia and cdi_nvidia():
        return Plan(
            "nvidia",
            (CDI_DEVICE,),
            {},
            "nvidia",
            "the desktop runs on the NVIDIA GPU; its driver is injected by the host (CDI)",
        )
    if usable:
        target = primary if primary in usable else usable[0]
        if primary.driver in PROPRIETARY and target.vendor and target.device:
            return Plan(
                "mesa-prime",
                (target.path, primary.path),
                {"DRI_PRIME": f"{target.vendor[2:]}:{target.device[2:]}"},
                target.family,
                "the desktop runs on the NVIDIA GPU; drawing on the other GPU instead, "
                + (
                    "as asked"
                    if cdi_nvidia()
                    else "because this container has no NVIDIA driver "
                    "(nvidia-container-toolkit is not set up)"
                ),
            )
        return Plan("mesa", (target.path,), {}, target.family, "")
    return Plan(
        "software",
        (),
        {},
        None,
        "the only GPU uses the proprietary NVIDIA driver and nvidia-container-toolkit "
        "is not set up, so the container has no driver for it",
    )


def host_family() -> str | None:
    """Vendor family of the GPU the browser will draw on."""
    return plan().family


# ------------------------------------------------------------------ measuring
def _helper(engine_dir: Path) -> tuple[str, list[str]] | None:
    """The engine's GPU probe and how its own Firefox invokes it."""
    if (engine_dir / "gfxtest").exists():  # Firefox 156 and later: one merged binary
        return "gfxtest", ["glx", "-f", "1", "-w"]
    if (engine_dir / "glxtest").exists():
        return "glxtest", ["-f", "1", "-w"]
    return None


def parse_probe(text: str) -> dict[str, object]:
    """The probe writes KEY and VALUE on alternating lines."""
    tokens = text.split("\n")
    fields: dict[str, str] = {}
    warnings: list[str] = []
    for key, value in zip(tokens[0::2], tokens[1::2], strict=False):
        if key in ("WARNING", "ERROR"):
            warnings.append(value)
        elif key:
            fields[key] = value
    renderer = fields.get("RENDERER", "")
    software = (
        not renderer
        or fields.get("MESA_ACCELERATED") == "FALSE"
        or any(s in renderer or s == fields.get("DRI_DRIVER") for s in SOFTWARE_RENDERERS)
    )
    return {
        "renderer": renderer,
        "vendor": fields.get("VENDOR", ""),
        "driver": fields.get("DRI_DRIVER", ""),
        "device": fields.get("DRM_RENDERDEVICE", ""),
        "accelerated": not software,
        "warnings": warnings,
    }


def measure(
    engine_dir: Path, image: str = "kiwi-fox/browser:latest", plan_: Plan | None = None
) -> dict[str, object]:
    """Ask the engine's own GPU probe what it gets, and remember the answer.

    The helper Firefox runs at startup, in a throwaway container with the devices
    and environment the browser will have — so this is the answer the browser will
    act on. It connects to the display but opens no window.
    """
    chosen = plan_ or plan()
    helper = _helper(engine_dir)
    result: dict[str, object]
    if helper is None:
        result = parse_probe("")
        result["warnings"] = ["the engine has no GPU probe helper"]
    else:
        name, args = helper
        cmd = [
            "podman", "run", "--rm", "--network", "none", "--userns", "keep-id",
            "--cap-drop", "all", "--security-opt", "no-new-privileges",
            "--security-opt", "label=disable", "--entrypoint", f"/opt/camoufox/{name}",
            "-v", f"{engine_dir}:/opt/camoufox:ro",
        ]  # fmt: skip
        runtime, display = os.environ.get("XDG_RUNTIME_DIR"), os.environ.get("WAYLAND_DISPLAY")
        if runtime and display and (Path(runtime) / display).exists():
            inside = f"/run/user/{os.getuid()}"
            cmd += ["-v", f"{runtime}/{display}:{inside}/{display}"]
            cmd += ["-e", f"XDG_RUNTIME_DIR={inside}", "-e", f"WAYLAND_DISPLAY={display}"]
        for device in chosen.devices:
            cmd += ["--device", device]
        for key, value in chosen.env.items():
            cmd += ["-e", f"{key}={value}"]
        try:
            proc = subprocess.run(  # noqa: S603
                [*cmd, image, *args], capture_output=True, text=True, check=False, timeout=90
            )
            result = parse_probe(proc.stdout)
            if not proc.stdout.strip():
                tail = (proc.stderr or "").strip().splitlines()[-1:] or ["no output"]
                result["warnings"] = [f"the probe failed: {tail[0]}"]
        except (OSError, subprocess.TimeoutExpired) as exc:
            result = parse_probe("")
            result["warnings"] = [f"the probe could not run: {exc}"]
    result["kind"] = chosen.kind
    result["when"] = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    _remember(result)
    return result


def _file() -> Path:
    from .paths import config_dir

    return config_dir() / MEASUREMENT_FILE


def _remember(result: dict[str, object]) -> None:
    path = _file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=1) + "\n")


def measurement() -> dict[str, object] | None:
    """The last measurement, if it was taken for the plan in force now."""
    try:
        data = json.loads(_file().read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("kind") == plan().kind else None


def accelerated() -> bool:
    """Will the browser draw on a GPU? Believe a measurement over the plan."""
    if plan().kind == "software":
        return False
    seen = measurement()
    return True if seen is None else bool(seen.get("accelerated"))


def describe() -> str:
    """One line for a person: what the browser draws with, and why."""
    chosen, seen = plan(), measurement()
    if seen and seen.get("accelerated"):
        how = {"nvidia": "host NVIDIA driver via CDI", "mesa-prime": "Mesa, offloaded"}.get(
            chosen.kind, "Mesa"
        )
        return f"hardware — {seen['renderer']} ({how})"
    if seen:
        # The probe's own warnings are mostly noise ("libpci missing"); what
        # matters is what it ended up with, and why the plan could do no better.
        got = seen.get("renderer") or "; ".join(seen.get("warnings") or []) or "no GPU"
        why = f"the engine's probe got {got}" + (f" — {chosen.note}" if chosen.note else "")
        return f"SOFTWARE — sites can tell, and it reads as a virtual machine ({why})"
    if chosen.kind == "software":
        return f"SOFTWARE — sites can tell, and it reads as a virtual machine ({chosen.note})"
    return f"not measured yet — planned: {chosen.kind}"
