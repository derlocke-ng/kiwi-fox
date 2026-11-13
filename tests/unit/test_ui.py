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


# ------------------------------------------------------------- engines and exits
def _exit(name, **endpoint):
    """A proxy in kiwi-proxy; a tor one passes auth through, as kiwi-proxy makes it."""
    from kiwi_proxy import exits

    from kiwi_fox.core.models import Endpoint

    ep = Endpoint(**({"host": "203.0.113.4", "port": 1080} | endpoint))
    return exits.create(name, ep, socks_auth="passthrough" if ep.module == "tor" else None)


def _plain(name, engine, **endpoint):
    """A non-camoufox profile on a proxy of its own, as the CLI shortcut makes one."""
    from kiwi_fox.core import store

    return store.create(name, _exit(f"{name}-exit", **endpoint).id, None, engine=engine)


@pytest.mark.parametrize("engine", ["firefox", "torbrowser"])
def test_details_and_editor_open_for_a_profile_without_a_fingerprint(engine):
    # Both dialogs loaded a fingerprint unconditionally, so a Firefox or Tor
    # Browser profile raised "has no fingerprint" and never opened.
    from kiwi_fox.ui.dialogs import ProfileDetails, ProfileEditor

    p = _plain(f"p-{engine}", engine, host="10.89.231.5", port=9050, module="tor", country="de")
    ProfileDetails(p)
    editor = ProfileEditor(p)
    assert editor._fp is None
    assert not hasattr(editor, "graphics"), "no Windows identity to edit"


def test_saving_a_firefox_profile_keeps_it_fingerprint_free_and_moves_its_proxy():
    from kiwi_fox.core import store
    from kiwi_fox.ui.dialogs import ProfileEditor

    other = _exit("kiwi-master-tor", host="10.8.0.1", port=9050)
    p = _plain("ff", "firefox")
    editor = ProfileEditor(p)
    assert editor.exits.selected_id == p.exit, "opens on the profile's own proxy"
    editor.name_row.set_text("ff-renamed")
    editor.exits.select(other.id)
    editor._on_save()
    saved = store.find_by_name("ff-renamed")
    assert saved is not None and saved.exit == other.id
    assert store.fingerprint_of(saved) is None
    # And off every proxy, which the editor offers to all but Tor Browser.
    editor = ProfileEditor(saved)
    editor.exits.select(None)
    editor._on_save()
    assert store.find_by_name("ff-renamed").exit is None


def test_a_row_names_the_proxy_and_its_detail_says_the_module_not_the_bridge():
    from kiwi_fox.core import store
    from kiwi_fox.ui.dialogs import exit_choice_label, exit_label

    p = _plain("t", "torbrowser", host="10.89.231.5", port=9050, module="tor", country="de")
    assert exit_label(p) == "t-exit"
    assert exit_choice_label(store.exit_of(p)).startswith("t-exit · tor · DE")
    assert exit_label(_plain("f", "firefox")) == "f-exit"
    assert store.describe_exit(store.exit_of(store.find_by_name("f"))).startswith(
        "f-exit · 203.0.113.4:1080"
    )
    bare = store.create("bare", None, None, engine="firefox")
    assert exit_label(bare) == "no proxy"


def test_new_profile_shows_only_what_the_engine_uses():
    from kiwi_fox.ui.dialogs import NewProfileDialog

    dialog = NewProfileDialog(Adw.ApplicationWindow(), lambda p: None)
    expect = {
        # engine: (Windows identity + graphics, may run with no proxy)
        "camoufox": (True, True),
        "firefox": (False, True),
        "torbrowser": (False, False),
    }
    for engine, (identity, no_proxy) in expect.items():
        dialog.select_engine(engine)
        assert dialog.engine == engine
        assert dialog.identity.get_visible() == identity, engine
        assert dialog.graphics_group.get_visible() == identity, engine
        assert dialog.exits.allows_none == no_proxy, engine
    assert not hasattr(dialog, "network"), "DNS is the proxy's, in kiwi-proxy's editor"


def test_the_picker_lists_kiwi_proxys_exits_and_prefers_one_over_no_proxy():
    from kiwi_fox.ui import dialogs

    a = _exit("a")
    b = _exit("b")
    dialog = dialogs.NewProfileDialog(Adw.ApplicationWindow(), lambda p: None)
    assert [e.id for e in dialog.exits._exits] == [a.id, b.id]
    assert dialog.exits.selected_id == a.id, "a proxy is the point; no-proxy is a choice"
    dialog.exits.select(None)
    assert dialog.exits.selected is None
    dialog.exits.select(b.id)
    assert dialog.exits.selected_id == b.id
    assert "used by" not in dialog.exits.row.get_subtitle()


