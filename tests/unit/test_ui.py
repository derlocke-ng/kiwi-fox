"""Construct the GUI's widgets.

A stale reference to a deleted handler made the "+" button do nothing: the dialog
raised during construction, so it never appeared and only the log knew. These tests
build the real widgets, which catches that class of error in `make test`.
"""

from __future__ import annotations

import pytest

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

pytestmark = pytest.mark.skipif(not Gtk.init_check(), reason="no display; GTK cannot initialise")


@pytest.fixture(scope="module", autouse=True)
def _adw():
    Adw.init()


def _stored(profile):
    """Save `profile` with a fingerprint, the way the dialogs expect to find it."""
    from kiwi_fox.core import store
    from kiwi_fox.core.fingerprint import generate

    fp = generate(engine_version="152.0.4", seed="ui")
    store.save(profile)
    store.save_fingerprint(profile.id, fp)
    return fp


def test_new_profile_dialog_has_exactly_one_graphics_control():
    # It once built the WebGL dropdown twice — the first copy was dead, so choosing
    # there did nothing — next to a separate card list that ignored the mode.
    from kiwi_fox.ui.dialogs import WEBGL_MODES, NewProfileDialog

    dialog = NewProfileDialog(Adw.ApplicationWindow(), lambda p: None)
    assert isinstance(dialog.graphics.mode_row, Adw.ComboRow)
    for stale in ("webgl_row", "card_expander", "card_row", "gpu_row", "_card_value"):
        assert not hasattr(dialog, stale), stale
    assert [key for key, _label in WEBGL_MODES] == ["host", "preset", "custom", "off", "raw"]
    assert dialog.graphics.mode == "host"


def _chooser():
    from kiwi_fox.ui.dialogs import GraphicsChooser

    return GraphicsChooser(Adw.PreferencesGroup())


def test_each_mode_shows_only_what_it_needs():
    chooser = _chooser()
    expect = {
        # mode: (series list, custom fields)
        "host": (False, False),
        "preset": (True, False),
        "custom": (False, True),
        "off": (False, False),
        "raw": (False, False),
    }
    for mode, (series, custom) in expect.items():
        chooser.set_mode(mode)
        assert all(r.get_visible() == series for r in chooser.series_rows), mode
        assert chooser.vendor_row.get_visible() == custom, mode
        assert chooser.renderer_row.get_visible() == custom, mode
        assert chooser.summary.get_subtitle(), f"{mode}: nothing says what pages will see"


def test_rows_show_text_literally(monkeypatch):
    # Row subtitles are Pango markup by default. One "<" in a hint, or an "&" typed
    # into a custom field, and GTK drops the whole text: the row renders blank. Seen
    # on screen, invisible to every other test, because the property still holds
    # the string.
    from kiwi_fox.core.fingerprint import webgl
    from kiwi_fox.ui import dialogs

    host = webgl.BY_KEY["radeon-r9-200"]
    for how in ("measured", "family"):
        monkeypatch.setattr(webgl, "host_series", lambda how=how: (host, how))
        chooser = _chooser()
        assert not chooser.summary.get_use_markup()
        assert all(not row.get_use_markup() for row in chooser.series_rows)
        assert host.renderer in chooser.summary.get_subtitle()
    chooser.set_mode("custom")
    chooser.renderer_row.set_text("ANGLE (AMD & <friends>)")
    assert "ANGLE (AMD & <friends>)" in chooser.summary.get_subtitle()
    assert not dialogs._row("t", "a < b & c").get_use_markup()


def test_choosing_a_series_is_what_gets_saved():
    from kiwi_fox.core.fingerprint import webgl

    chooser = _chooser()
    chooser.set_mode("preset")
    assert len(chooser.series_rows) == len(webgl.SERIES)
    for series in webgl.SERIES:
        chooser._radios[series.key].set_active(True)
        assert chooser.value() == {
            "webgl": "preset",
            "webgl_series": series.key,
            "webgl_vendor": None,
            "webgl_renderer": None,
        }
        assert chooser.summary.get_subtitle() == series.renderer
        assert chooser.problem() is None
    # the choice only counts in the mode it belongs to
    chooser.set_mode("host")
    assert chooser.value()["webgl_series"] is None


