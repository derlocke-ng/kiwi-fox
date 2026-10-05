"""The engine must only ever use config keys that exist at the pinned tag."""

import json
from pathlib import Path

import pytest

from kiwi_fox.core import podman
from kiwi_fox.core.engines.camoufox import CHUNK, Camoufox, chunk_env, fontconfig_xml
from kiwi_fox.core.fingerprint import fonts

PROPS = Path(__file__).parent / "data" / "camoufox-properties-152.0.4.json"


@pytest.fixture(scope="module")
def known_keys() -> set[str]:
    return {e["property"] for e in json.loads(PROPS.read_text())}


@pytest.fixture
def engine():
    return Camoufox()


def test_every_emitted_config_key_exists_upstream(engine, fp, profile, known_keys):
    cfg = engine.config(fp, profile, exit_ip="203.0.113.9")
    unknown = sorted(set(cfg) - known_keys)
    assert not unknown, f"keys not in properties.json at the pinned tag: {unknown}"


def test_config_covers_the_whole_screen_block(engine, fp, profile, known_keys):
    cfg = engine.config(fp, profile, None)
    for key in (
        "screen.width",
        "screen.height",
        "screen.availWidth",
        "screen.availHeight",
        "screen.availLeft",
        "screen.availTop",
        "screen.colorDepth",
        "screen.pixelDepth",
    ):
        assert key in cfg, f"{key} missing: an unset key falls back to the real monitor"


def test_ua_is_set_in_both_places(engine, fp, profile):
    cfg = engine.config(fp, profile, None)
    assert cfg["navigator.userAgent"] == cfg["headers.User-Agent"] == fp.ua


def test_window_geometry_is_not_spoofed(engine, fp, profile):
    # Spoofing window.inner* while the real window differs makes Firefox
    # letterbox the content with grey padding. The window is sized instead.
    cfg = engine.config(fp, profile, None)
    for key in (
        "window.innerWidth",
        "window.innerHeight",
        "window.outerWidth",
        "window.outerHeight",
        "window.screenX",
        "window.screenY",
    ):
        assert key not in cfg, f"{key} must not be spoofed"
    assert cfg["window.devicePixelRatio"] == fp.screen.device_pixel_ratio


def test_webrtc_exposes_only_the_exit_ip(engine, fp, profile):
    assert engine.config(fp, profile, "203.0.113.9")["webrtc:ipv4"] == "203.0.113.9"
    assert "webrtc:ipv4" not in engine.config(fp, profile, None)
    assert "webrtc:ipv6" not in engine.config(fp, profile, None)


def test_ipv6_exit_uses_the_ipv6_key(engine, fp, profile):
    # Measured: Mullvad's SOCKS5 exits report IPv6.
    cfg = engine.config(fp, profile, "2a02:6ea0:cb1b:1::d001")
    assert cfg["webrtc:ipv6"] == "2a02:6ea0:cb1b:1::d001"
    assert "webrtc:ipv4" not in cfg


def test_no_infinities_reach_the_json(engine, fp, profile):
    # JSON cannot carry Infinity and the C++ parser would choke.
    env = engine.env(fp, profile, None)
    blob = "".join(env[k] for k in sorted(env) if k.startswith("CAMOU_CONFIG_"))
    json.loads(blob)  # raises on Infinity
    assert "Infinity" not in blob


def test_prefs_pin_the_dangerous_ones(engine, fp, profile):
    prefs = engine.prefs(fp, profile)
    assert prefs["dom.webgpu.enabled"] is False
    assert prefs["network.proxy.failover_direct"] is False
    assert prefs["network.trr.mode"] == 5
    assert prefs["privacy.resistFingerprinting"] is False
    assert prefs["network.proxy.socks_remote_dns"] is False


def test_remote_dns_mode_flips_the_pref(engine, fp, profile):
    profile.dns.mode = "remote"
    assert engine.prefs(fp, profile)["network.proxy.socks_remote_dns"] is True


def test_chunking_splits_and_rejoins():
    payload = {"k": "x" * (CHUNK * 2)}
    env = chunk_env("CAMOU_CONFIG", payload)
    assert len(env) == 3
    blob = "".join(env[f"CAMOU_CONFIG_{i + 1}"] for i in range(len(env)))
    assert json.loads(blob) == payload


def test_chunking_always_emits_at_least_one_var():
    assert list(chunk_env("CAMOU_PREFS", {})) == ["CAMOU_PREFS_1"]


