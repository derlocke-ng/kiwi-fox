"""The real window: opened at a size the claimed screen can hold, and remembered."""

import json

import pytest

from kiwi_fox.core import geometry, paths
from kiwi_fox.core.engines.camoufox import Camoufox
from kiwi_fox.core.fingerprint import edit, generate
from kiwi_fox.core.fingerprint import windows11 as w11


@pytest.fixture
def fp156():
    return generate(engine_version="156.0.1", country="NL", seed="g" * 32)


def _leave_window_at(profile, width, height, sizemode="normal"):
    data = paths.profile_dir(profile.id) / "browser-data"
    data.mkdir(parents=True, exist_ok=True)
    saved = {"screenX": "0", "screenY": "0", "width": str(width), "height": str(height)}
    (data / "xulstore.json").write_text(
        json.dumps({geometry.XULSTORE_KEY: {"main-window": {**saved, "sizemode": sizemode}}})
    )


def test_a_first_window_is_what_firefox_itself_would_open_on_that_screen(fp156, profile):
    # browser-init.js: 90% of the usable screen, at most 1280x1040.
    assert (fp156.screen.width, fp156.screen.avail_height) == (1920, 1032)
    assert geometry.opening_size(profile, fp156) == ((1280, 928), "default")
    big = edit.with_screen(fp156, "2560x1440")
    assert geometry.opening_size(profile, big) == ((1280, 1040), "default")


def test_whatever_it_opens_at_the_reported_window_fits_the_claimed_screen(fp156, profile):
    # A page reads the asked size plus GTK's shadow. Measured on 156.0.1: asked
    # 1280x928, outer 1332x980. The engine's own default (1280x1040) reported
    # 1092 on a screen with 1032 usable — a window taller than its screen.
    for form in ("desktop", "laptop"):
        for preset in edit.screen_choices(form):
            claimed = edit.with_screen(
                edit.with_form(fp156, form), f"{preset.width}x{preset.height}"
            )
            for left_at in (None, (1424, 733), (5000, 3000), (1280, 1040)):
                width, height = w11.window_size(claimed.screen, left_at)
                assert width + w11.WINDOW_SHADOW_PX <= claimed.screen.avail_width
                assert height + w11.WINDOW_SHADOW_PX <= claimed.screen.avail_height


def test_the_window_comes_back_the_way_it_was_left(fp156, profile):
    _leave_window_at(profile, 1424, 733)
    assert geometry.opening_size(profile, fp156) == ((1424, 733), "remembered")
    assert "as you left it" in geometry.describe(profile, fp156)
    # ... unless the claimed screen could not hold it
    _leave_window_at(profile, 1900, 1040)
    assert geometry.opening_size(profile, fp156) == ((1868, 980), "fitted")
    # a maximised window still has the size it had before
    _leave_window_at(profile, 1300, 800, sizemode="maximized")
    assert geometry.opening_size(profile, fp156)[0] == (1300, 800)


@pytest.mark.parametrize(
    "junk", ["", "{", "[]", '{"x": 1}', '{"%s": {"main-window": {"width": "a"}}}']
)
def test_an_unreadable_saved_size_is_just_no_saved_size(fp156, profile, junk):
    data = paths.profile_dir(profile.id) / "browser-data"
    data.mkdir(parents=True)
    (data / "xulstore.json").write_text(junk.replace("%s", geometry.XULSTORE_KEY))
    assert geometry.opening_size(profile, fp156) == ((1280, 928), "default")


def test_156_is_told_the_size_and_older_engines_are_not(fp156, fp, profile):
    # On 156 these two keys resize the real window (and the engine resets it to
    # 1280x1040 without them). Before, sending them is not known to be safe.
    _leave_window_at(profile, 1424, 733)
    cfg = Camoufox().config(fp156, profile, exit_ip=None)
    assert (cfg["window.outerWidth"], cfg["window.outerHeight"]) == (1424, 733)
    assert not {"window.innerWidth", "window.innerHeight"} & set(cfg), "those pin the content"
    old = Camoufox().config(fp, profile, exit_ip=None)
    assert not [key for key in old if key.startswith("window.outer")]
    assert "fixed by this engine" in geometry.describe(profile, fp)


def _saved(profile):
    path = paths.profile_dir(profile.id) / "browser-data" / "xulstore.json"
    return json.loads(path.read_text())[geometry.XULSTORE_KEY]["main-window"]


def test_before_a_launch_the_saved_state_is_one_the_engine_cannot_trip_over(fp156, profile):
    # Measured on 156.0.1, both ending in a window about 500x200: no saved size
    # on a small claimed screen (Firefox's first-run rule maximises, the engine
    # un-maximises), and a window the user left maximised.
    small = edit.with_screen(edit.with_form(fp156, "laptop"), "1366x768")
    geometry.prepare(profile, small)
    assert _saved(profile) == {"width": "1229", "height": "648", "sizemode": "normal"}

    _leave_window_at(profile, 1300, 800, sizemode="maximized")
    geometry.prepare(profile, fp156)
    saved = _saved(profile)
    assert (saved["width"], saved["height"], saved["sizemode"]) == ("1300", "800", "normal")
    # and what the engine is then told is that same size
    cfg = Camoufox().config(fp156, profile, exit_ip=None)
    assert (cfg["window.outerWidth"], cfg["window.outerHeight"]) == (1300, 800)


def test_preparing_keeps_everything_else_firefox_saved(fp156, profile):
    data = paths.profile_dir(profile.id) / "browser-data"
    data.mkdir(parents=True)
    other = {"chrome://browser/content/places/places.xhtml": {"placesContentTree": {"x": "1"}}}
    mine = {geometry.XULSTORE_KEY: {"sidebar-box": {"style": "width: 300px"}}}
    (data / "xulstore.json").write_text(json.dumps({**other, **mine}))
    geometry.prepare(profile, fp156)
    after = json.loads((data / "xulstore.json").read_text())
    assert after["chrome://browser/content/places/places.xhtml"] == other[next(iter(other))]
    assert after[geometry.XULSTORE_KEY]["sidebar-box"] == {"style": "width: 300px"}
    assert after[geometry.XULSTORE_KEY]["main-window"]["sizemode"] == "normal"


def test_older_engines_are_left_alone(fp, profile):
    geometry.prepare(profile, fp)
    assert not (paths.profile_dir(profile.id) / "browser-data" / "xulstore.json").exists()


def test_a_launch_no_longer_overwrites_the_saved_size(fp156, profile):
    from kiwi_fox.core import launch

    assert not hasattr(launch, "seed_xulstore"), "it wrote the claimed screen over the saved size"
    assert "KF_WINDOW_SIZE" not in Camoufox().env(fp156, profile, None)
