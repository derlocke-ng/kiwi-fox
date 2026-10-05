from kiwi_fox.core.fingerprint import generate, validate
from kiwi_fox.core.fingerprint.validator import errors

ENGINE = "152.0.4"


def test_deterministic_from_seed():
    a = generate(engine_version=ENGINE, country="DE", seed="seed-one")
    b = generate(engine_version=ENGINE, country="DE", seed="seed-one")
    assert a == b


def test_different_seeds_differ_where_it_matters():
    a = generate(engine_version=ENGINE, country="DE", seed="one")
    b = generate(engine_version=ENGINE, country="DE", seed="two")
    assert a.canvas_seed != b.canvas_seed
    assert a.audio.seed != b.audio.seed


def test_many_seeds_are_all_coherent():
    for i in range(300):
        fp = generate(engine_version=ENGINE, country="DE", seed=f"s{i}")
        assert errors(validate(fp, engine_version=ENGINE)) == [], f"seed s{i}: {validate(fp)}"


def test_ua_is_stock_firefox_not_camoufox():
    fp = generate(engine_version=ENGINE, seed="x")
    assert "Camoufox" not in fp.ua
    assert "Firefox/152.0" in fp.ua
    assert "Windows NT 10.0; Win64; x64" in fp.ua


def test_region_drives_locale_and_timezone():
    fp = generate(engine_version=ENGINE, country="NL", seed="x")
    assert fp.locale == "nl-NL"
    assert fp.timezone == "Europe/Amsterdam"
    assert fp.accept_language.startswith("nl-NL")


def test_unknown_country_falls_back_without_crashing():
    fp = generate(engine_version=ENGINE, country="ZZ", seed="x")
    assert errors(validate(fp, engine_version=ENGINE)) == []


def test_desktop_has_no_battery_and_laptop_does():
    desktop = generate(engine_version=ENGINE, form_factor="desktop", seed="d")
    assert desktop.battery.charging and desktop.battery.level == 1.0
    laptop = generate(engine_version=ENGINE, form_factor="laptop", seed="l")
    assert laptop.form_factor == "laptop"


def test_screen_block_is_complete():
    # An unset screen key falls back to the real monitor — measured on the VM.
    fp = generate(engine_version=ENGINE, seed="x")
    s = fp.screen
    assert all(v > 0 for v in (s.width, s.height, s.avail_width, s.avail_height))
    assert s.height - s.avail_height == 48  # Windows 11 taskbar
    assert s.width >= s.avail_width >= fp.window.outer_width >= fp.window.inner_width


def test_font_set_varies_between_profiles():
    sets = {tuple(generate(engine_version=ENGINE, seed=f"f{i}").fonts) for i in range(40)}
    assert len(sets) > 1, "fonts are the per-profile lever; they must vary"


def test_fingerprint_round_trips_through_json():
    # pydantic turns float("inf") into null, which then fails to load: the bug
    # that broke the first real launch.
    from kiwi_fox.core.models import Fingerprint

    for form in ("desktop", "laptop"):
        for i in range(60):
            fp = generate(engine_version=ENGINE, form_factor=form, seed=f"rt{form}{i}")
            again = Fingerprint.model_validate_json(fp.model_dump_json())
            assert again == fp


def test_gpu_family_can_be_pinned():
    for fam in ("amd", "intel", "nvidia"):
        for i in range(25):
            fp = generate(engine_version=ENGINE, gpu_family=fam, seed=f"g{fam}{i}")
            assert fp.webgl.family == fam
            assert errors(validate(fp, engine_version=ENGINE)) == []


def test_third_party_fonts_vary_and_are_the_probed_ones():
    from kiwi_fox.core.fingerprint import fonts

    sets = set()
    for i in range(40):
        fp = generate(engine_version=ENGINE, seed=f"tp{i}")
        sets.add(tuple(f for f in fp.fonts if f in fonts.THIRD_PARTY))
    assert len(sets) > 1, "the fonts a fingerprinter probes for must differ per profile"


def test_engine_version_sorting_is_numeric():
    from kiwi_fox.core.engines.fetch import _version_key

    assert _version_key("152.0.4") < _version_key("156.0.1")
    # lexicographic ordering would get this backwards
    assert _version_key("99.0") < _version_key("152.0")


def test_hardware_readiness_requires_the_expected_helpers(tmp_path, monkeypatch):
    # A stray helper the build never calls must not count as ready.
    from kiwi_fox.core.engines import fetch

    monkeypatch.setattr(fetch, "expected_gl_helpers", lambda d: ["glxtest", "vaapitest"])
    assert not fetch.can_render_in_hardware(tmp_path)
    (tmp_path / "gfxtest").write_bytes(b"x")
    assert not fetch.can_render_in_hardware(tmp_path)
    (tmp_path / "glxtest").write_bytes(b"x")
    assert not fetch.can_render_in_hardware(tmp_path)
    (tmp_path / "vaapitest").write_bytes(b"x")
    assert fetch.can_render_in_hardware(tmp_path)


