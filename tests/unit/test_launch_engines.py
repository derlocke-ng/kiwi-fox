"""launch() dispatches by engine: a firefox profile needs no fingerprint and
skips every camoufox-only prep step, while still wiring the gateway, the
credentials and the browser the same way.
"""

from __future__ import annotations

import pytest

from kiwi_fox.core import launch, store
from kiwi_fox.core.engines import firefox_fetch
from kiwi_fox.core.models import Endpoint


@pytest.fixture
def podman_stub(fake_proxy, monkeypatch):
    # No Wayland socket hunt.
    monkeypatch.setattr(launch, "_wayland_mount", lambda: None)
    from kiwi_fox.core import gpu

    # A non-None measurement skips the measure-container path in launch().
    monkeypatch.setattr(gpu, "measurement", lambda: {"accelerated": True})
    return fake_proxy


def _spy(monkeypatch, name):
    calls: list[int] = []
    real = getattr(launch, name)

    def wrapper(*a, **k):
        calls.append(1)
        return real(*a, **k)

    monkeypatch.setattr(launch, name, wrapper)
    return calls


def test_firefox_launch_skips_camoufox_prep(podman_stub, monkeypatch, tmp_path):
    # An installed firefox engine, and no fingerprint anywhere.
    monkeypatch.setattr(firefox_fetch, "target_dir", lambda v: tmp_path / f"firefox-{v}")
    eng = tmp_path / "firefox-159.0"
    eng.mkdir(parents=True)
    (eng / "firefox").write_text("#!/bin/sh\n")
    (eng / "firefox").chmod(0o755)

    fontconfig = _spy(monkeypatch, "write_fontconfig")
    userchrome = _spy(monkeypatch, "write_user_chrome")
    langpack = _spy(monkeypatch, "install_langpack")

    p = store.create(
        "plain",
        Endpoint(host="10.64.0.1", port=1080),
        None,
        engine="firefox",
        engine_version="159.0",
    )
    result = launch.launch(p)

    assert result.browser == launch.paths.browser_name(p.id)
    assert not fontconfig and not userchrome and not langpack
    # The user.js was written from the firefox prefs (proxy present, no CAMOU).
    user_js = (launch.browser_data_dir(p) / "user.js").read_text()
    assert "network.proxy.socks" in user_js
    assert "resistFingerprinting" not in user_js
    assert "CAMOU_CONFIG" not in user_js


def test_firefox_missing_engine_is_a_launch_error(podman_stub, monkeypatch):
    monkeypatch.setattr(firefox_fetch, "latest_installed", lambda: None)
    p = store.create("plain", Endpoint(host="10.64.0.1", port=1080), None, engine="firefox")
    with pytest.raises((launch.LaunchError, RuntimeError)):
        launch.launch(p)


def test_firefox_browser_data_mount_is_present(podman_stub, monkeypatch, tmp_path):
    monkeypatch.setattr(firefox_fetch, "target_dir", lambda v: tmp_path / f"firefox-{v}")
    eng = tmp_path / "firefox-159.0"
    eng.mkdir(parents=True)
    (eng / "firefox").write_text("x")
    (eng / "firefox").chmod(0o755)
    p = store.create(
        "plain",
        Endpoint(host="10.64.0.1", port=1080),
        None,
        engine="firefox",
        engine_version="159.0",
    )
    launch.launch(p)
    (br,) = podman_stub.started
    assert br.name == launch.paths.browser_name(p.id)
    mounts = {dst for _s, dst, _o in br.volumes}
    assert "/opt/firefox" in mounts
    assert "/profile" in mounts
