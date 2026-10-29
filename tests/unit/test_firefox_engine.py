"""The stock Firefox engine and its signed-tarball fetcher.

No fingerprint, no CAMOU_CONFIG, no per-profile fontconfig: a firefox profile is
this machine's own Firefox. These tests pin the prefs it does set (proxy/leak,
WebRTC confinement, no spoofing), the container spec, and the verifier logic.
"""

from __future__ import annotations

import datetime as dt
import subprocess
import tempfile
from pathlib import Path

import pytest
from kiwi_proxy import podman

from kiwi_fox.core.engines import firefox_fetch, get_engine
from kiwi_fox.core.engines.firefox import Firefox
from kiwi_fox.core.models import Endpoint, Profile


@pytest.fixture
def ff_profile():
    return Profile(
        id="ffffffff-2222-3333-4444-555555555555",
        name="plain",
        created=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        engine="firefox",
        engine_version="159.0",
        endpoint=Endpoint(host="10.64.0.1", port=1080),
    )


def _install_fake(engine_dir: Path):
    engine_dir.mkdir(parents=True, exist_ok=True)
    (engine_dir / "firefox").write_text("#!/bin/sh\n")
    (engine_dir / "firefox").chmod(0o755)


# --------------------------------------------------------------------- prefs
def test_prefs_carry_the_proxy_and_leak_block(ff_profile):
    prefs = Firefox().prefs(None, ff_profile)
    assert prefs["network.proxy.type"] == 1
    assert prefs["network.proxy.socks"] == "127.0.0.1"
    assert prefs["network.proxy.socks_port"] == 1080
    assert prefs["network.proxy.failover_direct"] is False
    assert prefs["network.trr.mode"] == 5


def test_prefs_confine_webrtc(ff_profile):
    prefs = Firefox().prefs(None, ff_profile)
    assert prefs["media.peerconnection.ice.no_host"] is True
    assert prefs["media.peerconnection.ice.default_address_only"] is True
    assert prefs["media.peerconnection.ice.proxy_only_if_behind_proxy"] is True


def test_prefs_spoof_nothing(ff_profile):
    prefs = Firefox().prefs(None, ff_profile)
    # None of camoufox's Windows-claim or spoof keys may appear.
    for leak in (
        "privacy.resistFingerprinting",
        "webgl.force-enabled",
        "webgl.override-unmasked-vendor",
        "intl.locale.requested",
        "browser.uiCustomization.state",
        "xpinstall.signatures.required",
        "general.useragent.override",
    ):
        assert leak not in prefs, leak


def test_config_is_empty(ff_profile):
    assert Firefox().config(None, ff_profile, exit_ip="203.0.113.9") == {}


def test_remote_dns_follows_the_profile(ff_profile):
    assert Firefox().prefs(None, ff_profile)["network.proxy.socks_remote_dns"] is False
    ff_profile.dns.mode = "remote"
    assert Firefox().prefs(None, ff_profile)["network.proxy.socks_remote_dns"] is True


# ----------------------------------------------------------------------- env
def test_env_names_the_firefox_binary_and_no_camou_config(ff_profile):
    env = Firefox().env(ff_profile)
    assert env["KF_ENGINE_BIN"] == "firefox"
    assert env["KF_ENGINE_DIR"] == "/opt/firefox"
    assert env["FONTCONFIG_FILE"] == "/etc/kf-firefox-fonts.conf"
    assert not any(k.startswith("CAMOU_CONFIG") for k in env)


# ---------------------------------------------------------------------- spec
def test_build_spec_matches_the_hardened_shape(ff_profile, tmp_path, monkeypatch):
    monkeypatch.setattr(firefox_fetch, "target_dir", lambda v: tmp_path / f"firefox-{v}")
    _install_fake(tmp_path / "firefox-159.0")
    spec = Firefox().build_spec(ff_profile, None, gateway="kf-gw", exit_ip=None)
    assert spec.network == "container:kf-gw"
    assert spec.cap_drop == ["all"]
    assert spec.cap_add == ["SYS_CHROOT"]
    assert "no-new-privileges" in spec.security_opt
    assert spec.userns == "keep-id"
    mounts = {dst: opts for _src, dst, opts in spec.volumes}
    assert mounts["/opt/firefox"] == "ro,z"
    assert mounts["/profile"] == "rw,z"
    # No per-profile fontconfig mount: Firefox uses the image's static one.
    assert "/etc/kf-firefox-fonts.conf" not in mounts