def test_tor_browser_is_held_to_exits_on_the_tor_module():
    from kiwi_fox.ui import dialogs

    plain = _exit("plain")
    tor = _exit("tor", host="10.89.231.5", port=9050, module="tor", country="de")
    dialog = dialogs.NewProfileDialog(Adw.ApplicationWindow(), lambda p: None)
    dialog.exits.select(plain.id)
    dialog.select_engine("torbrowser")
    assert [e.id for e in dialog.exits._exits] == [tor.id]
    assert dialog.exits.selected_id == tor.id
    assert not dialog.exits.allows_none
    assert dialog.create_button.get_sensitive()
    dialog.select_engine("firefox")
    assert [e.id for e in dialog.exits._exits] == [plain.id, tor.id]


def test_tor_browser_without_a_tor_exit_says_how_to_get_one():
    from kiwi_fox.ui import dialogs

    _exit("plain")
    dialog = dialogs.NewProfileDialog(Adw.ApplicationWindow(), lambda p: None)
    dialog.select_engine("torbrowser")
    assert not dialog.create_button.get_sensitive()
    assert dialog.exits.note.get_visible()
    assert "kiwi install kiwi-plugin-tor" in dialog.exits.note.get_subtitle()


def test_the_app_grid_switch_round_trips():
    from kiwi_fox.core import desktop, store
    from kiwi_fox.ui.dialogs import NewProfileDialog, ProfileDetails, ProfileEditor

    dialog = NewProfileDialog(Adw.ApplicationWindow(), lambda p: None)
    assert not dialog.entry_row.get_active(), "opt-in"
    p = _plain("grid", "firefox")
    editor = ProfileEditor(p)
    assert not editor.entry_row.get_active()
    editor.entry_row.set_active(True)
    editor._on_save()
    saved = store.find_by_name("grid")
    assert saved.desktop_entry and desktop.entry_path(saved.id).exists()
    ProfileDetails(saved)
    editor = ProfileEditor(saved)
    editor.entry_row.set_active(False)
    editor._on_save()
    assert not desktop.entry_path(saved.id).exists()


def test_the_picker_makes_no_proxies_but_opens_kiwi_proxy():
    from kiwi_fox.ui import dialogs

    dialog = dialogs.NewProfileDialog(Adw.ApplicationWindow(), lambda p: None)
    assert not hasattr(dialog.exits, "add_row") and not hasattr(dialog.exits, "edit_button")
    assert dialog.exits.proxy_row.get_title() == "Proxies are defined in Kiwi Proxy"


def test_tags_round_trip_through_the_dialogs():
    from kiwi_fox.core import store
    from kiwi_fox.ui.dialogs import ProfileDetails, ProfileEditor

    p = _plain("tagged", "firefox")
    editor = ProfileEditor(p)
    assert editor.tags_row.get_text() == ""
    editor.tags_row.set_text("shop, EU, shop")
    editor._on_save()
    saved = store.find_by_name("tagged")
    assert saved.tags == ["shop", "EU"]
    ProfileDetails(saved)
    assert ProfileEditor(saved).tags_row.get_text() == "shop, EU"


def test_a_profile_with_a_lost_proxy_opens_and_says_so():
    from kiwi_proxy import exits

    from kiwi_fox.core import store
    from kiwi_fox.ui.dialogs import ProfileDetails, ProfileEditor

    p = _plain("lost", "firefox")
    exits.delete(p.exit)  # `kiwi-proxy rm lost-exit`
    ProfileDetails(store.load(p.id))
    editor = ProfileEditor(store.load(p.id))
    assert "gone from kiwi-proxy" in editor.status_label.get_text()


def _engines(monkeypatch, tmp_path):
    """Firefox 158.0 and 159.0.1 and Camoufox 152.0.4 installed; the publishers
    list a few more; no network."""
    from kiwi_fox.core import engine_versions as ev
    from kiwi_fox.core import paths

    for name, binary in (
        ("firefox-158.0", "firefox"),
        ("firefox-159.0.1", "firefox"),
        ("camoufox-152.0.4", "camoufox"),
    ):
        d = paths.engines_dir() / name
        d.mkdir(parents=True, exist_ok=True)
        (d / binary).write_text("x")
    listed = {
        "camoufox": ["157.0.1", "156.0.1", "152.0.4", "150.0.2", "148.0.1", "146.0"],
        "firefox": ["160.0", "159.0.1", "158.0"],
        "torbrowser": ["15.0.2"],
    }
    monkeypatch.setattr(
        ev, "_fetch_releases", lambda engine: [ev.Release(v) for v in listed[engine]]
    )


