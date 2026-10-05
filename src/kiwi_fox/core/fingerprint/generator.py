"""Seeded, reproducible fingerprint generation.

Every value derives from one seed, so a profile's identity is stable across
launches and unrelated to its neighbours. Nothing here is random at runtime.
"""

from __future__ import annotations

import hashlib
import secrets
from random import Random

from ..models import (
    AudioBlock,
    BatteryBlock,
    Fingerprint,
    ScreenBlock,
    WebGLBlock,
    WindowBlock,
)
from . import fonts, webgl
from . import windows11 as w11


def new_seed() -> str:
    return secrets.token_hex(16)


def _rng(seed: str) -> Random:
    digest = hashlib.sha256(seed.encode()).digest()
    return Random(int.from_bytes(digest, "big"))


def generate(
    *,
    engine_version: str,
    build_id: str | None = None,
    country: str | None = None,
    form_factor: str | None = None,
    gpu_family: str | None = None,
    series: str | None = None,
    timezone: str | None = None,
    seed: str | None = None,
    extra_fonts: bool = False,
) -> Fingerprint:
    """`series` is a GPU series key or anything `webgl.find` understands.

    `extra_fonts` draws a random set of the optional font families on top of the
    Windows core set. Off by default: see the note where the fonts are chosen.
    """
    seed = seed or new_seed()
    rng = _rng(seed)

    # Screen and GPU series are solved *together*. Picking one first paints the
    # other into a corner: choosing the GPU fixed the form factor, which then left
    # no screen whose avail height could contain the real window. Constraints are
    # relaxed in a defined order instead, so a caller's explicit choice always wins
    # and coherence is only dropped last.
    # Only engines that cannot be told a window size constrain the screen.
    window_height = 0 if w11.engine_sizes_window(engine_version) else w11.host_window_height()
    pairs = [(s, g) for s in w11.SCREENS for g in webgl.SERIES if s.form in g.forms]
    if series:
        chosen = webgl.find(series)  # an explicit request is not negotiable
        pairs = [(s, g) for s, g in pairs if g is chosen]
    if form_factor:
        pairs = [(s, g) for s, g in pairs if s.form == form_factor] or pairs
    if gpu_family:
        pairs = [(s, g) for s, g in pairs if g.family == gpu_family] or pairs

    def narrow(candidates, predicate):
        kept = [p for p in candidates if predicate(*p)]
        return kept or candidates

    # innerHeight must never exceed availHeight; drop this last of all.
    if window_height:
        pairs = narrow(pairs, lambda s, g: s.height - w11.TASKBAR_CSS_PX >= window_height)
    # 1920x1080 at 100% wherever it is possible. Every other resolution on the
    # list has been flagged by fingerprint.com at least once on some machine; this
    # one never has. The rest stay available on purpose (`set --screen`, the
    # editor), not by the draw.
    pairs = narrow(pairs, lambda s, g: (s.width, s.height, s.dpr) == w11.COMMON_SCREEN)
    if not series and not gpu_family:
        # Unasked, a profile is this machine: the frame the GPU actually draws is
        # the one thing no setting changes, so the series it sits beside may as
        # well be the true one.
        host, _how = webgl.host_series()
        if host:
            pairs = narrow(pairs, lambda s, g: g is host)

    # The series first, weighted the way real Windows Firefox users are spread
    # across them, then a screen that goes with it.
    candidates = list(dict.fromkeys(g for _s, g in pairs))
    gp = rng.choices(candidates, weights=[webgl.share(g) for g in candidates])[0]
    sp = rng.choice([s for s, g in pairs if g is gp])
    form = sp.form
    avail_h = sp.height - w11.TASKBAR_CSS_PX
    screen = ScreenBlock(
        width=sp.width,
        height=sp.height,
        avail_width=sp.width,
        avail_height=avail_h,
        device_pixel_ratio=sp.dpr,
    )
    # Maximized: the common case, and it keeps screen >= avail >= outer >= inner true.
    window = WindowBlock(
        outer_width=sp.width,
        outer_height=avail_h,
        inner_width=sp.width,
        inner_height=avail_h - w11.CHROME_CSS_PX,
    )

    webgl_block = WebGLBlock(vendor=gp.vendor, renderer=gp.renderer, family=gp.family, tier=gp.tier)
    cores = rng.choice(gp.cores)

    region = (
        w11.REGIONS.get((country or w11.DEFAULT_REGION).upper()) or w11.REGIONS[w11.DEFAULT_REGION]
    )

    # The Windows core set and nothing else, unless asked. Optional families were
    # the per-profile lever once; in use (fingerprint.com, 2026-10) profiles
    # stripped to the core set drew fewer tampering and virtual-machine flags
    # than the same profiles with a random set of extras, and a font set shared
    # with every plain Windows 11 install links nothing to anything.
    families = fonts.all_core_families()
    if extra_fonts:
        for bundle in fonts.BUNDLES:
            # Each language feature is independently installed on a real machine.
            if rng.random() < 0.5:
                families.extend(bundle)
        leftovers = [
            f
            for f in fonts.all_optional_families()
            if f not in families and not any(f in b for b in fonts.BUNDLES)
        ]
        for f in leftovers:
            if rng.random() < 0.45:
                families.append(f)
        # These are the ones a fingerprinter actually probes for.
        for fam in fonts.all_third_party_families():
            if rng.random() < 0.5:
                families.append(fam)
    families = sorted(set(families))

    audio = AudioBlock(
        sample_rate=rng.choice(w11.SAMPLE_RATES),
        max_channel_count=2,
        output_latency=round(rng.uniform(0.008, 0.045), 6),
        seed=rng.getrandbits(32),
    )

    if form == "desktop":
        # A desktop has no battery: charging, full, infinite. Left unset in the
        # engine config so the real (identical) values are reported instead.
        battery = BatteryBlock(charging=True, level=1.0, charging_time=0.0, discharging_time=None)
    else:
        charging = rng.random() < 0.5
        battery = BatteryBlock(
            charging=charging,
            level=round(rng.uniform(0.25, 1.0), 2),
            charging_time=round(rng.uniform(300, 5400)) if charging else None,
            discharging_time=None if charging else round(rng.uniform(1800, 21600)),
        )

    # Always 0, because that is what a page will see: at the pinned tag no engine
    # patch reads navigator.maxTouchPoints (measured — configured 5, reported 0),
    # so a "touchscreen laptop" here would be a claim nothing backs up.
    touch = 0

    voices = w11.voices_for(region)

    # Always a microphone. The engine builds the device list by inserting cameras
    # at index 1, so a camera with no microphone before it indexes past the end of
    # an empty array and takes the whole tab down on enumerateDevices() — see
    # media-device-spoofing.patch upstream, reproduced on the test VM. And an
    # empty list is what a headless browser reports, so "neither" is out too.
    media = {"micros": 1, "webcams": 1 if form == "laptop" else rng.choice([0, 1]), "speakers": 1}

    return Fingerprint(
        seed=seed,
        engine_version=engine_version,
        build_id=build_id or w11.FROZEN_BUILD_ID,
        form_factor=form,  # type: ignore[arg-type]
        ua=w11.ua_for(engine_version),
        hardware_concurrency=cores,
        max_touch_points=touch,
        locale=region.locale,
        languages=list(region.languages),
        accept_language=w11.accept_language_for(region.languages),
        # The measured exit timezone beats the region default: a country can span
        # several zones, and an AU exit in Perth was being given Australia/Sydney,
        # two hours out from its own IP.
        timezone=timezone or region.timezone,
        screen=screen,
        window=window,
        webgl=webgl_block,
        audio=audio,
        battery=battery,
        fonts=families,
        font_files=fonts.files_for(families),
        canvas_seed=rng.getrandbits(32),
        font_spacing_seed=rng.getrandbits(32),
        voices=voices,
        media_devices=media,
    )
