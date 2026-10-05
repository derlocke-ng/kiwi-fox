"""The probe measures a profile without ever touching it.

The first version stopped the user's running browser to get at the profile lock
and opened the real data directory, which left the probe page in the session
history: it came back at every launch as "Unable to connect". These tests pin the
replacement — a throwaway browser in a throwaway directory — with podman faked.
"""

import json
import urllib.parse
from pathlib import Path

import pytest

from kiwi_fox.core import launch, paths, podman, probe, store
from kiwi_fox.core.engines.camoufox import PROFILE_MOUNT
from kiwi_fox.core.fingerprint import webgl
from kiwi_fox.core.fingerprint import windows11 as w11

HOST_RENDERER = "Radeon R9 200 Series, or similar"
REPORT = {
    "webgl": {"available": True, "vendor": "Mozilla", "renderer": HOST_RENDERER},
    "window": {"outer": [1332, 1092], "inner": [1280, 985]},
}


class Rig:
    def __init__(self) -> None:
        self.running: dict[str, bool] = {}
        self.started: list = []
        self.removed: list[str] = []
        self.gateways_started: list[str] = []
        self.user_js = ""
        self.data_dir: Path | None = None
        self.reports = True


@pytest.fixture
def rig(monkeypatch, tmp_path, fp, profile):
    r = Rig()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    for sub in ("browser-data", "downloads"):
        (paths.profile_dir(profile.id) / sub).mkdir(parents=True)
    store.save(profile)
    store.save_fingerprint(profile.id, fp)
    (paths.profile_dir(profile.id) / "browser-data" / "sessionstore.jsonlz4").write_bytes(b"real")

    class Result:
        def __init__(self, stdout: str = "") -> None:
            self.stdout = stdout

    def exec_(name, args, **_k):
        script = " ".join(args)
        if "http_code" in script:
            return Result("200")
        if "GET /report?" in script and r.reports:
            return Result("GET /report?" + urllib.parse.quote(json.dumps(REPORT)))
        return Result()

    def start(spec, **_k):
        r.started.append(spec)
        r.data_dir = next(Path(src) for src, dst, _o in spec.volumes if dst == PROFILE_MOUNT)
        r.user_js = (r.data_dir / "user.js").read_text()
        return "id"

    def start_gateway(p):
        r.gateways_started.append(p.id)
        r.running[paths.gateway_name(p.id)] = True
        return paths.gateway_name(p.id), None

    monkeypatch.setattr(podman, "is_running", lambda name: r.running.get(name, False))
    monkeypatch.setattr(podman, "exec_", exec_)
    monkeypatch.setattr(podman, "start", start)
    monkeypatch.setattr(podman, "rm", lambda name, **_k: r.removed.append(name))
    monkeypatch.setattr(podman, "secret_rm", lambda name: r.removed.append(f"secret:{name}"))
    monkeypatch.setattr(podman, "logs", lambda name, **_k: "")
    monkeypatch.setattr(probe.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(probe.time, "sleep", lambda _s: None)
    monkeypatch.setattr(launch, "start_gateway", start_gateway)
    return r


def test_the_users_session_is_never_touched(rig, profile):
    gateway, browser = paths.gateway_name(profile.id), paths.browser_name(profile.id)
    rig.running = {gateway: True, browser: True}  # the user is browsing right now
    real = paths.profile_dir(profile.id) / "browser-data"

    report = probe.probe(profile)

    assert report == REPORT
    assert len(rig.started) == 1
    spec = rig.started[0]
    assert spec.name == f"kf-probe-{profile.id[:8]}" and spec.name != browser
    assert str(real) not in [src for src, _dst, _o in spec.volumes], "the real profile was mounted"
    assert browser not in rig.removed, "the probe stopped the user's browser"
    assert gateway not in rig.removed
    assert rig.gateways_started == []
    assert rig.removed.count(spec.name) == 2  # cleared before, removed after
    assert sorted(p.name for p in real.iterdir()) == ["sessionstore.jsonlz4"], "it wrote there"
    assert rig.data_dir is not None and not rig.data_dir.exists(), "the throwaway was left behind"
    assert spec.args[0].startswith("http://127.0.0.1:")


def test_the_throwaway_runs_the_profiles_prefs_but_keeps_no_session(rig, profile):
    rig.running = {paths.gateway_name(profile.id): True}
    probe.probe(profile)
    assert 'user_pref("network.proxy.socks_port", 1080);' in rig.user_js
    assert 'user_pref("browser.startup.page", 0);' in rig.user_js
    assert 'user_pref("browser.sessionstore.resume_from_crash", false);' in rig.user_js


def test_a_gateway_it_started_is_torn_down_again(rig, profile):
    gateway = paths.gateway_name(profile.id)
    probe.probe(profile)
    assert rig.gateways_started == [profile.id]
    assert gateway in rig.removed
    assert f"secret:{launch.creds_secret_name(profile.id)}" in rig.removed


def test_but_not_if_the_user_launched_the_profile_meanwhile(rig, profile, monkeypatch):
    gateway, browser = paths.gateway_name(profile.id), paths.browser_name(profile.id)
    original = podman.start

    def start(spec, **k):
        rig.running[browser] = True  # the user clicks Launch while the probe runs
        return original(spec, **k)

    monkeypatch.setattr(podman, "start", start)
    probe.probe(profile)
    assert gateway not in rig.removed and browser not in rig.removed


def test_failure_still_cleans_up(rig, profile):
    rig.running = {paths.gateway_name(profile.id): True}
    rig.reports = False
    with pytest.raises(probe.ProbeError, match="never reported back"):
        probe.probe(profile, timeout=0)
    assert rig.removed[-1] == f"kf-probe-{profile.id[:8]}"
    assert rig.data_dir is not None and not rig.data_dir.exists()


def _config(spec) -> dict:
    env = spec.env
    return json.loads(
        "".join(
            env[f"CAMOU_CONFIG_{i + 1}"] for i in range(len(env)) if f"CAMOU_CONFIG_{i + 1}" in env
        )
    )


def test_a_normal_probe_reads_the_spoof_so_it_teaches_nothing_about_the_host(rig, profile):
    rig.running = {paths.gateway_name(profile.id): True}
    probe.probe(profile.model_copy(update={"webgl": "host"}))
    assert any(k.startswith("webGl") for k in _config(rig.started[0]))
    assert webgl.measured_host_renderer() is None
    assert w11.host_window_height() == 1092  # the real window is real in every mode


def test_a_raw_probe_measures_the_machine(rig, profile):
    rig.running = {paths.gateway_name(profile.id): True}
    probe.probe(profile.model_copy(update={"webgl": "host"}), raw=True)
    assert not any(k.startswith("webGl") for k in _config(rig.started[0]))
    assert webgl.measured_host_renderer() == HOST_RENDERER
    series, how = webgl.host_series()
    assert (series.key, how) == ("radeon-r9-200", "measured")


def test_the_probe_page_ships_inside_the_package():
    # install.sh copies only the package; a page kept under tests/ was missing
    # from every installed copy.
    page = probe._page()
    assert page.parent == Path(probe.__file__).parent
    text = page.read_text()
    assert "enumerateDevices" in text and "/report?" in text


# ------------------------------------------------------------------- the audit
GOOD_GL = {
    "available": True,
    "vendor": "Mozilla",
    "renderer": "ANGLE (AMD, Radeon R9 200 Series Direct3D11 vs_5_0 ps_5_0), or similar",
    "unmaskedRenderer": "ANGLE (AMD, Radeon R9 200 Series Direct3D11 vs_5_0 ps_5_0), or similar",
    "nonWindowsExtensions": [],
}
GOOD = {
    "webgl": GOOD_GL,
    "webgl2": GOOD_GL,
    "window": {"inner": [1280, 985]},
    "screen": {"availHeight": 1392},
    "speech": ["Microsoft Hedda - German (Germany)"],
    "media": {"devices": {"audioinput": 1}},
    "webgpu": {"available": False},
    "navigator": {
        "userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0"
    },
}


def test_audit_passes_a_coherent_report(profile):
    assert probe.audit(GOOD, profile) == []


def test_audit_catches_what_the_first_design_shipped(profile):
    # Measured on a real profile before the rework: the masked value was the Linux
    # host's, the unmasked one a string only Chrome produces, and no voices.
    before = {
        **GOOD,
        "webgl": {
            **GOOD_GL,
            "renderer": "Radeon R9 200 Series, or similar",
            "unmaskedRenderer": "ANGLE (AMD, AMD Radeon(TM) Graphics (0x00001638) Direct3D11 "
            "vs_5_0 ps_5_0, D3D11-31.0.21921.1000)",
            "nonWindowsExtensions": ["EXT_depth_clamp"],
        },
        "speech": [],
        "window": {"inner": [1280, 955]},
        "screen": {"availHeight": 816},
    }
    problems = "\n".join(probe.audit(before, profile))
    for expected in (
        "differs from the unmasked",
        "EXT_depth_clamp",
        "no voices",
        "innerHeight 955",
    ):
        assert expected in problems, problems


def test_audit_respects_the_modes_that_deviate_on_purpose(profile):
    off = profile.model_copy(update={"webgl": "off"})
    no_gl = {**GOOD, "webgl": {"available": False}, "webgl2": {"available": False}}
    assert probe.audit(no_gl, off) == []
    assert any("no context" in p for p in probe.audit(no_gl, profile))
    assert any("although the profile turns it off" in p for p in probe.audit(GOOD, off))