def test_the_engines_dialog_lists_versions_and_older_ones_behind_an_expander(monkeypatch, tmp_path):
    from kiwi_fox.ui.engines import EnginesDialog

    _engines(monkeypatch, tmp_path)
    dialog = EnginesDialog()
    _pump_until(lambda: dialog._rows)
    titles = [r.get_title() for r in dialog._rows]
    assert "157.0.1" in titles and "152.0.4" in titles and "160.0" in titles  # newest + installed
    expanders = [r for r in dialog._rows if isinstance(r, Adw.ExpanderRow)]
    assert expanders and "156.0.1" in expanders[0].get_subtitle()


def test_a_profile_is_pinned_and_follows_again(monkeypatch, tmp_path):
    from kiwi_fox.core import engine_versions as ev
    from kiwi_fox.core import store
    from kiwi_fox.ui.engines import VersionDialog

    _engines(monkeypatch, tmp_path)
    p = store.create("ff", _exit("ff-exit").id, None, engine="firefox")
    assert ev.version_of(p) == "159.0.1"  # follows the newest installed
    got = []
    dialog = VersionDialog(p, got.append)
    checks = list(dialog._iter_checks())
    assert [c.choice for c in checks if c.get_active()] == [None]
    next(c for c in checks if c.choice == "158.0").set_active(True)
    dialog._on_use()
    _pump_until(lambda: got)
    assert store.load(p.id).engine_version == "158.0"


def test_the_engines_page_says_who_uses_what(monkeypatch, tmp_path):
    from kiwi_fox.core import store
    from kiwi_fox.ui.engines import EnginesPage

    _engines(monkeypatch, tmp_path)
    store.create("ff", _exit("ff-exit").id, None, engine="firefox", engine_version="158.0")
    page = EnginesPage(lambda: None)
    _pump_until(lambda: page._built)
    subtitles = [row.get_subtitle() for _g, row in page._built if isinstance(row, Adw.ActionRow)]
    assert any("158.0 (1 profile, 1 pinned)" in (s or "") for s in subtitles)
    assert any((s or "").startswith("160.0 · not installed") for s in subtitles)


def test_the_window_opens_large_and_remembers_its_size():
    import json

    from kiwi_fox.core import paths
    from kiwi_fox.ui.window import DEFAULT_SIZE, Window

    win = Window()
    assert win.get_default_size() == DEFAULT_SIZE  # room for the profile editor (660×780)
    win.set_default_size(900, 700)
    win._on_close_request()
    saved = json.loads((paths.config_dir() / "window.json").read_text())
    assert (saved["width"], saved["height"], saved["maximized"]) == (900, 700, False)
    assert Window().get_default_size() == (900, 700)
    (paths.config_dir() / "window.json").write_text('{"width": 10, "height": 10}')
    assert Window().get_default_size() == (640, 480)  # never unusably small


# -------------------------------------------------------------- snapshots
def _pump_until(until, timeout=8.0):
    import time

    from gi.repository import GLib

    ctx = GLib.MainContext.default()
    deadline = time.monotonic() + timeout
    while not until() and time.monotonic() < deadline:
        while ctx.pending():
            ctx.iteration(False)
        time.sleep(0.01)
    assert until(), "the window never got there"


@pytest.fixture
def snapshot_device(monkeypatch, tmp_path):
    """Fast gpg, no podman, and a way to be another device."""
    import contextlib
    import shutil
    import subprocess
    import tempfile

    from kiwi_fox.core import snapshots as fox

    if not fox.available() or fox.snap.missing_tools():
        pytest.skip("profile snapshots need kiwi-proxy 0.8, gpg and zstd")
    from kiwi_proxy import podman
    from kiwi_proxy.snapshots import crypt
    from kiwi_proxy.snapshots.folder import Folder

    from kiwi_fox.core import launch

    home = tempfile.mkdtemp(prefix="kf-ui-gpg-")
    monkeypatch.setattr(crypt, "S2K_COUNT", 1024)
    monkeypatch.setattr(crypt, "_gpg_home", lambda: contextlib.nullcontext(home))
    running: set[str] = set()
    monkeypatch.setattr(launch, "running", lambda p: p.id in running)
    monkeypatch.setattr(podman, "available", lambda: False)

    def device(name):
        for var in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR"):
            monkeypatch.setenv(var, str(tmp_path / name / var.lower()))
        fox.snap._session.clear()
        Folder.forget_unlocked()

    device.running = running  # type: ignore[attr-defined]
    yield device
    fox.snap._session.clear()
    Folder.forget_unlocked()
    subprocess.run(["gpgconf", "--homedir", home, "--kill", "all"], capture_output=True)
    shutil.rmtree(home, ignore_errors=True)


