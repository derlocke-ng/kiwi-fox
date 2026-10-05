"""The most important module in the repo: reject incoherent profiles.

Camoufox config keys do not cross-populate — setting navigator.platform leaves
the User-Agent alone (measured) — so coherence is entirely ours to enforce.
Every check here exists because something real would otherwise contradict
something else real.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..models import Fingerprint
from . import fonts, webgl
from . import windows11 as w11

Level = Literal["error", "warn"]

REQUIRED_PREFS: dict[str, object] = {
    "dom.webgpu.enabled": False,
    "network.proxy.failover_direct": False,
    "network.trr.mode": 5,
    "privacy.resistFingerprinting": False,
    "privacy.fingerprintingProtection": False,
}

# Prefs that are detectable by their absence — the documented pfox failure.
FORBIDDEN_PREFS = (
    "webgl.disabled",
    "dom.webaudio.enabled",
    "media.navigator.enabled",
    "browser.display.use_document_fonts",
    "privacy.firstparty.isolate",
)


@dataclass(frozen=True)
class Issue:
    level: Level
    code: str
    message: str

    def __str__(self) -> str:
        return f"[{self.level}] {self.code}: {self.message}"


def _err(code: str, msg: str) -> Issue:
    return Issue("error", code, msg)


def _warn(code: str, msg: str) -> Issue:
    return Issue("warn", code, msg)


LINUX_GL_MARKERS = ("mesa", "llvmpipe", "radeonsi", "gallium", "swrast", "nouveau", "softpipe")


def check_webgl_mode(
    mode: str,
    vendor: str | None = None,
    renderer: str | None = None,
    series: str | None = None,
) -> list[Issue]:
    """Each mode trades something; say which."""
    out: list[Issue] = []
    if mode == "raw":
        out.append(
            _warn(
                "webgl.raw",
                "raw reports this machine's real WebGL: on Linux that is Mesa's wording, "
                "limits and extension list under a Windows user agent",
            )
        )
    elif mode == "off":
        out.append(
            _warn(
                "webgl.off",
                "no WebGL at all is rare on Windows and stands out more than any GPU would",
            )
        )
    elif mode == "preset":
        if series and series not in webgl.BY_KEY:
            out.append(_err("webgl.series", f"unknown GPU series {series!r}"))
    elif mode == "custom":
        for label, value in (("vendor", vendor), ("renderer", renderer)):
            if not value:
                out.append(_err("webgl.custom", f"custom mode needs a {label} string"))
                continue
            low = value.lower()
            for marker in LINUX_GL_MARKERS:
                if marker in low:
                    out.append(
                        _err(
                            "webgl.custom.linux",
                            f"custom {label} contains {marker!r}, which names the real Linux stack",
                        )
                    )
        if renderer and not any(renderer == s.renderer for s in webgl.SERIES):
            would = webgl.series_for(renderer)
            hint = f"; a real one would say {would.renderer!r}" if would else ""
            out.append(
                _warn(
                    "webgl.custom.unreal",
                    "Firefox on Windows reports only a GPU series, never a card, so no "
                    f"real Firefox sends this renderer string{hint}",
                )
            )
    return out


def validate(
    fp: Fingerprint,
    *,
    engine_version: str | None = None,
    exit_country: str | None = None,
    prefs: dict[str, object] | None = None,
    allow_prefs: set[str] | None = None,
) -> list[Issue]:
    out: list[Issue] = []
    out += _check_os(fp, engine_version)
    out += _check_screen(fp)
    out += _check_hardware(fp)
    out += _check_fonts(fp)
    out += _check_locale(fp, exit_country)
    out += _check_seeds(fp)
    if prefs is not None:
        out += _check_prefs(prefs, allow_prefs or set())
    return out


def _check_os(fp: Fingerprint, engine_version: str | None) -> list[Issue]:
    out: list[Issue] = []
    if "Windows NT 10.0; Win64; x64" not in fp.ua:
        out.append(_err("ua.os", f"UA does not claim Windows 11/10 x64: {fp.ua!r}"))
    if "Windows NT 11" in fp.ua:
        out.append(_err("ua.nt11", "there is no Windows NT 11.0; Windows 11 reports NT 10.0"))
    for leak in ("Camoufox", "X11", "Linux", "Ubuntu"):
        if leak in fp.ua:
            out.append(_err("ua.leak", f"UA leaks {leak!r} — it must read as stock Firefox"))
    if fp.platform != "Win32":
        out.append(_err("platform", f"navigator.platform must be Win32, got {fp.platform!r}"))
    if "Windows NT 10.0" not in fp.oscpu:
        out.append(_err("oscpu", f"oscpu inconsistent with the Windows target: {fp.oscpu!r}"))
    want = engine_version or fp.engine_version
    major = want.split(".")[0]
    if f"rv:{major}.0" not in fp.ua or f"Firefox/{major}.0" not in fp.ua:
        out.append(
            _err("ua.version", f"UA version must equal the pinned engine major {major}: {fp.ua!r}")
        )
    if fp.engine_version != want:
        out.append(
            _err("engine.version", f"fingerprint built for {fp.engine_version}, engine is {want}")
        )
    return out


def _check_screen(fp: Fingerprint) -> list[Issue]:
    out: list[Issue] = []
    s, win = fp.screen, fp.window
    if s.width < s.avail_width or s.height < s.avail_height:
        out.append(_err("screen.avail", "availWidth/Height must not exceed screen"))
    if win.outer_width > s.avail_width or win.outer_height > s.avail_height:
        out.append(
            _err(
                "window.outer",
                f"window {win.outer_width}x{win.outer_height} exceeds avail "
                f"{s.avail_width}x{s.avail_height}; the real window must be sized to the spoof",
            )
        )
    if win.inner_width > win.outer_width or win.inner_height > win.outer_height:
        out.append(_err("window.inner", "inner must not exceed outer"))
    if win.outer_height - win.inner_height != w11.CHROME_CSS_PX:
        out.append(
            _warn(
                "window.chrome",
                f"outer-inner height is {win.outer_height - win.inner_height}px, expected "
                f"{w11.CHROME_CSS_PX} for stock chrome",
            )
        )
    if s.height - s.avail_height != w11.TASKBAR_CSS_PX:
        out.append(
            _warn(
                "screen.taskbar",
                f"screen-avail height is {s.height - s.avail_height}px, expected "
                f"{w11.TASKBAR_CSS_PX} for the Windows 11 taskbar",
            )
        )
    if s.device_pixel_ratio not in (1.0, 1.25, 1.5):
        out.append(_err("screen.dpr", f"DPR {s.device_pixel_ratio} is not plausible on Windows"))
    if s.color_depth != 24 or s.pixel_depth != 24:
        out.append(_warn("screen.depth", "Windows reports colorDepth/pixelDepth 24"))
    if 0 in (s.width, s.height, s.avail_width, s.avail_height):
        out.append(
            _err(
                "screen.partial",
                "incomplete screen block: an unset key falls back to the real monitor",
            )
        )
    return out


def _check_hardware(fp: Fingerprint) -> list[Issue]:
    out: list[Issue] = []
    series = webgl.series_for(fp.webgl.renderer)
    if series is None:
        out.append(_warn("webgl.unknown", "WebGL renderer is not a series Firefox reports"))
    else:
        if fp.hardware_concurrency not in series.cores:
            out.append(
                _err(
                    "cores.gpu",
                    f"{fp.hardware_concurrency} cores is not plausible beside {series.label} "
                    f"(expected one of {series.cores})",
                )
            )
        if fp.form_factor not in series.forms:
            out.append(_err("gpu.form", f"{series.label} does not ship in a {fp.form_factor}"))
    for bad in ("llvmpipe", "Mesa", "softpipe", "SwiftShader"):
        if bad in fp.webgl.renderer or bad in fp.webgl.vendor:
            out.append(_err("webgl.software", f"WebGL string leaks the real stack: {bad}"))
    if fp.webgl.family not in fp.webgl.vendor.lower().replace("inc. ", ""):
        out.append(
            _warn(
                "webgl.vendor",
                f"vendor {fp.webgl.vendor!r} does not name family {fp.webgl.family!r}",
            )
        )
    if fp.hardware_concurrency < 6:
        out.append(
            _err(
                "cores.vmlike",
                f"{fp.hardware_concurrency} cores reads as a virtual machine; 2 and 4 "
                "vCPUs are the classic VM defaults and were flagged in testing",
            )
        )
    if fp.max_touch_points < 0:
        out.append(_err("touch.count", f"maxTouchPoints {fp.max_touch_points} is impossible"))
    elif fp.max_touch_points:
        # Not a block: nothing is emitted for it, so nothing can contradict it.
        out.append(
            _warn(
                "touch.inert",
                f"the fingerprint says {fp.max_touch_points} touch points, but this engine "
                "cannot report any; pages see 0",
            )
        )
    if fp.max_touch_points and fp.form_factor == "desktop":
        out.append(_warn("touch.form", "a touch-capable desktop is unusual"))
    if fp.audio.sample_rate not in w11.SAMPLE_RATES:
        out.append(_err("audio.rate", f"sample rate {fp.audio.sample_rate} is implausible"))
    if fp.form_factor == "desktop":
        if not fp.battery.charging or fp.battery.level != 1.0:
            out.append(_err("battery.desktop", "a desktop reports charging, level 1.0"))
        if fp.battery.discharging_time is not None:
            out.append(_err("battery.desktop.time", "a desktop reports infinite dischargingTime"))
    if fp.form_factor == "laptop" and fp.media_devices.get("webcams", 0) < 1:
        out.append(_warn("media.webcam", "a laptop without a webcam is unusual"))
    if fp.media_devices.get("micros", 0) < 1 and fp.media_devices.get("webcams", 0) > 0:
        # Not a block either: the engine config adds the microphone.
        out.append(
            _warn(
                "media.crash",
                "a camera with no microphone crashes the tab on enumerateDevices() "
                "(engine bug); launched with one microphone",
            )
        )
    return out


def _check_fonts(fp: Fingerprint) -> list[Issue]:
    out: list[Issue] = []
    missing_core = [f for f in fonts.all_core_families() if f not in fp.fonts]
    if missing_core:
        out.append(
            _err(
                "fonts.core",
                f"{len(missing_core)} mandatory Windows 11 families missing: {missing_core[:5]}",
            )
        )
    known = set(fonts.CORE) | set(fonts.OPTIONAL) | set(fonts.THIRD_PARTY)
    unknown = [f for f in fp.fonts if f not in known]
    if unknown:
        out.append(_err("fonts.unknown", f"families not in the bundled set: {unknown[:5]}"))
    if not fp.font_files:
        out.append(_err("fonts.files", "no font files selected; fontconfig would expose nothing"))
    expected = fonts.files_for(fp.fonts)
    if sorted(fp.font_files) != expected:
        out.append(_err("fonts.mismatch", "font_files does not match the family list"))
    if len(fp.fonts) < len(fonts.CORE):
        out.append(
            _err("fonts.count", f"only {len(fp.fonts)} families; implausible for Windows 11")
        )
    return out


def _check_locale(fp: Fingerprint, exit_country: str | None) -> list[Issue]:
    out: list[Issue] = []
    region = next((r for r in w11.REGIONS.values() if r.locale == fp.locale), None)
    if region is None:
        out.append(_warn("locale.unknown", f"locale {fp.locale!r} has no region preset"))
    else:
        if fp.timezone != region.timezone:
            # A country can span several zones, so a timezone measured at the exit
            # legitimately differs from the region default — as long as it names the
            # same country's region prefix.
            same_area = fp.timezone.split("/")[0] == region.timezone.split("/")[0]
            level = _warn if same_area else _err
            out.append(
                level(
                    "locale.timezone",
                    f"locale {fp.locale} expects {region.timezone}, got {fp.timezone}",
                )
            )
        if exit_country and exit_country.upper() != region.country:
            out.append(
                _warn(
                    "locale.exit",
                    f"exit country {exit_country.upper()} does not match locale {fp.locale}",
                )
            )
    if not fp.languages or fp.languages[0] != fp.locale:
        out.append(_err("languages.head", "navigator.languages must start with the locale"))
    if not fp.accept_language.startswith(fp.locale):
        out.append(_err("accept_language", "Accept-Language must start with the locale"))
    return out


def _check_seeds(fp: Fingerprint) -> list[Issue]:
    out: list[Issue] = []
    # These are stable per profile, which is what makes them a different machine
    # rather than noise. Zero means unset, which collapses onto every other profile.
    if fp.canvas_seed == 0:
        out.append(_err("canvas.seed", "canvas seed unset: canvas would match every other profile"))
    if fp.audio.seed == 0:
        out.append(_err("audio.seed", "audio seed unset: audio would match every other profile"))
    if fp.font_spacing_seed == 0:
        out.append(_warn("fonts.spacing_seed", "font spacing seed unset"))
    return out


def _check_prefs(prefs: dict[str, object], allowed: set[str]) -> list[Issue]:
    out: list[Issue] = []
    for key, want in REQUIRED_PREFS.items():
        if prefs.get(key) != want:
            out.append(_err("prefs.required", f"{key} must be {want!r}, got {prefs.get(key)!r}"))
    for key in FORBIDDEN_PREFS:
        if key not in prefs:
            continue
        # A deliberately chosen deviation still has to be visible, so it warns
        # rather than passing silently.
        if key in allowed:
            out.append(_warn("prefs.rare", f"{key} is set deliberately — a strong tell"))
        else:
            out.append(_err("prefs.rare", f"{key} is detectable by its absence — do not set it"))
    return out


def validate_against(fp: Fingerprint, others: list[Fingerprint]) -> list[Issue]:
    """Two profiles sharing a machine-identifying value defeat the point."""
    out: list[Issue] = []
    for other in others:
        if other.seed == fp.seed:
            out.append(_err("dup.seed", "another profile has the same seed"))
            continue
        if other.fonts == fp.fonts:
            out.append(_warn("dup.fonts", "another profile exposes the identical font set"))
        if other.webgl.renderer == fp.webgl.renderer and other.screen == fp.screen:
            out.append(
                _warn("dup.machine", "another profile has the same GPU string and screen block")
            )
        if other.canvas_seed == fp.canvas_seed:
            out.append(_err("dup.canvas", "another profile has the same canvas seed"))
    return out


def errors(issues: list[Issue]) -> list[Issue]:
    return [i for i in issues if i.level == "error"]
