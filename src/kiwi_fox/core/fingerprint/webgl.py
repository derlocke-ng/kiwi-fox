"""WebGL the way Firefox on Windows presents it.

Firefox never shows a page the real graphics card. Before a renderer string
reaches JavaScript, dom/canvas/SanitizeRenderer.cpp collapses it into one of a
handful of representative devices — "GeForce RTX 3090" becomes "GeForce GTX 980",
the example in that file's own header — and plain getParameter(RENDERER) returns
the same collapsed string as WEBGL_debug_renderer_info does. So a real Windows
Firefox can only ever report one of a few *series*, never a card, and it reports
it in both places.

That is what a profile carries here: one series, written the way Firefox writes
it, in the masked and the unmasked value alike, together with the limits, the
extension list and the shader precision that belong to it. The records are real
ones, taken from Camoufox's database of Windows Firefox fingerprints
(data/webgl-windows.json, refreshed by tools/import-webgl-data.py).

Verified on the test VM against engine 152.0.4-beta.30: every value emitted here
is what the page then reads back. What stays the host's is what the GPU actually
draws — the pixels read back from a rendered frame are identical whichever series
is claimed.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

from .sanitizer import representative_device, sanitize_renderer

DATA = Path(__file__).parent / "data" / "webgl-windows.json"

Mode = str  # "host" | "preset" | "custom" | "off"


class Series(NamedTuple):
    key: str
    family: str  # amd | intel | nvidia
    kind: str  # "gpu" (discrete) | "igpu" (integrated)
    angle: str  # ANGLE's vendor token
    device: str  # the device Firefox reports for every card in the series
    label: str
    covers: str  # real hardware Firefox reports as this
    forms: tuple[str, ...]
    cores: tuple[int, ...]  # logical CPUs that plausibly sit beside it; never < 6

    @property
    def vendor(self) -> str:
        return f"Google Inc. ({self.angle})"

    @property
    def renderer(self) -> str:
        return f"ANGLE ({self.angle}, {self.device} Direct3D11 vs_5_0 ps_5_0), or similar"

    @property
    def tier(self) -> str:
        return "integrated" if self.kind == "igpu" else "mid"


# Ordered by how common each is among real Windows Firefox users. `covers` is not
# a guess: tests feed those card names through the sanitiser port and
# require this series to come out.
SERIES: tuple[Series, ...] = (
    Series(
        "geforce-gtx-980",
        "nvidia",
        "gpu",
        "NVIDIA",
        "NVIDIA GeForce GTX 980",
        "NVIDIA GeForce — GTX 900 and newer, every RTX",
        "GTX 950–1080 Ti, GTX 1630–1660, RTX 20/30/40/50 series, desktop and laptop",
        ("desktop", "laptop"),
        (6, 8, 12, 16),
    ),
    Series(
        "intel-hd",
        "intel",
        "igpu",
        "Intel",
        "Intel(R) HD Graphics",
        "Intel integrated — Iris Xe, UHD (11th gen and newer)",
        "Iris Xe, UHD Graphics without a model number, HD Graphics 2000–4600",
        ("laptop",),
        (8, 12, 16),
    ),
    Series(
        "intel-hd-400",
        "intel",
        "igpu",
        "Intel",
        "Intel(R) HD Graphics 400",
        "Intel integrated — UHD 600/700 series",
        "UHD 620/630/730/770, HD 520/530/630, Iris Plus 640/655",
        ("desktop", "laptop"),
        (6, 8, 12),
    ),
    Series(
        "radeon-hd-3200",
        "amd",
        "igpu",
        "AMD",
        "Radeon HD 3200 Graphics",
        "AMD integrated — Radeon Graphics (Ryzen APUs)",
        "Ryzen 4000–7000 processors whose graphics are named just “Radeon(TM) Graphics”",
        ("desktop", "laptop"),
        (6, 8, 12, 16),
    ),
    Series(
        "radeon-r9-200",
        "amd",
        "gpu",
        "AMD",
        "Radeon R9 200 Series",
        "AMD Radeon — RX and R-series, Vega, 600M/700M",
        "RX 460–7900, R5/R7/R9, Vega 8/11, Radeon 660M/680M/780M",
        ("desktop", "laptop"),
        (6, 8, 12, 16),
    ),
    Series(
        "geforce-gtx-480",
        "nvidia",
        "gpu",
        "NVIDIA",
        "NVIDIA GeForce GTX 480",
        "NVIDIA GeForce — GTX 400 to 700 series",
        "GTX 460–780 Ti, GT 710–740, MX 450",
        ("desktop", "laptop"),
        (8, 12),
    ),
)

BY_KEY = {s.key: s for s in SERIES}

# When all we know about the host is its vendor. Each is the series a current
# card of that vendor lands in.
FAMILY_DEFAULT = {"amd": "radeon-r9-200", "intel": "intel-hd-400", "nvidia": "geforce-gtx-980"}


# ---------------------------------------------------------------- the records
@lru_cache(maxsize=1)
def _records() -> dict[str, dict]:
    return {r["renderer"]: r for r in json.loads(DATA.read_text())["records"]}


def record(series: Series) -> dict:
    return _records()[series.renderer]


def share(series: Series) -> float:
    """Fraction of Windows Firefox users in the source database reporting this."""
    return float(record(series)["share"])


# ------------------------------------------------------- Firefox's sanitiser
# Ported from Firefox in sanitizer.py, which carries its own (MPL-2.0) licence.


def _device_of(reported: str) -> str:
    """The bare device inside a string Firefox reported, on any platform."""
    text = reported.removesuffix(", or similar")
    if text.startswith("ANGLE (") and ", " in text:
        text = text.split(", ", 1)[1].split(" Direct3D", 1)[0]
    return text.removeprefix("NVIDIA ").strip()


# Chrome writes the PCI device id into its ANGLE string; Firefox does not. Earlier
# profiles stored Chrome-style strings, and the id's digits would otherwise be read
# as a model number.
_PCI_ID = re.compile(r" \(0x[0-9A-Fa-f]+\)")


def series_for(text: str | None) -> Series | None:
    """The series a renderer belongs to, whatever spelling it arrives in.

    Accepts a series key, the exact Windows string, a string Firefox reported on
    Linux ("Radeon R9 200 Series, or similar"), or a driver's raw name — including
    the Chrome-style strings earlier profiles stored, which is how those profiles
    keep working without being regenerated.
    """
    if not text:
        return None
    if text in BY_KEY:
        return BY_KEY[text]
    text = _PCI_ID.sub("", text)
    for candidate in (text, sanitize_renderer(text)):
        if not candidate:
            continue
        device = _device_of(candidate)
        for series in SERIES:
            if device == series.device.removeprefix("NVIDIA "):
                return series
    return None


_WORDS = {
    w.lower(): w
    for w in (
        "GeForce", "Radeon", "NVIDIA", "AMD", "Intel", "Graphics", "RTX", "GTX", "GT", "RX",
        "UHD", "HD", "Iris", "Xe", "Vega", "Quadro", "TITAN", "Arc", "Plus", "Ti",
    )
}  # fmt: skip


def _as_card_name(query: str) -> str | None:
    """A driver-style name for what a person typed, e.g. "rtx 3060"."""
    words = [_WORDS.get(w.lower(), w) for w in re.sub(r"\((R|TM)\)", "", query).split()]
    text = " ".join(words)
    low = text.lower()
    if re.search(r"\b(rtx|gtx|gt|geforce|quadro|titan|nvidia)\b|\bmx ?\d", low):
        named = any(w in text for w in ("GeForce", "Quadro", "TITAN"))
        return text if named else f"NVIDIA GeForce {text}"
    if re.search(r"\b(rx|radeon|vega|r[579]|amd)\b", low):
        return text if "Radeon" in text else f"AMD Radeon {text}"
    if re.search(r"\b(uhd|iris|intel|hd|arc)\b", low):
        number = re.search(r"\b(\d{3,4})\b", text)
        model = number.group(1) if number else ""
        rest = [w for w in words if w not in ("Intel", "Graphics", model)]
        return f"Intel(R) {' '.join(rest)} Graphics {model}".strip()
    return None


def find(query: str) -> Series:
    """Resolve what a person typed: a key, a card name, or part of a label."""
    hit = series_for(query)
    if hit:
        return hit
    low = query.lower()
    matches = [s for s in SERIES if low in f"{s.key} {s.label} {s.covers} {s.device}".lower()]
    if len(matches) == 1:
        return matches[0]
    name = _as_card_name(query)
    device = representative_device(name) if name else None
    hit = series_for(f"{device}, or similar") if device else None
    if hit:
        return hit
    raise ValueError(
        f"{query!r} does not name one GPU series; choose from: " + ", ".join(s.key for s in SERIES)
    )


# ------------------------------------------------------------- what is emitted
# Limits fixed for the life of a context. Only these are safe to pin: everything
# else in the upstream record is *state* — the viewport, bindings, enables, masks
# — and pinning state makes the browser lie about what the page itself just set.
# Measured: with the whole record applied, a 64x64 canvas reported a 300x150
# viewport.
CAPABILITIES = frozenset(
    {
        3379,  # MAX_TEXTURE_SIZE
        3386,  # MAX_VIEWPORT_DIMS
        3408,  # SUBPIXEL_BITS
        33901,  # ALIASED_POINT_SIZE_RANGE
        33902,  # ALIASED_LINE_WIDTH_RANGE
        34024,  # MAX_RENDERBUFFER_SIZE
        34076,  # MAX_CUBE_MAP_TEXTURE_SIZE
        34921,  # MAX_VERTEX_ATTRIBS
        34930,  # MAX_TEXTURE_IMAGE_UNITS
        35660,  # MAX_VERTEX_TEXTURE_IMAGE_UNITS
        35661,  # MAX_COMBINED_TEXTURE_IMAGE_UNITS
        36347,  # MAX_VERTEX_UNIFORM_VECTORS
        36348,  # MAX_VARYING_VECTORS
        36349,  # MAX_FRAGMENT_UNIFORM_VECTORS
        # WebGL 2
        32883,  # MAX_3D_TEXTURE_SIZE
        33000,  # MAX_ELEMENTS_VERTICES
        33001,  # MAX_ELEMENTS_INDICES
        34045,  # MAX_TEXTURE_LOD_BIAS
        34852,  # MAX_DRAW_BUFFERS
        35071,  # MAX_ARRAY_TEXTURE_LAYERS
        35076,  # MIN_PROGRAM_TEXEL_OFFSET
        35077,  # MAX_PROGRAM_TEXEL_OFFSET
        35371,  # MAX_VERTEX_UNIFORM_BLOCKS
        35373,  # MAX_FRAGMENT_UNIFORM_BLOCKS
        35374,  # MAX_COMBINED_UNIFORM_BLOCKS
        35375,  # MAX_UNIFORM_BUFFER_BINDINGS
        35376,  # MAX_UNIFORM_BLOCK_SIZE
        35377,  # MAX_COMBINED_VERTEX_UNIFORM_COMPONENTS
        35379,  # MAX_COMBINED_FRAGMENT_UNIFORM_COMPONENTS
        35380,  # UNIFORM_BUFFER_OFFSET_ALIGNMENT
        35657,  # MAX_FRAGMENT_UNIFORM_COMPONENTS
        35658,  # MAX_VERTEX_UNIFORM_COMPONENTS
        35659,  # MAX_VARYING_COMPONENTS
        35968,  # MAX_TRANSFORM_FEEDBACK_SEPARATE_COMPONENTS
        35978,  # MAX_TRANSFORM_FEEDBACK_INTERLEAVED_COMPONENTS
        35979,  # MAX_TRANSFORM_FEEDBACK_SEPARATE_ATTRIBS
        36063,  # MAX_COLOR_ATTACHMENTS
        36183,  # MAX_SAMPLES
        36203,  # MAX_ELEMENT_INDEX
        37137,  # MAX_SERVER_WAIT_TIMEOUT
        37154,  # MAX_VERTEX_OUTPUT_COMPONENTS
        37157,  # MAX_FRAGMENT_INPUT_COMPONENTS
        37447,  # MAX_CLIENT_WAIT_TIMEOUT_WEBGL
    }
)

# The one deliberate exception to "never pin state". These four stencil masks are
# state, but their value in a fresh context differs by platform — ANGLE reports
# 0x7FFFFFFF where Mesa reports 0xFF — and fingerprinting scripts dump them from a
# fresh context. Left alone they say "Linux" under a Windows claim. The cost: a
# page that sets a stencil mask and reads it straight back gets the default.
PLATFORM_DEFAULTS = frozenset(
    {
        2963,  # STENCIL_VALUE_MASK
        2968,  # STENCIL_WRITEMASK
        36004,  # STENCIL_BACK_VALUE_MASK
        36005,  # STENCIL_BACK_WRITEMASK
    }
)

_VENDOR, _RENDERER = "7936", "7937"
MASKED_VENDOR = "Mozilla"  # constant in every Firefox


def engine_config(
    series: Series, *, vendor: str | None = None, renderer: str | None = None
) -> dict[str, object]:
    """Camoufox config keys for one series; the strings may be overridden.

    The unmasked strings go in `webGl:vendor`/`webGl:renderer` and deliberately
    *not* in the parameter table: the table is consulted before Firefox checks
    that WEBGL_debug_renderer_info was enabled, so putting them there would
    answer a query that a real Firefox rejects.
    """
    rec = record(series)
    vendor = vendor or series.vendor
    renderer = renderer or series.renderer
    pinned = CAPABILITIES | PLATFORM_DEFAULTS
    out: dict[str, object] = {"webGl:vendor": vendor, "webGl:renderer": renderer}
    for ctx in ("webGl", "webGl2"):
        table = rec[f"{ctx}:parameters"]
        params = {k: v for k, v in table.items() if int(k) in pinned and v is not None}
        params[_VENDOR] = MASKED_VENDOR
        params[_RENDERER] = renderer
        out[f"{ctx}:parameters"] = dict(sorted(params.items(), key=lambda kv: int(kv[0])))
        out[f"{ctx}:supportedExtensions"] = list(rec[f"{ctx}:supportedExtensions"])
        out[f"{ctx}:shaderPrecisionFormats"] = dict(rec[f"{ctx}:shaderPrecisionFormats"])
    return out


# ------------------------------------------------------------------- the host
HOST_FILE = "host-webgl-bucket.txt"


def measured_host_renderer() -> str | None:
    """What this host's own Firefox reported when nothing was spoofed.

    Written only by a raw probe (`kiwi-fox selfcheck --host`). Once WebGL is
    spoofed properly a normal probe reads back the spoof, not the machine.
    """
    from ..paths import config_dir

    path = config_dir() / HOST_FILE
    if not path.exists():
        return None
    return path.read_text().strip() or None


def remember_host_renderer(renderer: str | None) -> None:
    from ..paths import config_dir

    if not renderer:
        return
    config_dir().mkdir(parents=True, exist_ok=True)
    (config_dir() / HOST_FILE).write_text(renderer.strip() + "\n")


def host_series() -> tuple[Series | None, str]:
    """-> (series, how we know): "measured", "family" or "unknown".

    "measured" is exact. "family" means only the vendor is known and the series
    is that vendor's usual one — close, and coherent either way, because the
    whole record is emitted together.
    """
    from .. import gpu

    hit = series_for(measured_host_renderer())
    if hit:
        return hit, "measured"
    family = gpu.host_family()
    if family in FAMILY_DEFAULT:
        return BY_KEY[FAMILY_DEFAULT[family]], "family"
    return None, "unknown"


def resolve(
    mode: Mode,
    *,
    stored_renderer: str | None = None,
    series_key: str | None = None,
    custom_renderer: str | None = None,
) -> Series | None:
    """The series whose record a profile is launched with. None means WebGL off.

    host    this machine's series, re-read at every launch
    preset  the profile's own choice, else the one frozen in its fingerprint
    custom  the series the custom string would belong to, for its limits
    """
    if mode == "off":
        return None
    frozen = BY_KEY.get(series_key or "") or series_for(stored_renderer)
    fallback = frozen or host_series()[0] or SERIES[0]
    if mode == "host":
        return host_series()[0] or fallback
    if mode == "custom":
        return series_for(custom_renderer) or _same_vendor(custom_renderer) or fallback
    return fallback


def _same_vendor(renderer: str | None) -> Series | None:
    low = (renderer or "").lower()
    for family, key in FAMILY_DEFAULT.items():
        names = {"amd": ("amd", "radeon"), "intel": ("intel",), "nvidia": ("nvidia", "geforce")}
        if any(n in low for n in names[family]):
            return BY_KEY[key]
    return None