def _snap_profile(name="work"):
    from kiwi_proxy import exits
    from kiwi_proxy.models import Endpoint

    from kiwi_fox.core import store
    from kiwi_fox.core.fingerprint import generate

    ex = exits.find_by_name("mullvad") or exits.create(
        "mullvad", Endpoint(host="10.64.0.1", port=1080)
    )
    fp = generate(engine_version="152.0.4", country="DE", seed="b" * 32)
    return store.create(name, ex.id, fp), ex


def test_the_window_offers_profiles_only_in_the_folder(snapshot_device, tmp_path):
    from kiwi_proxy import exits
    from kiwi_proxy.models import Endpoint

    from kiwi_fox.core import snapshots as fox
    from kiwi_fox.ui.window import Window

    snapshot_device("lime")
    fox.snap.setup(tmp_path / "shared", "correct horse battery staple", device_name="lime")
    p, ex = _snap_profile()
    fox.take(p)

    snapshot_device("titan")
    fox.snap.setup(tmp_path / "shared", "correct horse battery staple", device_name="titan")
    win = Window()
    _pump_until(lambda: win.away_group.get_visible())
    assert win.stack.get_visible_child_name() == "list"
    row = win._away_rows[0]
    assert row.get_title() == "work" and "from lime" in row.get_subtitle()

    # its exit is not here: the window says to restore it in Kiwi Proxy, and nothing changes
    alerts = []
    win._alert = lambda heading, body: alerts.append(heading)
    win._on_restore_away(None, p.id, "work", fox.snap.history("profile", p.id)[0])
    assert alerts == ["Restore mullvad in Kiwi Proxy first"]

    exits.create("mullvad", Endpoint(host="10.64.0.1", port=1080), exit_id=ex.id)
    win._offer_engine = lambda profile, missing: None
    win._on_restore_away(None, p.id, "work", fox.snap.history("profile", p.id)[0])
    _pump_until(lambda: p.id in win._rows and not win.away_group.get_visible())
    _pump_until(lambda: "snapshot" in win._rows[p.id].get_subtitle())


def test_a_browser_that_ended_gets_its_snapshot(snapshot_device, tmp_path):
    from kiwi_fox.core import snapshots as fox
    from kiwi_fox.ui.window import Window

    snapshot_device("lime")
    fox.snap.setup(tmp_path / "shared", "correct horse battery staple", device_name="lime")
    p, _ex = _snap_profile()
    win = Window()
    _pump_until(lambda: len(fox.snap.history("profile", p.id)) == 1)  # the catch-up
    snapshot_device.running.add(p.id)
    fox.started(p)
    win._tick()
    snapshot_device.running.discard(p.id)  # the user closed the browser
    win._tick()
    _pump_until(lambda: len(fox.snap.history("profile", p.id)) == 2)


def test_everything_now_from_the_window(snapshot_device, tmp_path):
    from kiwi_fox.core import snapshots as fox
    from kiwi_fox.ui.window import Window

    snapshot_device("lime")
    fox.snap.setup(tmp_path / "shared", "correct horse battery staple", device_name="lime")
    a, _ = _snap_profile("a")
    b, _ = _snap_profile("b")
    snapshot_device.running.add(b.id)
    win = Window()
    assert "1 profile" in win._take_all() and "1 running" in win._take_all()
    assert len(fox.snap.history("profile", a.id)) >= 1
    assert fox.snap.history("profile", b.id) == []