def test_fontconfig_rejects_exactly_what_the_profile_lacks(fp):
    xml = fontconfig_xml(fp)
    every = set(fonts.files_for(fonts.all_core_families() + fonts.all_optional_families()))
    rejected = {
        line.split(">")[1].split("<")[0].rsplit("/", 1)[-1]
        for line in xml.splitlines()
        if "<glob>" in line
    }
    assert rejected == every - set(fp.font_files)
    for kept in fp.font_files:
        assert f"/{kept}<" not in xml


def test_browser_spec_grants_only_sys_chroot(engine, fp, profile):
    # Firefox's content sandbox chroots content processes; without the capability
    # its Chroot Helper segfaults and every tab dies. Nothing else is granted.
    spec = engine.build_spec(profile, fp, gateway="kf-gw-x", exit_ip=None)
    assert spec.cap_drop == ["all"]
    assert spec.cap_add == ["SYS_CHROOT"]
    assert spec.network == "container:kf-gw-x"
    assert "no-new-privileges" in spec.security_opt


def test_rendered_podman_args_are_stable(engine, fp, profile):
    spec = engine.build_spec(profile, fp, gateway="kf-gw-x", exit_ip=None)
    args = podman.spec_args(spec)
    assert args[0] == "run"
    assert "--privileged" not in args
    assert "--network" in args and "container:kf-gw-x" in args
    assert args[-1] == spec.image or spec.args


def test_no_camou_prefs_env_is_emitted(engine, fp, profile):
    # The engine binary has no CAMOU_PREFS string: inventing one meant Firefox
    # ran with no proxy and every page timed out.
    env = engine.env(fp, profile, None)
    assert not [k for k in env if k.startswith("CAMOU_PREFS")]
    assert [k for k in env if k.startswith("CAMOU_CONFIG")]


def test_user_js_carries_the_proxy_prefs(engine, fp, profile):
    from kiwi_fox.core.engines.camoufox import user_js

    text = user_js(engine.prefs(fp, profile))
    assert 'user_pref("network.proxy.type", 1);' in text
    assert 'user_pref("network.proxy.socks", "127.0.0.1");' in text
    assert 'user_pref("network.proxy.socks_port", 1080);' in text
    assert 'user_pref("network.proxy.failover_direct", false);' in text
    assert 'user_pref("dom.webgpu.enabled", false);' in text
    assert 'user_pref("network.trr.mode", 5);' in text


def test_user_js_renders_firefox_literals(engine, fp, profile):
    from kiwi_fox.core.engines.camoufox import user_js

    text = user_js({"a.bool": True, "a.num": 7, "a.str": 'has "quotes"'})
    assert 'user_pref("a.bool", true);' in text  # not Python's True
    assert 'user_pref("a.num", 7);' in text
    assert 'user_pref("a.str", "has \\"quotes\\"");' in text


def test_webgl_is_forced_on_but_webgl_disabled_is_untouched(engine, fp, profile):
    # No WebGL is a louder tell than software rendering; but touching
    # webgl.disabled is itself the pfox mistake.
    prefs = engine.prefs(fp, profile)
    assert prefs["webgl.force-enabled"] is True
    assert "webgl.disabled" not in prefs


def test_usability_prefs_restore_a_real_browser(engine, fp, profile):
    prefs = engine.prefs(fp, profile)
    assert prefs["toolkit.legacyUserProfileCustomizations.stylesheets"] is True
    assert prefs["browser.toolbars.bookmarks.visibility"] == "newtab"
    assert prefs["keyword.enabled"] is True


def test_user_chrome_css_restores_what_camoufox_hides():
    from kiwi_fox.core.engines.camoufox import USER_CHROME_CSS

    for selector in (
        ".tab-close-button",
        "#star-button-box",
        "#unified-extensions-button",
        ".titlebar-buttonbox-container",
        "#PersonalToolbar",
    ):
        assert selector in USER_CHROME_CSS, f"{selector} is hidden upstream and must be restored"
    assert "pointer-events: auto" in USER_CHROME_CSS


def test_chrome_marker_detection_is_not_self_defeating(tmp_path):
    # The first version searched for the upstream theme's name, which the
    # replacement comment itself contained, so a fixed file looked unfixed.
    from kiwi_fox.core.engines import fetch

    (tmp_path / "chrome.css").write_text("/* minimalisticfox */\n.tabbrowser-tab { }\n")
    assert fetch.chrome_css_is_minimal(tmp_path)
    assert fetch.apply_tweak(tmp_path, "chrome")
    assert not fetch.chrome_css_is_minimal(tmp_path)
    assert fetch.apply_tweak(tmp_path, "chrome") is False  # idempotent
    assert (tmp_path / "chrome.css.orig").exists()  # reversible


