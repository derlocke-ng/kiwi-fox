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


def _with_host_card(monkeypatch, name="NVIDIA GeForce RTX 4060 Laptop GPU"):
    from kiwi_fox.core.fingerprint import webgl

    monkeypatch.setattr(webgl, "host_card", lambda: name)
    monkeypatch.setattr(webgl, "host_series", lambda: (webgl.BY_NAME[name].series, "measured"))


def test_each_choice_shows_only_what_it_needs(monkeypatch):
    _with_host_card(monkeypatch)
    chooser = _chooser()
    expect = {
        # choice: (card list, exact switch, custom fields)
        "host": (False, True, False),
        "preset": (True, True, False),
        "custom": (False, False, True),
        "off": (False, False, False),
        "raw": (False, False, False),
    }
    for mode, (cards, exact, custom) in expect.items():
        chooser.set_mode(mode)
        assert all(g.get_visible() == cards for g in chooser.card_groups), mode
        assert chooser.exact_row.get_visible() == exact, mode
        assert chooser.vendor_row.get_visible() == custom, mode
        assert chooser.renderer_row.get_visible() == custom, mode
        assert chooser.summary.get_subtitle(), f"{mode}: nothing says what websites will see"


def test_my_card_is_named_and_the_group_it_reads_as_is_explained(monkeypatch):
    # "Why does it say GTX 980 and not my 4060?" has to be answered on screen.
    _with_host_card(monkeypatch)
    chooser = _chooser()
    text = chooser.summary.get_subtitle()
    assert "GeForce GTX 980" in text  # what websites see
    assert "RTX 4060 Laptop GPU" in text  # the card it stands for
    assert "never shows the exact model" in text
    assert chooser.value() == {
        "webgl": "host",
        "webgl_card": None,
        "webgl_series": None,
        "webgl_exact": False,
        "webgl_vendor": None,
        "webgl_renderer": None,
    }
    chooser.exact_row.set_active(True)
    assert chooser.value()["webgl_exact"] is True
    assert "RTX 4060 Laptop GPU Direct3D11" in chooser.summary.get_subtitle()


def test_without_a_measured_card_nothing_exact_is_offered():
    chooser = _chooser()  # the hermetic test host has no GPU measured
    assert not chooser.exact_row.get_visible()
    assert "not measured yet" in chooser.summary.get_subtitle()


def test_rows_show_text_literally(monkeypatch):
    # Row subtitles are Pango markup by default. One "<" in a hint, or an "&" typed
    # into a custom field, and GTK drops the whole text: the row renders blank. Seen
    # on screen, invisible to every other test, because the property still holds
    # the string.
    from kiwi_fox.ui import dialogs

    _with_host_card(monkeypatch)
    chooser = _chooser()
    assert not chooser.summary.get_use_markup()
    chooser.set_mode("custom")
    chooser.renderer_row.set_text("ANGLE (AMD & <friends>)")
    assert "ANGLE (AMD & <friends>)" in chooser.summary.get_subtitle()
    assert not dialogs._row("t", "a < b & c").get_use_markup()


def test_choosing_a_card_is_what_gets_saved():
    from kiwi_fox.core.fingerprint import webgl

    chooser = _chooser()
    chooser.set_mode("preset")
    assert len(chooser._radios) == len(webgl.CARDS)
    assert sum(len(list(webgl.CARDS)) for _ in [0]) > 40, "a proper list, not a handful"
    for card in (
        webgl.CARDS[5],
        webgl.BY_NAME["AMD Radeon RX 6600"],
        webgl.BY_NAME["Intel(R) UHD Graphics 620"],
    ):
        chooser.set_card(card.name)
        got = chooser.value()
        assert (got["webgl"], got["webgl_card"], got["webgl_series"]) == (
            "preset",
            card.name,
            card.series.key,
        )
        assert card.series.renderer in chooser.summary.get_subtitle()
        assert chooser.problem() is None
        # the group the chosen card is under shows it without being opened
        mine = next(g for g in chooser.card_groups if g.family == card.family)
        assert mine.get_subtitle() == card.short
    # the choice only counts for the option it belongs to
    chooser.set_mode("host")
    assert chooser.value()["webgl_card"] is None and chooser.value()["webgl_series"] is None


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
    got = chooser.value()
    assert (got["webgl"], got["webgl_vendor"], got["webgl_renderer"]) == (
        "custom",
        "Google Inc. (NVIDIA)",
        card,
    )
    assert got["webgl_card"] is None and got["webgl_exact"] is False
    # allowed, but it says which string a real Firefox would send instead
    assert "GeForce GTX 980" in chooser.summary.get_subtitle()


def test_chooser_shows_an_existing_profiles_choice(profile):
    fp = _stored(profile)
    chooser = _chooser()
    for update in (
        {
            "webgl": "preset",
            "webgl_card": "AMD Radeon RX 6600",
            "webgl_series": "radeon-r9-200",
            "webgl_exact": True,
        },
        {"webgl": "custom", "webgl_vendor": "V", "webgl_renderer": "ANGLE (Intel, X)"},
        {"webgl": "off"},
        {"webgl": "host"},
    ):
        p = profile.model_copy(update=update)
        chooser.load(p, fp)
        got = chooser.value()
        for field in ("webgl", "webgl_card", "webgl_series", "webgl_vendor", "webgl_renderer"):
            assert got[field] == getattr(p, field), (update, field)
    # a profile from before cards existed: only its group is known
    old = profile.model_copy(update={"webgl": "preset", "webgl_series": "intel-hd"})
    chooser.load(old, fp)
    assert chooser.value()["webgl_series"] == "intel-hd", "any card of that group reads the same"