def test_custom_has_fields_and_starts_from_a_valid_string():
    # "custom" used to have no inputs at all, so it could only ever fail at launch.
    from kiwi_fox.core.fingerprint import webgl

    chooser = _chooser()
    chooser.set_mode("custom")
    assert chooser.problem() is None, "the prefilled strings must already be usable"
    assert chooser.value()["webgl_renderer"] in {s.renderer for s in webgl.SERIES}
    chooser.renderer_row.set_text("")
    assert "renderer" in chooser.problem()
    assert "renderer" in chooser.summary.get_subtitle()
    chooser.renderer_row.set_text("llvmpipe (LLVM 20.1, 256 bits)")
    assert "Linux" in chooser.problem()
    card = "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11-32.0.15.6094)"
    chooser.vendor_row.set_text("Google Inc. (NVIDIA)")
    chooser.renderer_row.set_text(card)
    assert chooser.problem() is None
    assert chooser.value() == {
        "webgl": "custom",
        "webgl_series": None,
        "webgl_vendor": "Google Inc. (NVIDIA)",
        "webgl_renderer": card,
    }
    # allowed, but it says which string a real Firefox would send instead
    assert "GeForce GTX 980" in chooser.summary.get_subtitle()


def test_chooser_shows_an_existing_profiles_choice(profile):
    fp = _stored(profile)
    chooser = _chooser()
    for update in (
        {"webgl": "preset", "webgl_series": "intel-hd"},
        {"webgl": "custom", "webgl_vendor": "V", "webgl_renderer": "ANGLE (Intel, X)"},
        {"webgl": "off"},
        {"webgl": "host"},
    ):
        p = profile.model_copy(update=update)
        chooser.load(p, fp)
        got = chooser.value()
        assert got["webgl"] == p.webgl
        assert got["webgl_series"] == p.webgl_series
        assert (got["webgl_vendor"], got["webgl_renderer"]) == (p.webgl_vendor, p.webgl_renderer)


def test_graphics_dialog_saves_the_change(profile):
    from kiwi_fox.core import store
    from kiwi_fox.ui.dialogs import GraphicsDialog

    _stored(profile)
    saved = []
    dialog = GraphicsDialog(profile, saved.append)
    dialog.graphics.set_mode("preset")
    dialog.graphics._radios["geforce-gtx-980"].set_active(True)
    dialog._on_save()
    again = store.load(profile.id)
    assert (again.webgl, again.webgl_series) == ("preset", "geforce-gtx-980")
    assert saved and saved[0].id == profile.id
    # an unusable choice is refused and says why
    dialog = GraphicsDialog(again)
    dialog.graphics.set_mode("custom")
    dialog.graphics.vendor_row.set_text("")
    dialog._on_save()
    assert dialog.status_label.get_visible() and "vendor" in dialog.status_label.get_text()
    assert store.load(profile.id).webgl == "preset"


def test_profile_details_constructs_in_every_mode(profile):
    from kiwi_fox.ui.dialogs import ProfileDetails, describe_graphics

    fp = _stored(profile)
    for mode in ("host", "preset", "off", "raw"):
        p = profile.model_copy(update={"webgl": mode})
        details = ProfileDetails(p)
        assert details.graphics_row.get_subtitle() == describe_graphics(p, fp)
    assert "ANGLE (" in describe_graphics(profile.model_copy(update={"webgl": "host"}), fp)
    assert describe_graphics(profile.model_copy(update={"webgl": "off"}), fp) == "No WebGL"


def test_main_window_constructs():
    from kiwi_fox.ui.window import Window

    Window()
