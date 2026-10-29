"""Data model. Everything a profile is, and nothing that belongs in a secret store.

The network half — Endpoint, ExitInfo, DnsConfig, the provider models and
ContainerSpec — lives in kiwi-proxy now (``kiwi_proxy.models``), with the same
fields; it is re-exported here so profile.json and every import keep working.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from kiwi_proxy.models import (
    ContainerSpec,
    DnsConfig,
    Endpoint,
    ExitInfo,
    Lease,
    ProviderManifest,
    ProviderRecord,
    ProviderStatus,
)
from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "AudioBlock",
    "BatteryBlock",
    "ContainerSpec",
    "DnsConfig",
    "Endpoint",
    "EngineName",
    "ExitInfo",
    "Fingerprint",
    "Lease",
    "Profile",
    "ProviderManifest",
    "ProviderRecord",
    "ProviderStatus",
    "ScreenBlock",
    "WebGLBlock",
    "WindowBlock",
]

FormFactor = Literal["desktop", "laptop"]
GpuFamily = Literal["nvidia", "amd", "intel"]
GpuTier = Literal["integrated", "mid", "high"]
# Which browser a profile runs. "camoufox" is the spoofing engine (a frozen
# Windows identity, a fingerprint.json beside the profile). "firefox" and
# "torbrowser" carry no spoofed identity: stock Firefox shows this machine's own
# values, Tor Browser its own uniform crowd. Only camoufox profiles have a
# fingerprint; see store.create.
EngineName = Literal["camoufox", "firefox", "torbrowser"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScreenBlock(Strict):
    width: int
    height: int
    avail_width: int
    avail_height: int
    avail_left: int = 0
    avail_top: int = 0
    color_depth: int = 24
    pixel_depth: int = 24
    device_pixel_ratio: float


class WindowBlock(Strict):
    outer_width: int
    outer_height: int
    inner_width: int
    inner_height: int
    screen_x: int = 0
    screen_y: int = 0


class WebGLBlock(Strict):
    vendor: str
    renderer: str
    family: GpuFamily
    tier: GpuTier


class AudioBlock(Strict):
    sample_rate: int
    max_channel_count: int
    output_latency: float
    seed: int


class BatteryBlock(Strict):
    """None means Infinity: JSON has no representation for it, and pydantic
    silently serialises float("inf") to null, which then fails to load back."""

    charging: bool
    level: float
    charging_time: float | None = None
    discharging_time: float | None = None


class Fingerprint(Strict):
    """Frozen at profile creation. Regenerating it is an explicit, warned action."""

    seed: str
    # A fingerprint only ever belongs to a camoufox profile; the other engines
    # store none. Narrowed to the literal so a stray value cannot select another
    # engine, and so existing files (which all carry "camoufox") still load.
    engine: Literal["camoufox"] = "camoufox"
    engine_version: str
    build_id: str
    form_factor: FormFactor

    ua: str
    platform: str = "Win32"
    oscpu: str = "Windows NT 10.0; Win64; x64"
    hardware_concurrency: int
    max_touch_points: int = 0

    locale: str
    languages: list[str]
    accept_language: str
    timezone: str

    screen: ScreenBlock
    window: WindowBlock
    webgl: WebGLBlock
    audio: AudioBlock
    battery: BatteryBlock

    fonts: list[str]
    font_files: list[str]
    canvas_seed: int
    font_spacing_seed: int
    voices: list[str]
    media_devices: dict[str, int]


class Profile(Strict):
    id: str
    name: str
    created: dt.datetime
    last_used: dt.datetime | None = None
    # The browser this profile runs. Fixed at creation: browser-data is one
    # Firefox profile directory, so switching engines would downgrade it or carry
    # one identity's state into another. Old profile.json files have no "engine"
    # key and load as camoufox.
    engine: EngineName = "camoufox"
    # For firefox/torbrowser: which installed version to run, or None to follow
    # the newest installed (right for Tor Browser — security updates, and the
    # crowd is the current release). camoufox pins its version in the fingerprint.
    engine_version: str | None = None
    endpoint: Endpoint
    dns: DnsConfig = Field(default_factory=DnsConfig)
    last_exit: ExitInfo | None = None
    # Hardware GL via the host's render node. On by default: software-rendering
    # performance against a claimed discrete GPU is itself one of the residual
    # tells, so acceleration removes a tell rather than adding one.
    gpu_accel: bool = True
    # What a page is told about the graphics card. Firefox never names a card,
    # only the series it belongs to, so every mode but "raw" and "off" reports one
    # series — in the masked and the unmasked value alike — with that series' own
    # limits, extensions and shader precision (see fingerprint/webgl.py).
    #   host    the series this machine's real GPU belongs to, re-read each launch
    #   preset  a chosen series: `webgl_series`, else the one in the fingerprint
    #   custom  `webgl_vendor`/`webgl_renderer` verbatim, with the limits of the
    #           series those strings would belong to
    #   off     no WebGL at all — rare on Windows, so it stands out
    #   raw     spoof nothing. On Linux that is Mesa's wording and limits under a
    #           Windows user agent; it exists to measure the host and for testing.
    webgl: Literal["host", "preset", "custom", "off", "raw"] = "preset"
    webgl_series: str | None = None
    # preset: the card that was chosen, by its Windows driver name. What a page
    # is told is the card's series; the name is kept so the choice can be shown
    # again, and for `webgl_exact`.
    webgl_card: str | None = None
    # host/preset: let the debug extension name the exact card instead of its
    # series. Real Firefox does that only with a hidden setting changed.
    webgl_exact: bool = False
    webgl_vendor: str | None = None
    webgl_renderer: str | None = None
    # Light or dark, for the browser's own chrome and for what pages are told
    # (prefers-color-scheme). "host" follows the desktop the window appears on,
    # read at each launch — which is what stock Firefox does, and what it cannot
    # do by itself from inside a container.
    appearance: Literal["host", "light", "dark"] = "host"
    # Which Firefox this is, language-wise. "local": the build for the profile's
    # region, announcing that build's own language list and formatting dates the
    # local way. "english": an English Firefox used there — "en-US, en", US formats
    # unless the region is English-speaking. See windows11.browser_languages.
    language: Literal["local", "english"] = "local"
    # Replaces the user agent in navigator and in the request header. None is the
    # engine's own: stock Firefox of its version, on Windows.
    user_agent: str | None = None
    notes: str = ""