def _editor(profile):
    from kiwi_fox.ui.dialogs import ProfileEditor

    saved = []
    return ProfileEditor(profile, saved.append), saved


def test_editor_shows_the_profile_as_it_is(profile):
    from kiwi_fox.core.fingerprint import edit

    fp = _stored(profile)
    editor, _saved = _editor(profile)
    assert editor.name_row.get_text() == profile.name
    assert editor.timezone_row.get_text() == fp.timezone
    assert editor.ua_row.get_text() == fp.ua
    assert not editor.ua_note.get_visible(), "the engine's own user agent needs no warning"
    assert editor._cores[editor.cores_row.get_selected()] == fp.hardware_concurrency
    shown = editor._screens[editor.screen_row.get_selected()]
    assert (shown.width, shown.height) == (fp.screen.width, fp.screen.height)
    on = {name for name, row in editor._font_rows.items() if row.get_active()}
    assert on == set(fp.fonts) & set(edit.optional_fonts())
    assert editor.graphics.mode == profile.webgl


def test_saving_without_touching_anything_changes_nothing(profile):
    from kiwi_fox.core import store

    fp = _stored(profile)
    editor, saved = _editor(profile)
    editor._on_save()
    assert saved, editor.status_label.get_text()
    assert store.load_fingerprint(profile.id) == fp
    again = store.load(profile.id)
    assert (again.name, again.user_agent, again.webgl) == (profile.name, None, profile.webgl)


def test_editor_saves_every_kind_of_change(profile):
    from kiwi_fox.core import store
    from kiwi_fox.core.fingerprint import edit
    from kiwi_fox.core.fingerprint import windows11 as w11

    fp = _stored(profile)
    editor, saved = _editor(profile)
    other_form = "laptop" if fp.form_factor == "desktop" else "desktop"
    editor.name_row.set_text("renamed")
    editor.form_row.set_selected(["desktop", "laptop"].index(other_form))
    editor.screen_row.set_selected(len(editor._screens) - 1)
    wanted_screen = editor._screens[-1]
    cores = next(c for c in editor._cores if c != fp.hardware_concurrency)
    editor.cores_row.set_selected(editor._cores.index(cores))
    editor.country_row.set_selected(editor._countries.index("SE"))
    editor.appearance_row.set_selected(2)  # dark
    editor.camera_row.set_active(False)
    flip = edit.optional_fonts()[0]
    editor._font_rows[flip].set_active(flip not in fp.fonts)
    editor.graphics.set_mode("preset")
    editor.graphics.set_card("Intel(R) UHD Graphics 620")
    editor.language_row.set_selected(1)  # English Firefox
    editor._on_save()
    assert saved, editor.status_label.get_text()

    new, p = store.load_fingerprint(profile.id), store.load(profile.id)
    assert p.name == "renamed" and p.appearance == "dark"
    assert (p.webgl, p.webgl_card, p.webgl_series) == (
        "preset",
        "Intel(R) UHD Graphics 620",
        "intel-hd-400",
    )
    assert p.language == "english"
    assert new.form_factor == other_form
    assert (new.screen.width, new.screen.height) == (wanted_screen.width, wanted_screen.height)
    assert new.hardware_concurrency == cores
    assert new.locale == "sv-SE" and new.timezone == "Europe/Stockholm"
    assert new.voices == w11.voices_for(w11.REGIONS["SE"])
    assert (flip in new.fonts) != (flip in fp.fonts)
    assert new.media_devices["micros"] == 1, "never a machine without a microphone"
    # what was not touched is exactly as it was
    assert (new.seed, new.canvas_seed, new.audio.seed, new.ua) == (
        fp.seed,
        fp.canvas_seed,
        fp.audio.seed,
        fp.ua,
    )


def test_editor_refuses_what_would_not_be_coherent(profile):
    from kiwi_fox.core import store

    fp = _stored(profile)
    editor, saved = _editor(profile)
    editor.timezone_row.set_text("Mars/Olympus")
    editor._on_save()
    assert not saved and "timezone" in editor.status_label.get_text()
    editor.timezone_row.set_text(fp.timezone)
    editor.name_row.set_text("")
    editor._on_save()
    assert not saved and "name" in editor.status_label.get_text()
    editor.name_row.set_text(profile.name)
    editor.graphics.set_mode("custom")
    editor.graphics.renderer_row.set_text("")
    editor._on_save()
    assert not saved and "Graphics" in editor.status_label.get_text()
    assert store.load_fingerprint(profile.id) == fp, "a refused save must not write anything"


def test_a_custom_user_agent_is_saved_and_explained(profile):
    from kiwi_fox.core import store

    fp = _stored(profile)
    editor, saved = _editor(profile)
    editor.ua_row.set_text("Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0")
    note = editor.ua_note.get_subtitle()
    assert editor.ua_note.get_visible() and "Windows" in note and "Firefox" in note
    editor._on_save()
    assert saved and store.load(profile.id).user_agent.startswith("Mozilla/5.0 (X11")
    # and back to the engine's own, which is stored as "no override"
    editor, saved = _editor(store.load(profile.id))
    assert editor.ua_note.get_visible()
    editor.ua_row.set_text(fp.ua)
    editor._on_save()
    assert saved and store.load(profile.id).user_agent is None


def test_the_screens_offered_follow_the_kind_of_machine(profile):
    from kiwi_fox.core.fingerprint import edit

    _stored(profile)
    editor, _saved = _editor(profile)
    for index, form in enumerate(("desktop", "laptop")):
        editor.form_row.set_selected(index)
        assert editor._screens == edit.screen_choices(form)
        assert editor.screen_row.get_model().get_n_items() == len(edit.screen_choices(form))


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
