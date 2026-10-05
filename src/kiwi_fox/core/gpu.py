"""The host's real graphics hardware, as far as it can be read without a browser."""

from __future__ import annotations

from pathlib import Path

DRM = Path("/sys/class/drm")

# PCI vendor ids.
PCI_VENDORS = {"0x1002": "amd", "0x8086": "intel", "0x10de": "nvidia"}

# The browser image carries Mesa and nothing else, so a node bound to the
# proprietary NVIDIA driver cannot be used from inside it: there is no userspace
# for it there. On a hybrid laptop that is exactly the difference between the two
# nodes, and nothing guarantees the usable one is renderD128.
UNUSABLE_DRIVERS = {"nvidia"}


def _driver(node: Path) -> str | None:
    link = node / "device" / "driver"
    try:
        return link.resolve().name if link.exists() else None
    except OSError:
        return None


def render_node() -> str | None:
    """The DRM render node to hand to the browser, or None if Mesa can drive none.

    A render node, never a card node: card* is display/KMS and belongs to the
    compositor. Render nodes are mode 666 on Fedora, so no group juggling.
    """
    for node in sorted(DRM.glob("renderD*")):
        if _driver(node) in UNUSABLE_DRIVERS:
            continue
        dev = Path("/dev/dri") / node.name
        if dev.exists():
            return str(dev)
    return None


def host_family() -> str | None:
    """Vendor family of the GPU the browser will actually render on."""
    node = render_node()
    candidates = [DRM / Path(node).name] if node else sorted(DRM.glob("card[0-9]*"))
    for candidate in candidates:
        try:
            vendor = (candidate / "device" / "vendor").read_text().strip().lower()
        except OSError:
            continue
        if vendor in PCI_VENDORS:
            return PCI_VENDORS[vendor]
    return None
