"""Windows 11 presets. Values a real machine could report, in plausible combinations.

Graphics live in webgl.py: Firefox reports a GPU series, not a card."""

from __future__ import annotations

from typing import NamedTuple

# navigator.buildID is frozen by Firefox rather than reporting the real build.
# TODO verify against a stock Firefox of the pinned major before trusting it.
FROZEN_BUILD_ID = "20181001000000"

# Windows 11 taskbar, in CSS pixels, at every scale factor. It is also exactly
# what stock Firefox reports whatever the real taskbar is: its default
# fingerprinting protection sets availHeight to height - 48 on Windows
# (nsRFPService::GetSpoofedScreenAvailSize, target ScreenAvailToResolution, which
# is on for every user since the baseline protections shipped).
TASKBAR_CSS_PX = 48
# Tab strip + nav bar at stock Camoufox chrome dimensions.
CHROME_CSS_PX = 88


class ScreenPreset(NamedTuple):
    width: int
    height: int
    dpr: float
    form: str  # desktop | laptop


# Only combinations a real Windows machine actually reports: a physical panel at
# one of Windows' offered scale factors. An earlier list contained 1280x800 @1.5,
# which no standard panel-and-scale pair produces — and fingerprint.com flagged the
# profile carrying it as a virtual machine (suspect score 21 vs 7) while the
# profile on 1536x864 @1.25, which is 1080p at 125%, passed clean. An implausible
# *combination* is a tell even when each number looks ordinary on its own.
# Narrowed empirically, not by taste. fingerprint.com flagged a profile reporting
# 2048x1152 @1.25 as a virtual machine while 1920x1080 @1.0 passed clean, and an
# earlier 1280x800 @1.5 was flagged too. Both were arithmetically valid panel and
# scale pairs; they are simply rare as *reported* resolutions. So this list holds
# only combinations that dominate real browser statistics, and 1.25 survives only
# for 1536x864 — 1080p at 125%, the most common laptop report there is. Do not add
# a resolution because the maths works; add it because real machines report it.
SCREENS: list[ScreenPreset] = [
    # Only resolutions with a large real-world share. Narrowed twice after
    # fingerprint.com's "virtual machine" signal fired: 1280x800 @1.5,
    # 2048x1152 @1.25 and 1600x900 @1.0 were each flagged, while 1920x1080 @1.0
    # was the only value that ever came back clean. Every flagged pair was a
    # valid panel-and-scale combination, so the heuristic weighs *share*, not
    # arithmetic. Do not add a resolution because the maths works.
    ScreenPreset(1920, 1080, 1.0, "desktop"),
    ScreenPreset(2560, 1440, 1.0, "desktop"),
    ScreenPreset(1920, 1080, 1.0, "laptop"),
    ScreenPreset(1536, 864, 1.25, "laptop"),
    ScreenPreset(2560, 1440, 1.0, "laptop"),
    ScreenPreset(1366, 768, 1.0, "laptop"),
]


class Region(NamedTuple):
    country: str
    timezone: str
    locale: str
    languages: tuple[str, ...]
    voices: tuple[str, ...]


