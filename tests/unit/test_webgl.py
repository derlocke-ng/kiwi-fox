"""WebGL as Firefox on Windows presents it: a series, never a card."""

import json

import pytest

from kiwi_fox.core.fingerprint import webgl

# What Firefox's sanitiser makes of real driver strings. Each left-hand side is a
# name a driver actually reports; the port must agree with SanitizeRenderer.cpp.
SANITISED = {
    # Windows, ANGLE/Direct3D
    "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11-32.0.15.6094)": "geforce-gtx-980",
    "ANGLE (NVIDIA, NVIDIA GeForce RTX 4060 Laptop GPU Direct3D11 vs_5_0 ps_5_0, D3D11-32.0.15.6094)": "geforce-gtx-980",
    "ANGLE (NVIDIA, NVIDIA GeForce GTX 1650 Direct3D11 vs_5_0 ps_5_0, D3D11-31.0.15.3623)": "geforce-gtx-980",
    "ANGLE (NVIDIA, NVIDIA GeForce GTX 750 Ti Direct3D11 vs_5_0 ps_5_0, D3D11-30.0.14.7514)": "geforce-gtx-480",
    "ANGLE (NVIDIA, NVIDIA GeForce MX450 Direct3D11 vs_5_0 ps_5_0, D3D11-31.0.15.3623)": "geforce-gtx-480",
    "ANGLE (Intel, Intel(R) UHD Graphics 620 Direct3D11 vs_5_0 ps_5_0, D3D11-31.0.101.2111)": "intel-hd-400",
    "ANGLE (Intel, Intel(R) UHD Graphics 770 Direct3D11 vs_5_0 ps_5_0, D3D11-31.0.101.4502)": "intel-hd-400",
    "ANGLE (Intel, Intel(R) Iris(R) Xe Graphics Direct3D11 vs_5_0 ps_5_0, D3D11-31.0.101.5186)": "intel-hd",
    "ANGLE (Intel, Intel(R) UHD Graphics Direct3D11 vs_5_0 ps_5_0, D3D11-31.0.101.5186)": "intel-hd",
    "ANGLE (Intel, Intel(R) HD Graphics 4600 Direct3D11 vs_5_0 ps_5_0, D3D11-20.19.15.5171)": "intel-hd",
    "ANGLE (AMD, AMD Radeon(TM) Graphics Direct3D11 vs_5_0 ps_5_0, D3D11-31.0.21921.1000)": "radeon-hd-3200",
    "ANGLE (AMD, AMD Radeon RX 6600 Direct3D11 vs_5_0 ps_5_0, D3D11-31.0.21921.1000)": "radeon-r9-200",
    "ANGLE (AMD, AMD Radeon RX 580 2048SP Direct3D11 vs_5_0 ps_5_0, D3D11-31.0.21921.1000)": "radeon-r9-200",
    "ANGLE (AMD, AMD Radeon(TM) 680M Direct3D11 vs_5_0 ps_5_0, D3D11-31.0.21921.1000)": "radeon-r9-200",
    "ANGLE (AMD, AMD Radeon(TM) Vega 8 Graphics Direct3D11 vs_5_0 ps_5_0, D3D11-31.0.21921.1000)": "radeon-r9-200",
    # Linux drivers, as a raw probe of the host sees them
    "AMD Radeon 680M (radeonsi, rembrandt, LLVM 20.1.8, DRM 3.64, 7.1.6-201.fc44.x86_64)": "radeon-r9-200",
    "AMD Radeon Graphics (radeonsi, renoir, LLVM 19.1.0, DRM 3.59, 6.12.0)": "radeon-hd-3200",
    "Mesa Intel(R) UHD Graphics 620 (KBL GT2)": "intel-hd-400",
    "NVIDIA GeForce RTX 4060 Laptop GPU/PCIe/SSE2": "geforce-gtx-980",
    # what a Linux Firefox has already sanitised
    "Radeon R9 200 Series, or similar": "radeon-r9-200",
    "NVIDIA GeForce GTX 980, or similar": "geforce-gtx-980",
    "GeForce GTX 980, or similar": "geforce-gtx-980",
    "Intel(R) HD Graphics 400, or similar": "intel-hd-400",
    # the Chrome-style strings profiles stored before the rework
    "ANGLE (AMD, AMD Radeon RX 6600 (0x000073FF) Direct3D11 vs_5_0 ps_5_0, D3D11-31.0.21921.1000)": "radeon-r9-200",
    "ANGLE (AMD, AMD Radeon(TM) Graphics (0x00001638) Direct3D11 vs_5_0 ps_5_0, D3D11-31.0.21921.1000)": "radeon-hd-3200",
    "ANGLE (AMD, AMD Radeon R9 200 Series (0x00006810) Direct3D11 vs_5_0 ps_5_0, D3D11-31.0.21921.1000)": "radeon-r9-200",
    "ANGLE (Intel, Intel(R) UHD Graphics 630 (0x00003E92) Direct3D11 vs_5_0 ps_5_0, D3D11-31.0.101.2115)": "intel-hd-400",
    "ANGLE (Intel, Intel(R) Iris(R) Xe Graphics (0x00009A49) Direct3D11 vs_5_0 ps_5_0, D3D11-31.0.101.5186)": "intel-hd",
    "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 (0x00002503) Direct3D11 vs_5_0 ps_5_0, D3D11-32.0.15.6094)": "geforce-gtx-980",
}

