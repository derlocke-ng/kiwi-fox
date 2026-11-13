"""Names for a profile's media devices, as Windows Firefox shows them after a
getUserMedia grant (WASAPI friendly names). The counts are the profile's own;
only the names and their groups are drawn here, seeded by the fingerprint, so a
profile keeps the same devices every launch.

The catalogue is Camoufox's (data/camoufox-media-devices.json, MPL-2.0); the
drawing follows its draw_media_devices(): one sound card whose microphone and
speakers share a group, display audio or a headset for more, built-in cameras.
Before a grant Firefox shows no names at all, as it does here.
"""

from __future__ import annotations

import itertools
import json
import random
from functools import cache
from pathlib import Path

DATA = Path(__file__).parent / "data" / "camoufox-media-devices.json"


@cache
def _catalogue() -> dict:
    return json.loads(DATA.read_text())["win"]


def _pick(rng: random.Random, items: list[dict]) -> dict:
    total = sum(i.get("w", 1) for i in items)
    r = rng.random() * total
    for item in items:
        r -= item.get("w", 1)
        if r < 0:
            return item
    return items[-1]


def device_names(seed: str, micros: int, webcams: int, speakers: int) -> dict[str, list[str]]:
    """The mediaDevices:*Labels and *Groups keys for these counts."""
    rng = random.Random(f"media-devices:{seed}")
    cat = _catalogue()
    group = (f"hw-{n}" for n in itertools.count(1))
    mics: list[tuple[str, str]] = []
    outs: list[tuple[str, str]] = []

    def add(item: dict) -> None:
        g = next(group)
        mics.extend((m, g) for m in item.get("mics") or [])
        outs.extend((o, g) for o in item.get("outs") or [])

    add(_pick(rng, cat["cards"]))
    for _ in range(8):  # more than a card gives: a headset (mic), display audio (speakers)
        if len(mics) >= micros and len(outs) >= speakers:
            break
        add(_pick(rng, cat["headsets"] if len(mics) < micros else cat["displays"]))
    builtin = [c for c in cat["cameras"] if not c.get("mic")] or cat["cameras"]
    cams: list[tuple[str, str]] = []
    for _ in range(webcams):
        left = [c for c in builtin if c["cam"] not in {n for n, _g in cams}] or builtin
        cams.append((_pick(rng, left)["cam"], next(group)))
    mics, outs = mics[:micros], outs[:speakers]
    return {
        "mediaDevices:microphoneLabels": [n for n, _g in mics],
        "mediaDevices:microphoneGroups": [g for _n, g in mics],
        "mediaDevices:webcamLabels": [n for n, _g in cams],
        "mediaDevices:webcamGroups": [g for _n, g in cams],
        "mediaDevices:speakerLabels": [n for n, _g in outs],
        "mediaDevices:speakerGroups": [g for _n, g in outs],
    }