def test_screen_presets_are_real_windows_scale_combinations():
    # 1280x800 @1.5 is not a panel-and-scale pair Windows produces, and
    # fingerprint.com flagged the profile carrying it as a virtual machine.
    from kiwi_fox.core.fingerprint import windows11 as w11

    for preset in w11.SCREENS:
        physical = (round(preset.width * preset.dpr), round(preset.height * preset.dpr))
        assert physical in {
            (1920, 1080),
            (2560, 1440),
            (1366, 768),
        }, f"{preset.width}x{preset.height}@{preset.dpr} implies a {physical} panel"
        # Dominant shares only: 1280x800@1.5, 2048x1152@1.25 and 1600x900@1.0 were
        # each flagged as a virtual machine despite valid panel-and-scale maths.
        assert preset.dpr == 1.0 or (preset.width, preset.height) == (1536, 864)
        # Only the most common non-1.0 scale survives: rare logical resolutions were
        # flagged as virtual machines even though the arithmetic was valid.
        assert preset.dpr == 1.0 or (preset.width, preset.height) == (1536, 864)


def test_languages_reach_the_engine_as_a_list(fp=None):
    import datetime as dt

    from kiwi_fox.core.engines.camoufox import Camoufox
    from kiwi_fox.core.models import Endpoint, Profile

    fp = generate(engine_version=ENGINE, country="DE", seed="lang")
    profile = Profile(
        id="x",
        name="x",
        created=dt.datetime.now(dt.UTC),
        endpoint=Endpoint(host="10.0.0.1", port=1080),
    )
    cfg = Camoufox().config(fp, profile, None)
    assert cfg["locale:all"] == ",".join(fp.languages)
    assert len(fp.languages) > 1, "a single-entry language list is unusual"


def test_explicit_series_selection_is_honoured_exactly():
    # The first GUI passed a display label that never matched anything, so every
    # selection silently fell back to automatic.
    from kiwi_fox.core.fingerprint import webgl

    for series in webgl.SERIES:
        for form in series.forms:
            fp = generate(engine_version=ENGINE, series=series.key, form_factor=form, seed="sel")
            assert fp.webgl.renderer == series.renderer, series.key
            assert fp.webgl.vendor == series.vendor
            assert fp.form_factor == form
            assert fp.hardware_concurrency in series.cores
            assert errors(validate(fp, engine_version=ENGINE)) == []


def test_a_card_name_selects_the_series_firefox_reports_for_it():
    fp = generate(engine_version=ENGINE, series="RTX 3060", seed="x")
    assert "GeForce GTX 980" in fp.webgl.renderer  # what Firefox says for any RTX


def test_unknown_series_is_rejected_not_ignored():
    import pytest

    with pytest.raises(ValueError, match="does not name one GPU series"):
        generate(engine_version=ENGINE, series="Voodoo 3", seed="x")


def test_unasked_a_profile_gets_this_machines_series(monkeypatch):
    from kiwi_fox.core.fingerprint import webgl

    host = webgl.BY_KEY["intel-hd-400"]
    monkeypatch.setattr(webgl, "host_series", lambda: (host, "measured"))
    for i in range(40):
        assert generate(engine_version=ENGINE, seed=f"h{i}").webgl.renderer == host.renderer


def test_without_a_known_host_series_follow_real_world_share():
    from kiwi_fox.core.fingerprint import webgl

    seen = [generate(engine_version=ENGINE, seed=f"w{i}").webgl.renderer for i in range(400)]
    counts = {s.key: seen.count(s.renderer) for s in webgl.SERIES}
    assert all(counts.values()), f"a series was never drawn: {counts}"
    assert counts["geforce-gtx-980"] == max(counts.values()), counts
    assert counts["geforce-gtx-480"] == min(counts.values()), counts


def test_no_profile_can_crash_the_device_list():
    # A camera with no microphone before it makes the engine index past the end of
    # an empty array: the tab dies on enumerateDevices(). A quarter of all desktop
    # profiles used to be drawn that way.
    for form in ("desktop", "laptop"):
        for i in range(300):
            media = generate(engine_version=ENGINE, form_factor=form, seed=f"m{i}").media_devices
            assert media["micros"] >= 1, media
            assert media["speakers"] >= 1, media


def test_touch_is_never_claimed():
    # The engine cannot report touch points, so a profile must not claim any.
    assert not any(
        generate(engine_version=ENGINE, form_factor="laptop", seed=f"t{i}").max_touch_points
        for i in range(200)
    )


def test_voices_are_the_ones_windows_ships_for_the_language():
    from kiwi_fox.core.fingerprint import windows11 as w11

    for country, region in w11.REGIONS.items():
        fp = generate(engine_version=ENGINE, country=country, seed="v")
        assert fp.voices, f"{country}: a Windows machine with no voices does not exist"
        if region.locale in w11.VOICES:
            assert tuple(fp.voices) == w11.VOICES[region.locale]
    gb = generate(engine_version=ENGINE, country="GB", seed="v").voices
    assert "Microsoft Hazel - English (United Kingdom)" in gb
    assert not any("(Great Britain)" in v and "Desktop" not in v for v in gb)
