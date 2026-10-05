"""Each test is one way a real machine would contradict itself."""

import pytest

from kiwi_fox.core.fingerprint import validate, validate_against
from kiwi_fox.core.fingerprint.validator import errors

ENGINE = "152.0.4"


def codes(issues):
    return {i.code for i in issues}


def test_clean_profile_has_no_issues(fp):
    assert validate(fp, engine_version=ENGINE, exit_country="DE") == []


def test_camoufox_in_ua_is_an_error(fp):
    fp.ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Camoufox/152.0.4"
    assert "ua.leak" in codes(errors(validate(fp, engine_version=ENGINE)))


def test_linux_ua_is_an_error(fp):
    fp.ua = "Mozilla/5.0 (X11; Linux x86_64; rv:152.0) Gecko/20100101 Firefox/152.0"
    found = codes(errors(validate(fp, engine_version=ENGINE)))
    assert {"ua.os", "ua.leak"} & found


def test_windows_nt_11_is_rejected(fp):
    fp.ua = "Mozilla/5.0 (Windows NT 11.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0"
    assert "ua.nt11" in codes(errors(validate(fp, engine_version=ENGINE)))


def test_ua_version_must_match_the_pinned_engine(fp):
    assert "ua.version" in codes(errors(validate(fp, engine_version="156.0.1")))


def test_platform_must_be_win32(fp):
    fp.platform = "Linux x86_64"
    assert "platform" in codes(errors(validate(fp, engine_version=ENGINE)))


def test_window_larger_than_avail_is_rejected(fp):
    fp.window.outer_height = fp.screen.avail_height + 200
    assert "window.outer" in codes(errors(validate(fp, engine_version=ENGINE)))


def test_inner_larger_than_outer_is_rejected(fp):
    fp.window.inner_height = fp.window.outer_height + 10
    assert "window.inner" in codes(errors(validate(fp, engine_version=ENGINE)))


def test_partial_screen_block_is_rejected(fp):
    # An absent screen key falls back to the real monitor, measured on the VM.
    fp.screen.avail_width = 0
    assert "screen.partial" in codes(errors(validate(fp, engine_version=ENGINE)))


@pytest.mark.parametrize("dpr", [2.0, 1.1, 3.0])
def test_implausible_dpr_is_rejected(fp, dpr):
    fp.screen.device_pixel_ratio = dpr
    assert "screen.dpr" in codes(errors(validate(fp, engine_version=ENGINE)))


def test_software_renderer_leak_is_rejected(fp):
    fp.webgl.renderer = "Mesa/X.org llvmpipe (LLVM 17.0.6, 256 bits)"
    assert "webgl.software" in codes(errors(validate(fp, engine_version=ENGINE)))


def test_cores_implausible_for_the_gpu(fp):
    fp.hardware_concurrency = 128
    assert "cores.gpu" in codes(errors(validate(fp, engine_version=ENGINE)))


def test_timezone_must_match_locale(fp):
    fp.timezone = "America/New_York"
    assert "locale.timezone" in codes(errors(validate(fp, engine_version=ENGINE)))


def test_exit_country_mismatch_is_a_warning_not_a_block(fp):
    issues = validate(fp, engine_version=ENGINE, exit_country="US")
    assert errors(issues) == []
    assert "locale.exit" in codes(issues)


def test_missing_core_fonts_rejected(fp):
    fp.fonts = [f for f in fp.fonts if f != "Segoe UI"]
    assert {"fonts.core", "fonts.mismatch"} & codes(errors(validate(fp, engine_version=ENGINE)))


def test_unset_canvas_seed_rejected(fp):
    fp.canvas_seed = 0
    assert "canvas.seed" in codes(errors(validate(fp, engine_version=ENGINE)))


def test_desktop_with_a_discharging_battery_rejected(fp):
    fp.form_factor = "desktop"
    fp.battery.charging = False
    fp.battery.discharging_time = 3600.0
    found = codes(errors(validate(fp, engine_version=ENGINE)))
    assert {"battery.desktop", "battery.desktop.time"} & found


def test_required_prefs_enforced(fp):
    bad = {
        "dom.webgpu.enabled": True,
        "network.proxy.failover_direct": True,
        "network.trr.mode": 2,
        "privacy.resistFingerprinting": True,
        "privacy.fingerprintingProtection": True,
    }
    found = codes(errors(validate(fp, engine_version=ENGINE, prefs=bad)))
    assert "prefs.required" in found


def test_rare_prefs_are_rejected(fp):
    # The documented pfox failure: each is detectable by its absence.
    good = {
        "dom.webgpu.enabled": False,
        "network.proxy.failover_direct": False,
        "network.trr.mode": 5,
        "privacy.resistFingerprinting": False,
        "privacy.fingerprintingProtection": False,
        "webgl.disabled": True,
    }
    assert "prefs.rare" in codes(errors(validate(fp, engine_version=ENGINE, prefs=good)))


