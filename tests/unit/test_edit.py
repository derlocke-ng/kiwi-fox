"""Changing a profile on purpose: every edit is coherent or refused."""

import pytest

from kiwi_fox import cli
from kiwi_fox.core import store
from kiwi_fox.core.fingerprint import edit, fonts, generate, validate
from kiwi_fox.core.fingerprint import windows11 as w11
from kiwi_fox.core.fingerprint.validator import check_window_fits, errors

ENGINE = "152.0.4"


@pytest.fixture
def stored(profile, fp):
    store.save(profile)
    store.save_fingerprint(profile.id, fp)
    return profile


def test_screen_must_be_one_real_machines_report(fp):
    out = edit.with_screen(fp.model_copy(update={"form_factor": "desktop"}), "1920x1080")
    assert (out.screen.width, out.screen.avail_height, out.window.outer_height) == (
        1920,
        1032,
        1032,
    )
    assert errors(validate(out, engine_version=ENGINE)) == []
    for bad in ("1280x800", "banana", "1920"):
        with pytest.raises(edit.EditError):
            edit.with_screen(fp, bad)
    with pytest.raises(edit.EditError, match="1920x1080"):  # it says what is on offer
        edit.with_screen(fp, "1600x900")


def test_form_takes_battery_camera_and_screen_with_it():
    desktop = generate(engine_version=ENGINE, form_factor="desktop", seed="e")
    laptop = edit.with_form(desktop, "laptop")
    assert laptop.form_factor == "laptop" and laptop.media_devices["webcams"] == 1
    back = edit.with_form(laptop, "desktop")
    assert back.battery.level == 1.0 and back.battery.discharging_time is None
    for out in (laptop, back):
        assert errors(validate(out, engine_version=ENGINE)) == []


def test_region_changes_everything_that_speaks_a_language(fp):
    out = edit.with_region(fp, "se")
    assert (out.locale, out.timezone, out.languages[0]) == ("sv-SE", "Europe/Stockholm", "sv-SE")
    assert out.accept_language.startswith("sv-SE") and out.voices == w11.voices_for(
        w11.REGIONS["SE"]
    )
    assert edit.with_region(fp, "SE", keep_timezone=True).timezone == fp.timezone
    with pytest.raises(edit.EditError, match="no region"):
        edit.with_region(fp, "ZZ")
    with pytest.raises(edit.EditError, match="IANA"):
        edit.with_timezone(fp, "Mars/Olympus")
    assert edit.with_timezone(fp, "Europe/Zurich").timezone == "Europe/Zurich"


def test_fonts_can_change_only_where_real_machines_differ(fp):
    extra = next(f for f in edit.optional_fonts() if f not in fp.fonts)
    added = edit.with_fonts(fp, add=[extra.lower()])  # case does not matter
    assert extra in added.fonts and added.font_files == fonts.files_for(added.fonts)
    assert extra not in edit.with_fonts(added, remove=[extra]).fonts
    with pytest.raises(edit.EditError, match="every Windows 11"):
        edit.with_fonts(fp, remove=[fonts.all_core_families()[0]])
    with pytest.raises(edit.EditError, match="not a font"):
        edit.with_fonts(fp, add=["Comic Papyrus"])
    assert errors(validate(added, engine_version=ENGINE)) == []


def test_a_camera_never_comes_without_a_microphone(fp):
    assert edit.with_camera(fp, True).media_devices == {
        **fp.media_devices,
        "micros": 1,
        "webcams": 1,
    }
    assert edit.with_camera(fp, False).media_devices["micros"] == 1


def test_user_agent_notes_say_what_will_stand_out(fp):
    assert edit.check_user_agent(fp.ua, fp.engine_version) == []
    notes = edit.check_user_agent(
        "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0", fp.engine_version
    )
    assert len(notes) == 2 and "Windows" in notes[0] and "Firefox 152" in notes[1]


def test_an_unmeasured_host_only_gets_screens_its_window_fits(monkeypatch):
    # A fresh install drew 1366x768 for a window that opens 1040 tall: bigger than
    # its own screen. Until this host is measured, assume the engine's default.
    assert w11.host_window_height() == w11.DEFAULT_WINDOW_HEIGHT == 1092
    for i in range(120):
        fp = generate(engine_version=ENGINE, seed=f"u{i}")
        assert fp.screen.avail_height >= 1092, (fp.screen.width, fp.screen.height)
        assert check_window_fits(fp) == []
    w11.remember_host_window_height(768)  # a small real monitor: smaller screens fit too
    heights = {generate(engine_version=ENGINE, seed=f"m{i}").screen.height for i in range(200)}
    assert {1080, 1440} <= heights


def test_a_window_taller_than_the_claimed_screen_is_pointed_out(fp):
    small = edit.with_screen(edit.with_form(fp, "laptop"), "1366x768")
    (issue,) = check_window_fits(small)
    assert issue.level == "warn" and "1366x768" in issue.message and "--screen" in issue.message


# ------------------------------------------------------------------ kiwi-fox set
def test_set_saves_coherent_changes(stored, fp, capsys):
    assert cli.main(["set", stored.name, "--country", "FR", "--cores", str(fp.hardware_concurrency),
                     "--appearance", "dark", "--camera", "no"]) == 0  # fmt: skip
    new, p = store.load_fingerprint(stored.id), store.load(stored.id)
    assert new.locale == "fr-FR" and new.timezone == "Europe/Paris"
    assert p.appearance == "dark" and new.media_devices["webcams"] == 0
    assert "fr-FR" in capsys.readouterr().out


def test_set_refuses_an_incoherent_change_and_writes_nothing(stored, fp, capsys):
    assert cli.main(["set", stored.name, "--cores", "2", "--country", "FR"]) == 1
    assert store.load_fingerprint(stored.id) == fp, "half an edit must not be saved"
    assert "nothing was changed" in capsys.readouterr().err


def test_set_user_agent_and_back(stored, fp, capsys):
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:157.0) Gecko/20100101 Firefox/157.0"
    assert cli.main(["set", stored.name, "--user-agent", ua]) == 0
    assert store.load(stored.id).user_agent == ua
    assert "ua.custom" in capsys.readouterr().out
    assert cli.main(["set", stored.name, "--default-user-agent"]) == 0
    assert store.load(stored.id).user_agent is None


def test_set_without_arguments_lists_what_can_be_chosen(stored, capsys):
    assert cli.main(["set", stored.name]) == 0
    out = capsys.readouterr().out
    assert "nothing changed" in out and "screens :" in out and "regions :" in out


def test_fonts_lists_what_a_profile_has(stored, fp, capsys):
    assert cli.main(["fonts", stored.name]) == 0
    out = capsys.readouterr().out
    assert all(name in out for name in edit.optional_fonts())
    assert out.count("[x]") == len(set(fp.fonts) & set(edit.optional_fonts()))