# `languages` is what the Firefox build for that region announces by default, taken
# from Firefox's own table (intl/locale/rust/locale_service_glue at 156.0.1), not
# from how the locale is usually written: there is no de-AT or nl-BE Firefox, so
# Austria and Belgium run the "de" and "nl" builds, and Australia and Ireland the
# British one. `locale` is the operating system's region — what dates and numbers
# are formatted for.
REGIONS: dict[str, Region] = {
    "DE": Region(
        "DE",
        "Europe/Berlin",
        "de-DE",
        ("de", "en-US", "en"),
        ("Microsoft Hedda - German (Germany)", "Microsoft Stefan - German (Germany)"),
    ),
    "AT": Region(
        "AT",
        "Europe/Vienna",
        "de-AT",
        ("de", "en-US", "en"),
        ("Microsoft Michael - German (Austria)",),
    ),
    "CH": Region(
        "CH",
        "Europe/Zurich",
        "de-CH",
        ("de", "en-US", "en"),
        ("Microsoft Karsten - German (Switzerland)",),
    ),
    "NL": Region(
        "NL",
        "Europe/Amsterdam",
        "nl-NL",
        ("nl", "en-US", "en"),
        ("Microsoft Frank - Dutch (Netherlands)",),
    ),
    "SE": Region(
        "SE",
        "Europe/Stockholm",
        "sv-SE",
        ("sv-SE", "sv", "en-US", "en"),
        ("Microsoft Bengt - Swedish (Sweden)",),
    ),
    "FR": Region(
        "FR",
        "Europe/Paris",
        "fr-FR",
        ("fr", "fr-FR", "en-US", "en"),
        ("Microsoft Paul - French (France)", "Microsoft Hortense - French (France)"),
    ),
    "FI": Region(
        "FI",
        "Europe/Helsinki",
        "fi-FI",
        ("fi-FI", "fi", "en-US", "en"),
        ("Microsoft Heidi - Finnish (Finland)",),
    ),
    "NO": Region(
        "NO",
        "Europe/Oslo",
        "nb-NO",
        ("nb-NO", "nb", "no-NO", "no", "nn-NO", "nn", "en-US", "en"),
        ("Microsoft Jon - Norwegian (Bokmal)",),
    ),
    "DK": Region(
        "DK",
        "Europe/Copenhagen",
        "da-DK",
        ("da", "en-US", "en"),
        ("Microsoft Helle - Danish (Denmark)",),
    ),
    "GB": Region(
        "GB",
        "Europe/London",
        "en-GB",
        ("en-GB", "en"),
        (
            "Microsoft Hazel - English (United Kingdom)",
            "Microsoft George - English (United Kingdom)",
        ),
    ),
    "US": Region(
        "US",
        "America/New_York",
        "en-US",
        ("en-US", "en"),
        ("Microsoft David - English (United States)", "Microsoft Zira - English (United States)"),
    ),
    "AU": Region(
        "AU",
        "Australia/Sydney",
        "en-AU",
        ("en-GB", "en"),
        ("Microsoft Catherine - English (Australia)", "Microsoft James - English (Australia)"),
    ),
    "CA": Region(
        "CA",
        "America/Toronto",
        "en-CA",
        ("en-CA", "en-US", "en"),
        ("Microsoft Linda - English (Canada)",),
    ),
    "ES": Region(
        "ES",
        "Europe/Madrid",
        "es-ES",
        ("es-ES", "es", "en-US", "en"),
        ("Microsoft Helena - Spanish (Spain)",),
    ),
    "IT": Region(
        "IT",
        "Europe/Rome",
        "it-IT",
        ("it-IT", "it", "en-US", "en"),
        ("Microsoft Elsa - Italian (Italy)",),
    ),
    "PL": Region(
        "PL",
        "Europe/Warsaw",
        "pl-PL",
        ("pl", "en-US", "en"),
        ("Microsoft Paulina - Polish (Poland)",),
    ),
    "CZ": Region(
        "CZ",
        "Europe/Prague",
        "cs-CZ",
        ("cs", "sk", "en-US", "en"),
        ("Microsoft Jakub - Czech (Czech Republic)",),
    ),
    "IE": Region(
        "IE",
        "Europe/Dublin",
        "en-IE",
        ("en-GB", "en"),
        ("Microsoft Sean - English (Ireland)",),
    ),
    "BE": Region(
        "BE",
        "Europe/Brussels",
        "nl-BE",
        ("nl", "en-US", "en"),
        ("Microsoft Bart - Dutch (Belgium)",),
    ),
}

DEFAULT_REGION = "DE"

# What Firefox lists on Windows 11 for each installed language: the OneCore voices
# and the older SAPI "Desktop" ones. Taken from upstream's capture of real machines
# (pythonlib/camoufox/voices.json at the pinned tag), minus the Windows 7 and
# Windows Phone entries in it.
VOICES: dict[str, tuple[str, ...]] = {
    "en-US": (
        "Microsoft David - English (United States)",
        "Microsoft Mark - English (United States)",
        "Microsoft Zira - English (United States)",
        "Microsoft David Desktop - English (United States)",
        "Microsoft Zira Desktop - English (United States)",
    ),
    "en-GB": (
        "Microsoft Hazel - English (United Kingdom)",
        "Microsoft George - English (United Kingdom)",
        "Microsoft Susan - English (United Kingdom)",
        "Microsoft Hazel Desktop - English (Great Britain)",
    ),
    "en-AU": (
        "Microsoft Catherine - English (Australia)",
        "Microsoft James - English (Australia)",
    ),
    "en-CA": ("Microsoft Linda - English (Canada)", "Microsoft Richard - English (Canada)"),
    "en-IE": ("Microsoft Sean - English (Ireland)",),
    "de-DE": (
        "Microsoft Hedda - German (Germany)",
        "Microsoft Katja - German (Germany)",
        "Microsoft Stefan - German (Germany)",
        "Microsoft Hedda Desktop - German",
    ),
    "fr-FR": (
        "Microsoft Hortense - French (France)",
        "Microsoft Julie - French (France)",
        "Microsoft Paul - French (France)",
        "Microsoft Hortense Desktop - French",
    ),
    "es-ES": (
        "Microsoft Helena - Spanish (Spain)",
        "Microsoft Laura - Spanish (Spain)",
        "Microsoft Pablo - Spanish (Spain)",
        "Microsoft Helena Desktop - Spanish (Spain)",
    ),
    "it-IT": (
        "Microsoft Cosimo - Italian (Italy)",
        "Microsoft Elsa - Italian (Italy)",
        "Microsoft Elsa Desktop - Italian (Italy)",
    ),
    "nl-NL": ("Microsoft Frank - Dutch (Netherlands)",),
    "pl-PL": (
        "Microsoft Adam - Polish (Poland)",
        "Microsoft Paulina - Polish (Poland)",
        "Microsoft Paulina Desktop - Polish",
    ),
    "cs-CZ": ("Microsoft Jakub - Czech (Czech Republic)",),
}