def test_two_profiles_sharing_a_canvas_seed_is_an_error(fp):
    import copy

    twin = copy.deepcopy(fp)
    twin.seed = "different"
    assert "dup.canvas" in codes(errors(validate_against(fp, [twin])))


def test_identical_font_set_warns(fp):
    import copy

    twin = copy.deepcopy(fp)
    twin.seed = "different"
    twin.canvas_seed = fp.canvas_seed + 1
    assert "dup.fonts" in codes(validate_against(fp, [twin]))


def test_low_core_count_is_rejected(fp):
    # Measured: the one profile reporting 4 cores was flagged as a virtual machine
    # while 6 and 8 came back clean.
    fp.hardware_concurrency = 4
    assert "cores.vmlike" in codes(errors(validate(fp, engine_version=ENGINE)))


def test_a_camera_without_a_microphone_is_flagged(fp):
    fp.media_devices = {"micros": 0, "webcams": 1, "speakers": 1}
    issues = validate(fp, engine_version=ENGINE)
    assert "media.crash" in codes(issues)
    assert errors(issues) == [], "repaired at launch, so it must not block an old profile"


def test_stored_touch_points_are_flagged_as_unreportable(fp):
    fp.max_touch_points = 10
    issues = validate(fp, engine_version=ENGINE)
    assert "touch.inert" in codes(issues)
    assert errors(issues) == []


def test_profiles_from_before_the_series_rework_still_validate(fp):
    # They stored Chrome-style strings with a PCI id; the series is recovered from
    # the card they name.
    from kiwi_fox.core.fingerprint import webgl

    fp.form_factor = "desktop"
    fp.battery.charging, fp.battery.level, fp.battery.discharging_time = True, 1.0, None
    fp.webgl.vendor = "Google Inc. (AMD)"
    fp.webgl.family = "amd"
    fp.webgl.renderer = "ANGLE (AMD, AMD Radeon RX 6600 (0x000073FF) Direct3D11 vs_5_0 ps_5_0, D3D11-31.0.21921.1000)"
    fp.hardware_concurrency = 12
    assert webgl.series_for(fp.webgl.renderer).key == "radeon-r9-200"
    assert errors(validate(fp, engine_version=ENGINE)) == []
    assert "webgl.unknown" not in codes(validate(fp, engine_version=ENGINE))


def test_webgl_mode_checks():
    from kiwi_fox.core.fingerprint import webgl
    from kiwi_fox.core.fingerprint.validator import check_webgl_mode

    assert check_webgl_mode("host") == []
    assert check_webgl_mode("preset", series="intel-hd") == []
    assert "webgl.series" in codes(errors(check_webgl_mode("preset", series="voodoo")))
    assert codes(check_webgl_mode("off")) == {"webgl.off"}
    assert codes(check_webgl_mode("raw")) == {"webgl.raw"}
    # custom: both strings or nothing
    assert len(errors(check_webgl_mode("custom"))) == 2  # vendor and renderer
    assert len(errors(check_webgl_mode("custom", "Google Inc. (AMD)", None))) == 1
    mesa = check_webgl_mode("custom", "Mesa", "llvmpipe (LLVM 20.1, 256 bits)")
    assert "webgl.custom.linux" in codes(errors(mesa))
    # a string Firefox really sends passes clean; a card name is allowed but called out
    real = webgl.BY_KEY["intel-hd-400"]
    assert check_webgl_mode("custom", real.vendor, real.renderer) == []
    card = check_webgl_mode(
        "custom",
        "Google Inc. (NVIDIA)",
        "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11-32.0.15.6094)",
    )
    assert codes(card) == {"webgl.custom.unreal"} and errors(card) == []
    assert "GeForce GTX 980" in card[0].message, "it should say what a real Firefox reports"


def test_a_duplicate_is_reported_once_however_many_profiles_share_it(fp):
    twins = [
        fp.model_copy(update={"seed": f"dup-{n}", "canvas_seed": fp.canvas_seed + n})
        for n in (1, 2, 3)
    ]
    issues = validate_against(fp, twins[:1])
    assert [i.code for i in issues] == ["dup.fonts", "dup.machine"]
    assert issues[0].message == "another profile exposes the identical font set"
    issues = validate_against(fp, twins)
    assert [i.code for i in issues] == ["dup.fonts", "dup.machine"]
    assert issues[0].message == "3 other profiles expose the identical font set"
    assert issues[1].message.startswith("3 other profiles have the same GPU string")