def test_new_profiles_start_from_the_general_preferences():
    from kiwi_fox.core import settings
    from kiwi_fox.ui.dialogs import NewProfileDialog

    a = _exit("first-exit")
    b = _exit("second-exit")
    dialog = NewProfileDialog(Adw.ApplicationWindow(), lambda p: None)
    assert dialog.engine == "camoufox" and dialog.exits.selected_id in (a.id, b.id)
    settings.save(settings.Settings(new_engine="firefox", new_exit=b.id))
    dialog = NewProfileDialog(Adw.ApplicationWindow(), lambda p: None)
    assert dialog.engine == "firefox" and dialog.exits.selected_id == b.id
    settings.save(settings.Settings(new_engine="firefox", new_exit="none"))
    dialog = NewProfileDialog(Adw.ApplicationWindow(), lambda p: None)
    assert dialog.exits.selected_id is None


def test_the_general_page_has_its_three_groups(monkeypatch):
    from kiwi_fox.ui.window import Window

    monkeypatch.setattr(Window, "_check_environment", lambda self, announce=False: None)
    win = Window()
    page = win._general_page()
    titles = []
    child = page.get_first_child()
    stack = [child]
    while stack:
        w = stack.pop()
        if w is None:
            continue
        if isinstance(w, Adw.PreferencesGroup):
            titles.append(w.get_title())
        stack += [w.get_first_child(), w.get_next_sibling()]
    assert set(titles) == {"Browser and container", "New profiles", "Window"}
    win.destroy()


def test_installing_from_the_engines_page_shows_it_installed_and_settles(monkeypatch, tmp_path):
    from gi.repository import Gtk

    from kiwi_fox.core import engine_versions as ev
    from kiwi_fox.core import paths
    from kiwi_fox.ui.engines import EnginesPage

    _engines(monkeypatch, tmp_path)
    collected = []

    def install(engine, version, *, progress=None):
        (paths.engines_dir() / f"camoufox-{version}").mkdir(parents=True)
        (paths.engines_dir() / f"camoufox-{version}" / "camoufox").write_text("x")
        return version

    monkeypatch.setattr(ev, "install", install)
    page = EnginesPage(lambda: None)
    _pump_until(lambda: page._built)
    collect = page._collect
    monkeypatch.setattr(page, "_collect", lambda: (collected.append(1), collect())[1])
    latest = next(
        r for _g, r in page._built if (r.get_subtitle() or "") == "157.0.1 · not installed"
    )
    button = latest.get_first_child()
    stack = [latest]
    while stack:
        w = stack.pop()
        if isinstance(w, Gtk.Button) and w.get_label() == "Install":
            button = w
            break
        c = w.get_first_child()
        while c is not None:
            stack.append(c)
            c = c.get_next_sibling()
    button.emit("clicked")
    _pump_until(
        lambda: any((r.get_subtitle() or "") == "157.0.1 · installed" for _g, r in page._built)
    )
    import time

    from gi.repository import GLib

    time.sleep(0.3)
    ctx = GLib.MainContext.default()
    while ctx.pending():
        ctx.iteration(False)
    assert len(collected) == 1  # once, not in a loop


def test_preferences_sit_behind_a_gear_and_the_menu_is_slim():
    from gi.repository import Gio, Gtk

    from kiwi_fox.ui.window import Window

    win = Window()
    found = {"gear": False, "menu": None}
    stack = [win.get_first_child()]
    while stack:
        w = stack.pop()
        if w is None:
            continue
        if isinstance(w, Gtk.Button) and w.get_icon_name() == "emblem-system-symbolic":
            found["gear"] = True
        if isinstance(w, Gtk.MenuButton) and w.get_icon_name() == "open-menu-symbolic":
            found["menu"] = w.get_menu_model()
        stack += [w.get_next_sibling(), w.get_first_child()]
    assert found["gear"]
    model: Gio.MenuModel = found["menu"]
    labels = [
        model.get_item_attribute_value(i, "label", None).get_string()
        for i in range(model.get_n_items())
    ]
    assert len(labels) == 2 and labels[-1].startswith("About")


def test_a_maintenance_job_closes_preferences_and_runs_the_windows_action():
    from gi.repository import Adw, Gtk

    from kiwi_fox.ui.maintenance import MaintenancePage

    class Win(Gtk.Window):
        ran: list = []

        def activate_action(self, name, args=None):
            self.ran.append(name)
            return True

    win = Win()
    page = MaintenancePage(win, [("Set up environment", "x", "Set up", "win.setup")])
    dialog = Adw.PreferencesDialog()
    dialog.add(page)
    closed = []
    dialog.connect("closed", lambda *_: closed.append(1))
    dialog.present(win)
    page.buttons["win.setup"].emit("clicked")
    assert win.ran == ["win.setup"]
