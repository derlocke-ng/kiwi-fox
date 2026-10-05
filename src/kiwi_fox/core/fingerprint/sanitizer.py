# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Firefox's WebGL renderer sanitiser, ported to Python.

A port of dom/canvas/SanitizeRenderer.cpp from Mozilla Firefox at
FIREFOX_152_0_RELEASE — the desktop vendors only — and, as a derivative of that
file, under the Mozilla Public License 2.0 rather than this project's GPL. Kept
line-for-line close to the original so a diff against a newer Firefox stays
readable.

Firefox runs every GL_RENDERER string through this before a page sees it, which is
why a page is only ever told the *series* a card belongs to.
"""

from __future__ import annotations

import re

_RADEON = re.compile(r"Radeon.*?((R[579X]|HD) )?([0-9][0-9][0-9]+)")
_FIREPRO = re.compile(r"FirePro.*?([VDW])[0-9][0-9][0-9]+")
_GEFORCE = re.compile(r"GeForce.*?([0-9][0-9][0-9]+)")
_QUADRO = re.compile(r"Quadro.*?([KMPVT]?)[0-9][0-9][0-9]+")
_TITAN = re.compile(r"TITAN( [BZXVR])?")
_INTEL = re.compile(r"Intel.*Graphics( P?([0-9][0-9][0-9]+))?")

_RADEON_HD_3000 = "Radeon HD 3200 Graphics"
_RADEON_HD_5850 = "Radeon HD 5850"
_RADEON_R9_290 = "Radeon R9 200 Series"
_GEFORCE_8800 = "GeForce 8800 GTX"
_GEFORCE_480 = "GeForce GTX 480"
_GEFORCE_980 = "GeForce GTX 980"


def representative_device(name: str) -> str | None:
    """ChooseDeviceReplacement(): the device Firefox reports in place of `name`."""
    for marker in ("REMBRANDT", "RENOIR", "Vega", "VII", "Fury"):
        if marker in name:
            return _RADEON_R9_290
    m = _RADEON.search(name)
    if m:
        if m.group(2) == "HD":
            model = int(m.group(3))
            if model >= 5000:
                return _RADEON_HD_5850
            return _RADEON_HD_3000
        return _RADEON_R9_290
    m = _FIREPRO.search(name)
    if m:
        return _RADEON_HD_3000 if m.group(1) == "V" else _RADEON_R9_290
    if "ARUBA" in name:
        return _RADEON_HD_5850
    if "AMD " in name or "FirePro" in name or "Radeon" in name:
        return _RADEON_HD_3000

    if "NVIDIA" in name or "GeForce" in name or "Quadro" in name:
        device = _nvidia(name)
        return f"NVIDIA {device}" if name.startswith("NVIDIA") else device

    if "Intel" in name:
        if "Intel(R) Arc(TM)" in name:
            return "Intel(R) Arc(TM) A750 Graphics"
        m = _INTEL.search(name)
        if m:
            if not m.group(1):
                return "Intel(R) HD Graphics"
            model = int(m.group(2))
            if model >= 5000:
                return "Intel(R) HD Graphics 400"
            if model >= 1000:
                return "Intel(R) HD Graphics"
            return "Intel(R) HD Graphics 400"
        return "Intel 945GM"
    return None


def _nvidia(name: str) -> str:
    m = _GEFORCE.search(name)
    if m:
        model = int(m.group(1))
        if model >= 8000:
            return _GEFORCE_8800
        if model >= 900:
            return _GEFORCE_980
        if model >= 400:
            return _GEFORCE_480
        return _GEFORCE_8800
    m = _QUADRO.search(name)
    if m:
        if "RTX" in name:
            return _GEFORCE_980
        if m.group(1):
            return _GEFORCE_980 if m.group(1) in "MPVT" else _GEFORCE_480
        return _GEFORCE_8800
    m = _TITAN.search(name)
    if m:
        letter = (m.group(1) or "  ")[1]
        return _GEFORCE_480 if letter in " BZ" else _GEFORCE_980
    return _GEFORCE_8800


_ANGLE_D3D = re.compile(r"ANGLE [(]([^,]*), ([^,]*)( Direct3D[^,]*), .*[)]")
_GL_ENGINE = re.compile(r"(.*) OpenGL Engine")
_PCIE_SSE2 = re.compile(r"(.*)(/PCIe?/SSE2)")
_STANDARD = re.compile(r"(.*)( [(].*[)])")


def sanitize_renderer(raw: str) -> str | None:
    """SanitizeRenderer(): what Firefox reports for a driver's raw GL_RENDERER.

    None where Firefox would fall back to "Generic Renderer".
    """
    m = _ANGLE_D3D.fullmatch(raw)
    if m:
        device = representative_device(m.group(2))
        return f"ANGLE ({m.group(1)}, {device}{m.group(3)}), or similar" if device else None
    if "ANGLE" in raw:
        return None
    for pattern in (_GL_ENGINE, _PCIE_SSE2, _STANDARD):
        m = pattern.fullmatch(raw)
        if m:
            device = representative_device(m.group(1))
            break
    else:
        device = representative_device(raw)
    return f"{device}, or similar" if device else None
