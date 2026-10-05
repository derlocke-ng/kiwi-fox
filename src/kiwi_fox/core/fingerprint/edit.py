"""Change what an existing profile reports.

A fingerprint is frozen at creation so that an identity never drifts by accident.
Changing it on purpose is a different thing, and this is where it happens: one
function per kind of change, each returning a new fingerprint that the caller
validates before saving. The CLI's `set` and the GUI's editor both go through
here, so neither can produce a profile the other would refuse.
"""

from __future__ import annotations

from ..models import BatteryBlock, Fingerprint, ScreenBlock, WindowBlock
from . import fonts
from . import windows11 as w11


class EditError(ValueError):
    pass


def screen_choices(form: str) -> list[w11.ScreenPreset]:
    return [s for s in w11.SCREENS if s.form == form]


def screen_label(preset: w11.ScreenPreset) -> str:
    scale = "" if preset.dpr == 1.0 else f" at {int(preset.dpr * 100)}%"
    return f"{preset.width}x{preset.height}{scale}"


def with_screen(fp: Fingerprint, spec: str) -> Fingerprint:
    """`spec` is WIDTHxHEIGHT, one of the resolutions real machines report."""
    try:
        width, height = (int(part) for part in spec.lower().split("x"))
    except ValueError:
        raise EditError(f"{spec!r} is not WIDTHxHEIGHT") from None
    choices = screen_choices(fp.form_factor)
    preset = next((s for s in choices if (s.width, s.height) == (width, height)), None)
    if preset is None:
        raise EditError(
            f"{spec} is not offered for a {fp.form_factor}: only resolutions with a "
            "large real-world share are, because rare ones stand out. Choose from "
            + ", ".join(screen_label(s) for s in choices)
        )
    avail = preset.height - w11.TASKBAR_CSS_PX
    out = fp.model_copy(deep=True)
    out.screen = ScreenBlock(
        width=preset.width,
        height=preset.height,
        avail_width=preset.width,
        avail_height=avail,
        device_pixel_ratio=preset.dpr,
    )
    out.window = WindowBlock(
        outer_width=preset.width,
        outer_height=avail,
        inner_width=preset.width,
        inner_height=avail - w11.CHROME_CSS_PX,
    )
    return out


def with_form(fp: Fingerprint, form: str) -> Fingerprint:
    """Desktop or laptop: battery, camera and the screens on offer follow."""
    if form not in ("desktop", "laptop"):
        raise EditError("the machine is a desktop or a laptop")
    out = fp.model_copy(deep=True)
    out.form_factor = form  # type: ignore[assignment]
    if form == "desktop":
        out.battery = BatteryBlock(charging=True, level=1.0, charging_time=0.0)
    else:
        out.battery = BatteryBlock(charging=True, level=0.8, charging_time=1800.0)
        out.media_devices = {**out.media_devices, "micros": 1, "webcams": 1}
    if not any(
        (s.width, s.height) == (fp.screen.width, fp.screen.height) for s in screen_choices(form)
    ):
        out = with_screen(out, screen_label(screen_choices(form)[0]).split(" ")[0])
    return out


def with_region(fp: Fingerprint, country: str, *, keep_timezone: bool = False) -> Fingerprint:
    """Locale, languages, Accept-Language, voices — and the timezone, unless kept."""
    region = w11.REGIONS.get(country.upper())
    if region is None:
        raise EditError(f"no region {country!r}; choose from {', '.join(sorted(w11.REGIONS))}")
    out = fp.model_copy(deep=True)
    out.locale = region.locale
    out.languages = list(region.languages)
    out.accept_language = w11.accept_language_for(region.languages)
    out.voices = w11.voices_for(region)
    if not keep_timezone:
        out.timezone = region.timezone
    return out


def with_timezone(fp: Fingerprint, timezone: str) -> Fingerprint:
    import zoneinfo

    try:
        zoneinfo.ZoneInfo(timezone)
    except (KeyError, ValueError, zoneinfo.ZoneInfoNotFoundError):
        raise EditError(f"{timezone!r} is not an IANA timezone, e.g. Europe/Berlin") from None
    out = fp.model_copy(deep=True)
    out.timezone = timezone
    return out


def with_cores(fp: Fingerprint, cores: int) -> Fingerprint:
    out = fp.model_copy(deep=True)
    out.hardware_concurrency = cores
    return out


def with_audio_rate(fp: Fingerprint, rate: int) -> Fingerprint:
    if rate not in w11.SAMPLE_RATES:
        raise EditError(f"sample rate must be one of {', '.join(map(str, w11.SAMPLE_RATES))}")
    out = fp.model_copy(deep=True)
    out.audio.sample_rate = rate
    return out


def with_camera(fp: Fingerprint, present: bool) -> Fingerprint:
    out = fp.model_copy(deep=True)
    # Always a microphone beside a camera: without one the engine's device list
    # takes the tab down (see generator.py).
    out.media_devices = {**out.media_devices, "micros": 1, "webcams": int(present)}
    return out


def optional_fonts() -> list[str]:
    """Families a profile may or may not have; the Windows core is not negotiable."""
    return sorted(set(fonts.all_optional_families()) | set(fonts.all_third_party_families()))


def with_fonts(fp: Fingerprint, *, add: list[str] = (), remove: list[str] = ()) -> Fingerprint:
    known = {name.lower(): name for name in optional_fonts()}
    core = set(fonts.all_core_families())
    families = set(fp.fonts)
    for name in add:
        if name.lower() not in known:
            raise EditError(f"{name!r} is not a font this engine can offer; see `kiwi-fox fonts`")
        families.add(known[name.lower()])
    for name in remove:
        match = known.get(name.lower())
        if match is None:
            if name.lower() in {c.lower() for c in core}:
                raise EditError(f"{name!r} ships with every Windows 11 and cannot be removed")
            raise EditError(f"{name!r} is not a font this engine can offer; see `kiwi-fox fonts`")
        families.discard(match)
    out = fp.model_copy(deep=True)
    out.fonts = sorted(families)
    out.font_files = fonts.files_for(out.fonts)
    return out


def check_user_agent(ua: str, engine_version: str) -> list[str]:
    """Why a custom user agent will stand out. Empty when it will not."""
    major = engine_version.split(".")[0]
    notes = []
    if "Windows NT 10.0; Win64; x64" not in ua:
        notes.append(
            "it does not say Windows: fonts, WebGL and voices all still say Windows 11, "
            "and Firefox writes Windows 10 and 11 identically (Windows NT 10.0)"
        )
    if f"rv:{major}.0" not in ua or f"Firefox/{major}.0" not in ua:
        notes.append(
            f"it does not say Firefox {major}: the engine really is Firefox {major}, and pages "
            "can tell a version by what it can do"
        )
    return notes