def test_toolbar_layout_puts_new_tab_beside_the_tabs(engine, fp, profile):
    import json

    state = json.loads(engine.prefs(fp, profile)["browser.uiCustomization.state"])
    tabs = state["placements"]["TabsToolbar"]
    assert "new-tab-button" in tabs, "the + belongs in the tab strip, not the nav-bar"
    assert "new-tab-button" not in state["placements"]["nav-bar"]
    assert "personal-bookmarks" in state["placements"]["PersonalToolbar"]


def test_webgl_off_sets_the_rare_pref_only_when_asked(engine, fp, profile):
    assert "webgl.disabled" not in engine.prefs(fp, profile)
    profile.webgl = "off"
    prefs = engine.prefs(fp, profile)
    assert prefs["webgl.disabled"] is True
    assert "webgl.force-enabled" not in prefs


def test_deliberate_webgl_off_warns_but_does_not_block(engine, fp, profile):
    from kiwi_fox.core.fingerprint import validate
    from kiwi_fox.core.fingerprint.validator import errors

    profile.webgl = "off"
    prefs = engine.prefs(fp, profile)
    blocked = validate(fp, engine_version=fp.engine_version, prefs=prefs)
    assert any(i.code == "prefs.rare" for i in errors(blocked)), "unannounced must block"
    allowed = validate(
        fp, engine_version=fp.engine_version, prefs=prefs, allow_prefs={"webgl.disabled"}
    )
    assert errors(allowed) == []
    assert any(i.code == "prefs.rare" and i.level == "warn" for i in allowed)


def test_run_uses_replace_so_concurrent_starts_cannot_collide(engine, fp, profile):
    # `podman rm` can return before the name is free; launching several profiles in
    # quick succession then failed with "container name is already in use".
    spec = engine.build_spec(profile, fp, gateway="kf-gw-x", exit_ip=None)
    args = podman.spec_args(spec)
    assert args[:2] == ["run", "--replace"]


def test_stop_removes_the_browser_before_the_gateway(monkeypatch, profile):
    # The browser shares the gateway's netns, so podman refuses to remove or
    # replace the gateway while it exists.
    from kiwi_fox.core import launch, paths, podman

    order: list[str] = []
    monkeypatch.setattr(podman, "rm", lambda name, **k: order.append(name))
    monkeypatch.setattr(podman, "secret_rm", lambda name: None)
    launch.stop(profile)
    assert order == [paths.browser_name(profile.id), paths.gateway_name(profile.id)]


# ------------------------------------------------------------------ graphics
def _gl(cfg):
    return {k: v for k, v in cfg.items() if k.startswith("webGl")}


def test_every_webgl_mode_emits_known_keys_only(engine, fp, profile, known_keys):
    for mode, extra in (
        ("host", {}),
        ("preset", {"webgl_series": "geforce-gtx-980"}),
        ("custom", {"webgl_vendor": "Google Inc. (Intel)", "webgl_renderer": "X"}),
        ("off", {}),
        ("raw", {}),
    ):
        p = profile.model_copy(update={"webgl": mode, **extra})
        cfg = engine.config(fp, p, None)
        assert not sorted(set(cfg) - known_keys), mode


def test_spoofed_modes_emit_the_whole_record_and_the_others_nothing(engine, fp, profile):
    for mode in ("host", "preset"):
        gl = _gl(engine.config(fp, profile.model_copy(update={"webgl": mode}), None))
        assert len(gl) == 8, f"{mode}: strings, tables, extensions and precision for both contexts"
        # one string in three places: a page comparing them must find no gap
        assert (
            gl["webGl:renderer"]
            == gl["webGl:parameters"]["7937"]
            == gl["webGl2:parameters"]["7937"]
        )
        assert gl["webGl:renderer"].startswith("ANGLE (") and gl["webGl:renderer"].endswith(
            ", or similar"
        )
    for mode in ("off", "raw"):
        assert _gl(engine.config(fp, profile.model_copy(update={"webgl": mode}), None)) == {}


def test_preset_uses_the_chosen_series_over_the_fingerprints(engine, fp, profile):
    from kiwi_fox.core.fingerprint import webgl

    for series in webgl.SERIES:
        p = profile.model_copy(update={"webgl": "preset", "webgl_series": series.key})
        assert engine.config(fp, p, None)["webGl:renderer"] == series.renderer