# Names earlier profiles stored that no Windows carries, and what they should be.
VOICE_ALIASES = {
    "Microsoft Hazel - English (Great Britain)": "Microsoft Hazel - English (United Kingdom)",
    "Microsoft George - English (Great Britain)": "Microsoft George - English (United Kingdom)",
}


def voices_for(region: Region) -> list[str]:
    """Voice names for a region: the captured list where there is one.

    The seven locales without a capture (de-AT, de-CH, sv-SE, fi-FI, nb-NO, da-DK,
    nl-BE) fall back to the single name in REGIONS, which is from memory and not
    verified against a real machine.
    """
    return list(VOICES.get(region.locale) or region.voices)


def voice_language(name: str, default: str) -> str:
    for locale, names in VOICES.items():
        if name in names:
            return locale
    return default


# AudioContext sample rates a real Windows machine reports.
SAMPLE_RATES = (44100, 48000)


HOST_WINDOW_FILE = "host-window-height.txt"


# What a fresh engine window reports as outerHeight: 1040, plus the invisible 26px
# resize border GTK adds above and below on Wayland. The same on every host
# measured. Until a probe has measured this machine, assume it — a machine nobody
# has measured must not be treated as one where any screen fits.
DEFAULT_WINDOW_HEIGHT = 1092


def host_window_height() -> int:
    """How tall a window Firefox opens on this host: measured, else the default.

    The reported `innerHeight` must not exceed the spoofed `availHeight` — no real
    machine can do that, and it is a one-line check for any tampering detector. We
    cannot resize the window reliably on Wayland, so instead only screens whose
    avail height exceeds the real window are offered. Written by a probe run.
    """
    from ..paths import config_dir

    path = config_dir() / HOST_WINDOW_FILE
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return DEFAULT_WINDOW_HEIGHT


def remember_host_window_height(height: int | None) -> None:
    from ..paths import config_dir

    if not height or height <= 0:
        return
    config_dir().mkdir(parents=True, exist_ok=True)
    (config_dir() / HOST_WINDOW_FILE).write_text(f"{int(height)}\n")


def ua_for(engine_version: str) -> str:
    """Stock-Firefox UA. Camoufox's own default says 'Camoufox/<ver>', which is a
    dead giveaway, so this is never optional — measured on the test VM."""
    major = engine_version.split(".")[0]
    return (
        f"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:{major}.0) Gecko/20100101 Firefox/{major}.0"
    )


def accept_language_for(languages: tuple[str, ...] | list[str]) -> str:
    """The header Firefox 156 builds from a language list: each further language
    0.1 lower, never below 0.1 (netwerk/base/rust-helper, rust_prepare_accept_languages).

    For display only. The header itself is never sent from here: the engine is
    given the list and Firefox writes the header, so it is Firefox's own format
    on whichever version is installed. Sending our own string put a q-pattern on
    the wire (0.9, 0.7, 0.5) that no browser produces.
    """
    parts = [languages[0]]
    for index, lang in enumerate(languages[1:], start=1):
        parts.append(f"{lang};q=0.{max(10 - min(index, 10), 1)}")
    return ",".join(parts)


ENGLISH = ("en-US", "en")

# Builds whose name is not simply the first language they announce.
_BUILD_NAMES = {"fi-FI": "fi", "it-IT": "it"}


def firefox_build(locale: str) -> str:
    """The localized Firefox a profile's region runs: "de", "sv-SE", "en-GB" …

    Also the name of Mozilla's language pack for it. "en-US" where the region is
    unknown, which needs no pack.
    """
    region = next((r for r in REGIONS.values() if r.locale == locale), None)
    if region is None:
        return "en-US"
    return _BUILD_NAMES.get(region.languages[0], region.languages[0])


def browser_languages(locale: str, stored: list[str], mode: str = "local") -> list[str]:
    """The language list the browser announces.

    local    what the Firefox build for the profile's region ships as its default
             (intl/locale/rust/locale_service_glue): German Firefox says
             "de, en-US, en" — not "de-DE", which is how Chrome spells it.
    english  an English-language Firefox used in that region: "en-US, en". The
             engine *is* an en-US build, so this is the one setting under which
             nothing about language is spoofed at all.
    """
    if mode == "english":
        return list(ENGLISH)
    region = next((r for r in REGIONS.values() if r.locale == locale), None)
    return list(region.languages) if region else list(stored)
