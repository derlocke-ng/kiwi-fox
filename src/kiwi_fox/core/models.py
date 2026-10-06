"""Data model. Everything a profile is, and nothing that belongs in a secret store."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FormFactor = Literal["desktop", "laptop"]
GpuFamily = Literal["nvidia", "amd", "intel"]
GpuTier = Literal["integrated", "mid", "high"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Endpoint(Strict):
    """A SOCKS5 endpoint. Every provider module exposes exactly this shape."""

    host: str
    port: int
    username: str | None = None
    has_password: bool = False  # the password itself lives in libsecret
    module: str | None = None  # provider module name; None = plain SOCKS5
    lease: str | None = None  # module-specific lease (9proxy port, myst provider_id)
    # Exit country requested from the provider. Persisted separately from lease
    # because for some modules the two are distinct axes (a myst provider_id and a
    # country), so it is replayed on every relaunch to keep the exit — and the
    # frozen fingerprint built for it — coherent.
    country: str | None = None

    @property
    def label(self) -> str:
        who = f"{self.module}:" if self.module else ""
        return f"{who}{self.host}:{self.port}"


class ExitInfo(Strict):
    ip: str
    country: str | None = None
    city: str | None = None
    timezone: str | None = None
    asn: str | None = None
    seen: dt.datetime


class DnsConfig(Strict):
    # "resolver": dnscrypt-proxy in the gateway, upstream through the SOCKS5 exit.
    # "remote":   hand the hostname to the proxy (most native, no DNS adblock).
    mode: Literal["resolver", "remote"] = "resolver"
    upstream: str = "google"  # key into dns.UPSTREAMS
    blocklists: list[str] = Field(default_factory=lambda: ["oisd-big"])


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
    engine: str = "camoufox"
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


class ProviderRecord(Strict):
    """One verified exit, cached across profiles. Provider geo is self-reported; this is measured."""

    module: str
    lease: str  # provider_id / port / address
    ip: str
    subnet: str | None = None
    country: str | None = None
    city: str | None = None
    asn: str | None = None
    quality: float | None = None
    verified_at: dt.datetime


# ---------------------------------------------------------------- provider plugins
# A provider module turns some upstream (Tor, a VPN tunnel, a residential-proxy
# account, a Mysterium node) into plain SOCKS5 and exposes nothing else — the
# gateway, forwarder, firewall rule and DNS design stay single-shaped (see
# docs/decisions.md). kiwi-fox discovers modules under paths.modules_dir(); each
# ships a provider.py exposing PROVIDER (a Provider) and MANIFEST.

ProviderAuth = Literal["none", "isolation", "account"]
#   none       the exposed SOCKS5 takes no credentials
#   isolation  any user/pass is accepted and used only to separate circuits/sessions
#              per profile (Tor IsolateSOCKSAuth); kiwi-fox mints a per-profile token
#   account    fixed credentials the user holds with the provider (9proxy login);
#              supplied as the profile endpoint's own username/password


class Lease(Strict):
    """One selectable exit a provider can bring up: a Tor exit country, a gluetun
    server, a 9proxy residential port, a Mysterium provider. ``id`` is what the
    user passes as ``--lease`` and what is stored on the Endpoint; the rest is for
    display only."""

    id: str
    label: str | None = None
    country: str | None = None
    city: str | None = None
    detail: str | None = None


class ProviderManifest(Strict):
    """Static metadata a provider module declares about itself."""

    name: str  # the module id: tor, vpn, 9proxy, mysterium. Also Endpoint.module.
    title: str
    description: str = ""
    version: str = "0.0.0"
    # True when the module runs its own container(s) that become the SOCKS5
    # upstream; False for a module that only tags an already-remote SOCKS5.
    runs_container: bool = True
    # The podman image the module's container runs, built from its Containerfile.
    # None lets kiwi-fox derive the conventional name (kiwi-fox/<name>:latest).
    image: str | None = None
    # SOCKS5 port the provider container listens on, inside the providers network.
    socks_port: int = 1080
    auth: ProviderAuth = "none"
    # Does using this provider require an account / subscription / identity?
    needs_account: bool = False
    # Host binaries `kiwi-fox module doctor` checks for, beyond podman.
    requires: list[str] = Field(default_factory=list)
    # Free-form notes surfaced in `kiwi-fox module list`.
    notes: str = ""


class ProviderStatus(Strict):
    """A provider's live state, for `kiwi-fox module status` and doctor."""

    name: str
    installed: bool = True
    image_present: bool = False
    running: bool = False
    containers: list[str] = Field(default_factory=list)
    leases: list[str] = Field(default_factory=list)
    detail: str = ""


class ContainerSpec(Strict):
    """What an engine asks podman for. Golden-file tested; keep it declarative."""

    name: str
    image: str
    network: str  # "container:<gateway>", "pasta", or a bridge name
    ip: str | None = None  # static address on a bridge network (providers only)
    restart: str | None = None  # podman restart policy, e.g. "on-failure"
    env: dict[str, str] = Field(default_factory=dict)
    volumes: list[tuple[str, str, str]] = Field(default_factory=list)  # src, dst, opts
    args: list[str] = Field(default_factory=list)  # command line after the image
    devices: list[str] = Field(default_factory=list)
    tmpfs: list[str] = Field(default_factory=list)
    secrets: list[tuple[str, str]] = Field(default_factory=list)  # secret name, target path
    cap_drop: list[str] = Field(default_factory=lambda: ["all"])
    cap_add: list[str] = Field(default_factory=list)
    security_opt: list[str] = Field(default_factory=lambda: ["no-new-privileges"])
    userns: str | None = "keep-id"
    labels: dict[str, str] = Field(default_factory=dict)