# Not hardware Windows users run, or not hardware at all.
NO_SERIES = (
    "llvmpipe (LLVM 20.1.8, 256 bits)",
    "llvmpipe, or similar",
    "ANGLE (Microsoft, Microsoft Basic Render Driver Direct3D11 vs_5_0 ps_5_0, D3D11-10.0.22621.1)",
    "",
)

# State, not capability: values the page itself changes. Pinning any of them makes
# the browser contradict what the page just did.
STATE = {
    2978: "VIEWPORT",
    3088: "SCISSOR_BOX",
    3042: "BLEND",
    2929: "DEPTH_TEST",
    34016: "ACTIVE_TEXTURE",
    35725: "CURRENT_PROGRAM",
    34964: "ARRAY_BUFFER_BINDING",
    36006: "FRAMEBUFFER_BINDING",
    32873: "TEXTURE_BINDING_2D",
    3317: "UNPACK_ALIGNMENT",
    3413: "ALPHA_BITS",
    3414: "DEPTH_BITS",
    32937: "SAMPLES",
    34467: "COMPRESSED_TEXTURE_FORMATS",
    34047: "MAX_TEXTURE_MAX_ANISOTROPY_EXT",
}


@pytest.mark.parametrize("raw,key", SANITISED.items())
def test_series_for_agrees_with_firefoxs_sanitiser(raw, key):
    assert webgl.series_for(raw).key == key


@pytest.mark.parametrize("raw", NO_SERIES)
def test_software_and_unknown_renderers_have_no_series(raw):
    assert webgl.series_for(raw) is None


def test_sanitiser_writes_the_string_the_way_firefox_does():
    raw = "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11-32.0.15.6094)"
    assert (
        webgl.sanitize_renderer(raw)
        == "ANGLE (NVIDIA, NVIDIA GeForce GTX 980 Direct3D11 vs_5_0 ps_5_0), or similar"
    )
    # and that is exactly the string a series carries
    assert webgl.sanitize_renderer(raw) == webgl.BY_KEY["geforce-gtx-980"].renderer


def test_every_series_has_a_real_record_and_they_are_ordered_by_share():
    shares = [webgl.share(s) for s in webgl.SERIES]
    assert shares == sorted(shares, reverse=True)
    assert 0.9 < sum(shares) <= 1.0
    for series in webgl.SERIES:
        rec = webgl.record(series)
        assert rec["vendor"] == series.vendor
        assert series.family in series.vendor.lower()
        assert min(series.cores) >= 6, "fewer reads as a virtual machine"


@pytest.mark.parametrize(
    "typed,key",
    [
        ("RTX 3060", "geforce-gtx-980"),
        ("gtx 1650", "geforce-gtx-980"),
        ("GTX 750 Ti", "geforce-gtx-480"),
        ("iris xe", "intel-hd"),
        ("UHD 630", "intel-hd-400"),
        ("uhd graphics 770", "intel-hd-400"),
        ("rx 6600", "radeon-r9-200"),
        ("680M", "radeon-r9-200"),
        ("vega 8", "radeon-r9-200"),
        ("Ryzen", "radeon-hd-3200"),
        ("radeon-hd-3200", "radeon-hd-3200"),
    ],
)
def test_find_understands_what_people_type(typed, key):
    assert webgl.find(typed).key == key


@pytest.mark.parametrize("typed", ["voodoo", "geforce", ""])
def test_find_refuses_what_it_cannot_place(typed):
    with pytest.raises(ValueError, match="does not name one GPU series"):
        webgl.find(typed)