def test_custom_strings_reach_both_renderer_values(engine, fp, profile):
    vendor = "Google Inc. (NVIDIA)"
    renderer = (
        "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11-32.0.15.6094)"
    )
    p = profile.model_copy(
        update={"webgl": "custom", "webgl_vendor": vendor, "webgl_renderer": renderer}
    )
    gl = _gl(engine.config(fp, p, None))
    assert gl["webGl:vendor"] == vendor
    assert gl["webGl:renderer"] == gl["webGl:parameters"]["7937"] == renderer
    # and the limits are NVIDIA's, not whatever the fingerprint was drawn with
    from kiwi_fox.core.fingerprint import webgl

    assert gl["webGl2:parameters"] == {
        **webgl.engine_config(webgl.BY_KEY["geforce-gtx-980"])["webGl2:parameters"],
        "7937": renderer,
    }


def test_a_profile_from_before_the_rework_launches_as_its_series(engine, fp, profile):
    fp.webgl.renderer = "ANGLE (AMD, AMD Radeon RX 6600 (0x000073FF) Direct3D11 vs_5_0 ps_5_0, D3D11-31.0.21921.1000)"
    gl = _gl(engine.config(fp, profile, None))  # profile.webgl defaults to "preset"
    assert (
        gl["webGl:renderer"]
        == "ANGLE (AMD, Radeon R9 200 Series Direct3D11 vs_5_0 ps_5_0), or similar"
    )
    assert "0x" not in json.dumps(gl), "the Chrome-style string must not survive anywhere"


def test_the_whole_config_still_fits_the_environment(engine, fp, profile):
    env = chunk_env("CAMOU_CONFIG", engine.config(fp, profile, "203.0.113.9"))
    assert all(len(v) <= CHUNK for v in env.values())
    assert json.loads("".join(env[f"CAMOU_CONFIG_{i + 1}"] for i in range(len(env))))


# ----------------------------------------------------------- devices, voices
def test_a_camera_without_a_microphone_is_never_emitted(engine, fp, profile):
    # That combination indexes past the end of an empty array in the engine and
    # kills the tab on enumerateDevices(). Old profiles carry it; repair it here.
    fp.media_devices = {"micros": 0, "webcams": 1, "speakers": 1}
    cfg = engine.config(fp, profile, None)
    assert (cfg["mediaDevices:micros"], cfg["mediaDevices:webcams"]) == (1, 1)
    fp.media_devices = {"micros": 0, "webcams": 0, "speakers": 1}
    assert engine.config(fp, profile, None)["mediaDevices:micros"] == 0  # harmless: left alone


def test_voices_reach_the_engine_as_complete_objects(engine, fp, profile):
    cfg = engine.config(fp, profile, None)
    voices = cfg["voices"]
    assert [v["name"] for v in voices] == fp.voices
    for v in voices:
        # MaskConfig::MVoices() silently drops any entry missing one of these.
        assert set(v) == {"lang", "name", "voiceUri", "isDefault", "isLocalService"}
        assert v["voiceUri"] == f"urn:moz-tts:sapi:{v['name']}?{v['lang']}"
        assert v["isLocalService"] is True
    assert [v["isDefault"] for v in voices].count(True) == 1
    assert next(v for v in voices if v["isDefault"])["lang"] == fp.locale
    assert cfg["voices:blockIfNotDefined"] is True


def test_voice_names_from_old_profiles_are_corrected(engine, fp, profile):
    fp.locale = "en-GB"
    fp.voices = [
        "Microsoft David - English (United States)",
        "Microsoft Hazel - English (Great Britain)",
    ]
    voices = engine.config(fp, profile, None)["voices"]
    assert [v["name"] for v in voices] == [
        "Microsoft David - English (United States)",
        "Microsoft Hazel - English (United Kingdom)",
    ]
    assert [v["lang"] for v in voices] == ["en-US", "en-GB"]
    assert [v["isDefault"] for v in voices] == [False, True]


def test_touch_points_are_not_emitted(engine, fp, profile):
    # No patch at the pinned tag reads the key; emitting it would be a claim the
    # page never sees.
    fp.max_touch_points = 10
    assert "navigator.maxTouchPoints" not in engine.config(fp, profile, None)


def test_hardware_rendering_needs_a_node_mesa_can_drive(engine, fp, profile, monkeypatch):
    from kiwi_fox.core import gpu

    spec = engine.build_spec(profile, fp, gateway="kf-gw-x", exit_ip=None)
    assert spec.devices == ["/dev/dri/renderD128"]
    assert engine.prefs(fp, profile)["gfx.webrender.software"] is False
    # an NVIDIA-only host on the proprietary driver: nothing to pass through
    monkeypatch.setattr(gpu, "render_node", lambda: None)
    spec = engine.build_spec(profile, fp, gateway="kf-gw-x", exit_ip=None)
    assert spec.devices == []
    prefs = engine.prefs(fp, profile)
    assert prefs["gfx.webrender.software"] is True
    assert prefs["layers.gpu-process.enabled"] is False