def test_rendered_podman_args_are_stable(ff_profile, tmp_path, monkeypatch):
    monkeypatch.setattr(firefox_fetch, "target_dir", lambda v: tmp_path / f"firefox-{v}")
    _install_fake(tmp_path / "firefox-159.0")
    spec = Firefox().build_spec(ff_profile, None, gateway="kf-gw", exit_ip=None)
    args = podman.spec_args(spec)
    assert "--cap-drop" in args and "all" in args
    assert "SYS_CHROOT" in args
    assert "container:kf-gw" in args


def test_engine_dir_needs_an_install(ff_profile, monkeypatch, tmp_path):
    monkeypatch.setattr(firefox_fetch, "latest_installed", lambda: None)
    ff_profile.engine_version = None
    with pytest.raises(RuntimeError, match="no Firefox engine"):
        Firefox().engine_dir(ff_profile, None)


# --------------------------------------------------------------- fetch layout
def test_target_dir_and_installed(monkeypatch, tmp_path):
    monkeypatch.setattr(firefox_fetch.paths, "engines_dir", lambda: tmp_path)
    assert firefox_fetch.target_dir("159.0") == tmp_path / "firefox-159.0"
    assert firefox_fetch.installed() == []
    _install_fake(tmp_path / "firefox-159.0")
    _install_fake(tmp_path / "firefox-153.6.0")
    # a langpacks sibling is never mistaken for an engine
    (tmp_path / "langpacks").mkdir()
    assert firefox_fetch.installed() == ["153.6.0", "159.0"]
    assert firefox_fetch.latest_installed() == "159.0"


def test_sha512_for_matches_on_basename():
    sums = "aa  linux-x86_64/en-US/firefox-159.0.tar.xz\nbb  win64/firefox-159.0.exe\n"
    assert firefox_fetch.sha512_for(sums, "firefox-159.0.tar.xz") == "aa"
    assert firefox_fetch.sha512_for(sums, "nope.tar.xz") is None


def test_policies_turn_off_updates(tmp_path):
    path = firefox_fetch.write_policies(tmp_path)
    import json

    pol = json.loads(path.read_text())["policies"]
    assert pol["DisableAppUpdate"] is True
    assert pol["DisableTelemetry"] is True
    assert pol["OverrideFirstRunPage"] == ""


# --------------------------------------------------- end-to-end verify helpers
@pytest.mark.skipif(
    not firefox_fetch.shutil.which("gpg") or not firefox_fetch.shutil.which("gpgv"),
    reason="gpg/gpgv not available",
)
def test_signature_verification_roundtrip():
    """A key we generate signs a SHA512SUMS; our helpers accept it, reject a
    tamper, and the fingerprint matches gpg's own."""
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        home = work / "gnupg"
        home.mkdir(mode=0o700)
        env = {"GNUPGHOME": str(home)}
        subprocess.run(
            [
                "gpg",
                "--batch",
                "--pinentry-mode",
                "loopback",
                "--passphrase",
                "",
                "--quick-generate-key",
                "kiwi-fox test <t@example.com>",
                "rsa2048",
                "sign",
                "0",
            ],
            env=env,
            check=True,
            capture_output=True,
        )
        key = subprocess.run(["gpg", "--armor", "--export"], env=env, capture_output=True).stdout
        real_fp = next(
            line.split(":")[9]
            for line in subprocess.run(
                ["gpg", "--with-colons", "--fingerprint"], env=env, capture_output=True
            )
            .stdout.decode()
            .splitlines()
            if line.startswith("fpr")
        )
        assert firefox_fetch.key_fingerprint(key) == real_fp

        sums = work / "SHA512SUMS"
        sums.write_text("deadbeef  linux-x86_64/en-US/firefox-1.0.tar.xz\n")
        subprocess.run(
            [
                "gpg",
                "--batch",
                "--yes",
                "--armor",
                "--detach-sign",
                "--output",
                str(work / "SHA512SUMS.asc"),
                str(sums),
            ],
            env=env,
            check=True,
            capture_output=True,
        )
        keyring = work / "kr.gpg"
        firefox_fetch._keyring_from(key, keyring)
        assert firefox_fetch.gpgv_ok(keyring, work / "SHA512SUMS.asc", sums)
        sums.write_text("tampered  x\n")
        assert not firefox_fetch.gpgv_ok(keyring, work / "SHA512SUMS.asc", sums)


# -------------------------------------------------------------- end to end wiring
def test_get_engine_returns_firefox():
    assert isinstance(get_engine("firefox"), Firefox)