@pytest.mark.parametrize("series", webgl.SERIES, ids=lambda s: s.key)
def test_engine_config_is_one_coherent_record(series):
    cfg = webgl.engine_config(series)
    assert cfg["webGl:vendor"] == series.vendor
    assert cfg["webGl:renderer"] == series.renderer
    for ctx in ("webGl", "webGl2"):
        params = cfg[f"{ctx}:parameters"]
        # masked and unmasked agree, and the masked vendor is Firefox's constant
        assert params["7937"] == series.renderer
        assert params["7936"] == "Mozilla"
        # The unmasked pair must stay out of the table: the engine consults the
        # table before Firefox checks the extension was enabled, so listing them
        # would answer a query a real Firefox rejects.
        assert "37445" not in params and "37446" not in params
        assert None not in params.values()
        emitted = {int(k) for k in params} - {7936, 7937}
        assert emitted <= webgl.CAPABILITIES | webgl.PLATFORM_DEFAULTS
        assert not emitted & set(STATE), [STATE[i] for i in emitted & set(STATE)]
        # the limits that tell ANGLE from Mesa
        assert params["3386"] == [32767, 32767]  # MAX_VIEWPORT_DIMS
        assert params["33902"] == [1, 1]  # ALIASED_LINE_WIDTH_RANGE
        assert params["2963"] == 2147483647  # STENCIL_VALUE_MASK
        extensions = cfg[f"{ctx}:supportedExtensions"]
        assert "WEBGL_debug_renderer_info" in extensions
        for linux_only in ("WEBGL_compressed_texture_astc", "EXT_depth_clamp"):
            assert linux_only not in extensions
        assert len(cfg[f"{ctx}:shaderPrecisionFormats"]) == 12
    assert len(cfg["webGl2:parameters"]) > len(cfg["webGl:parameters"])
    assert "webGl:contextAttributes" not in cfg, "they depend on what the page asked for"
    json.dumps(cfg, allow_nan=False)


def test_custom_strings_replace_both_renderers_and_keep_the_limits():
    series = webgl.BY_KEY["intel-hd-400"]
    cfg = webgl.engine_config(series, vendor="V", renderer="R")
    assert (cfg["webGl:vendor"], cfg["webGl:renderer"]) == ("V", "R")
    assert cfg["webGl:parameters"]["7937"] == cfg["webGl2:parameters"]["7937"] == "R"
    assert cfg["webGl:parameters"]["7936"] == "Mozilla"
    plain = webgl.engine_config(series)
    assert cfg["webGl2:supportedExtensions"] == plain["webGl2:supportedExtensions"]


def test_resolve_by_mode(monkeypatch):
    amd, intel, nvidia = (webgl.BY_KEY[k] for k in ("radeon-r9-200", "intel-hd", "geforce-gtx-980"))
    monkeypatch.setattr(webgl, "host_series", lambda: (amd, "measured"))
    assert webgl.resolve("off") is None
    # host follows the machine, not what the profile stored
    assert webgl.resolve("host", stored_renderer=intel.renderer) is amd
    # preset: the explicit choice, else the fingerprint's
    assert webgl.resolve("preset", stored_renderer=intel.renderer) is intel
    assert webgl.resolve("preset", stored_renderer=intel.renderer, series_key=nvidia.key) is nvidia
    # custom: limits from the series the string belongs to, else its vendor's
    card = "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11-32.0.15.6094)"
    assert webgl.resolve("custom", stored_renderer=intel.renderer, custom_renderer=card) is nvidia
    assert webgl.resolve("custom", custom_renderer="Some Intel Thing").family == "intel"
    # nothing known about the machine: host falls back to the stored series
    monkeypatch.setattr(webgl, "host_series", lambda: (None, "unknown"))
    assert webgl.resolve("host", stored_renderer=intel.renderer) is intel


def test_host_series_prefers_a_measurement_over_the_vendor(monkeypatch):
    from kiwi_fox.core import gpu

    assert webgl.host_series() == (None, "unknown")
    monkeypatch.setattr(
        gpu, "plan", lambda prefer=None: gpu.Plan("mesa", ("/dev/dri/renderD128",), {}, "amd", "")
    )
    series, how = webgl.host_series()
    assert (series.key, how) == ("radeon-r9-200", "family")
    webgl.remember_host_renderer("Intel(R) HD Graphics 400, or similar")
    series, how = webgl.host_series()
    assert (series.key, how) == ("intel-hd-400", "measured")
    # a software renderer is a measurement of nothing: fall back to the vendor
    webgl.remember_host_renderer("llvmpipe, or similar")
    assert webgl.host_series()[1] == "family"


@pytest.mark.parametrize("series", webgl.SERIES, ids=lambda s: s.key)
def test_firefox_sanitises_the_driver_string_back_to_the_series(series):
    # The pref value goes through Firefox's own sanitiser, for RENDERER and for
    # the debug extension. It must come out as exactly the string the engine
    # config carries, or the two would disagree again.
    raw = webgl.driver_string(series.renderer)
    assert raw != series.renderer and raw.count(", ") == 2, "ANGLE's driver field is missing"
    assert webgl.sanitize_renderer(raw) == series.renderer
    assert webgl.firefox_prefs(series) == {
        "webgl.override-unmasked-vendor": series.vendor,
        "webgl.override-unmasked-renderer": raw,
    }


def test_a_custom_driver_string_is_passed_on_as_it_is():
    card = "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11-32.0.15.6094)"
    assert webgl.driver_string(card) == card
    # Firefox would report the series for it, which is what a real one does
    assert webgl.sanitize_renderer(card) == webgl.BY_KEY["geforce-gtx-980"].renderer
    assert webgl.driver_string("Some Free Text") == "Some Free Text"
