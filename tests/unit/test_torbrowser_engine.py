"""The Tor Browser engine: no spoofing, proxy-only (TOR_PROVIDER=none), DNS
forced remote, the tor module required, and its exit in passthrough mode."""

from __future__ import annotations

import datetime as dt
import io
import os
import subprocess
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from kiwi_proxy import exits, gateway, podman, providers

from kiwi_fox.core import launch, store
from kiwi_fox.core.engines import get_engine, torbrowser_fetch
from kiwi_fox.core.engines.torbrowser import TorBrowser
from kiwi_fox.core.models import Endpoint, Profile


def _tb_profile(**kw):
    return Profile(
        id="aaaaaaaa-2222-3333-4444-555555555555",
        name="tor",
        created=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        engine="torbrowser",
        engine_version="15.0.26",
        endpoint=Endpoint(host="10.89.231.5", port=9050, module="tor"),
        **kw,
    )


def _install_fake_tb(engine_dir: Path):
    binp = engine_dir / "Browser" / "firefox"
    binp.parent.mkdir(parents=True, exist_ok=True)
    binp.write_text("#!/bin/sh\n")
    binp.chmod(0o755)


# ---------------------------------------------------------------------- engine
def test_env_disables_bundled_tor_and_points_at_the_forwarder():
    env = TorBrowser().env(_tb_profile())
    assert env["TOR_PROVIDER"] == "none"
    assert env["TOR_SOCKS_HOST"] == "127.0.0.1"
    assert env["TOR_SOCKS_PORT"] == "1080"
    assert env["KF_ENGINE_BIN"] == "Browser/firefox"
    assert env["KF_TORBROWSER"] == "1"
    assert not any(k.startswith("CAMOU_CONFIG") for k in env)
    # No FONTCONFIG_FILE: Tor Browser uses its own bundled fontconfig (the
    # entrypoint wires it), not a kiwi-fox one.
    assert "FONTCONFIG_FILE" not in env


def test_prefs_are_leak_only_and_remote_dns():
    prefs = TorBrowser().prefs(None, _tb_profile())
    assert prefs["network.proxy.socks"] == "127.0.0.1"
    assert prefs["network.proxy.socks_remote_dns"] is True  # forced, for .onion
    assert prefs["network.proxy.failover_direct"] is False
    # Nothing that would disturb Tor Browser's uniform fingerprint.
    for leak in ("privacy.resistFingerprinting", "webgl.force-enabled", "intl.locale.requested"):
        assert leak not in prefs


def test_prefs_force_remote_even_for_a_resolver_profile():
    p = _tb_profile()
    p.dns.mode = "resolver"
    assert TorBrowser().prefs(None, p)["network.proxy.socks_remote_dns"] is True


def test_build_spec_mounts_tor_browser_read_only(tmp_path, monkeypatch):
    monkeypatch.setattr(torbrowser_fetch, "target_dir", lambda v: tmp_path / f"torbrowser-{v}")
    _install_fake_tb(tmp_path / "torbrowser-15.0.26")
    spec = TorBrowser().build_spec(_tb_profile(), None, gateway="kf-gw", exit_ip=None)
    mounts = {dst: opts for _s, dst, opts in spec.volumes}
    assert mounts["/opt/torbrowser"] == "ro,z"
    assert mounts["/profile"] == "rw,z"
    assert spec.cap_add == ["SYS_CHROOT"]
    args = podman.spec_args(spec)
    assert "container:kf-gw" in args


def test_get_engine_returns_torbrowser():
    assert isinstance(get_engine("torbrowser"), TorBrowser)


# ------------------------------------------------------------------- fetch layout
def test_fetch_layout(monkeypatch, tmp_path):
    monkeypatch.setattr(torbrowser_fetch.paths, "engines_dir", lambda: tmp_path)
    assert torbrowser_fetch.target_dir("15.0.26") == tmp_path / "torbrowser-15.0.26"
    assert torbrowser_fetch.installed() == []
    _install_fake_tb(tmp_path / "torbrowser-15.0.26")
    _install_fake_tb(tmp_path / "torbrowser-16.0a14")
    assert torbrowser_fetch.latest_installed() == "16.0a14"  # alpha sorts after


def test_discover_refuses_below_the_floor(monkeypatch):
    # An explicit too-old version is refused outright (rollback guard).
    with pytest.raises(torbrowser_fetch.FetchError, match="floor"):
        torbrowser_fetch.discover("14.5.6")
    assert torbrowser_fetch.discover("15.0.26") == "15.0.26"


# -------------------------------------------------------------------- store rule
def test_create_torbrowser_requires_the_tor_module():
    with pytest.raises(store.StoreError, match="tor provider"):
        store.create(
            "bad",
            Endpoint(host="h", port=1080),
            None,
            engine="torbrowser",
            engine_version="15.0.26",
        )


def test_create_torbrowser_with_tor_module_works():
    p = store.create(
        "ok",
        Endpoint(host="10.89.231.5", port=9050, module="tor"),
        None,
        engine="torbrowser",
        engine_version="15.0.26",
    )
    assert p.engine == "torbrowser"
    assert store.fingerprint_of(p) is None


# ------------------------------------------------------------------- the exit
@pytest.fixture
def tor_module(monkeypatch):
    """A managed tor provider with isolation auth, as kiwi-plugin-tor declares."""

    class _Manifest:
        auth = "isolation"

    monkeypatch.setattr(providers, "manages", lambda m: m == "tor")
    monkeypatch.setattr(providers, "manifest_of", lambda m: _Manifest())


def _create_tb(name="tor"):
    return store.create(
        name,
        Endpoint(host="10.89.231.5", port=9050, module="tor"),
        None,
        engine="torbrowser",
        engine_version="15.0.26",
    )


def test_its_exit_passes_auth_through_and_resolves_remotely():
    p = _create_tb()
    ex = exits.load(p.id)
    assert ex.socks_auth == "passthrough"
    assert ex.dns.mode == "remote"
    assert p.dns.mode == "remote"


def test_a_resolver_set_on_its_exit_does_not_stick():
    p = _create_tb()
    ex = exits.load(p.id)
    ex.dns.mode = "resolver"
    ex.socks_auth = "inject"
    exits.save(ex)  # `kiwi-proxy set tor --dns resolver --socks-auth inject`
    store.save(store.load(p.id))
    ex = exits.load(p.id)
    assert (ex.dns.mode, ex.socks_auth) == ("remote", "passthrough")


def test_kiwi_proxy_builds_the_passthrough_gateway_from_it(tor_module):
    # The real gateway spec, from kiwi-proxy, for the exit kiwi-fox registered.
    p = _create_tb()
    ex = exits.load(p.id)
    spec = gateway.gateway_spec(ex, "10.89.231.5", endpoint_port=9050, network="kf-providers")
    assert spec.env["KF_SOCKS_AUTH"] == "passthrough"
    assert spec.env["KF_DNS_MODE"] == "remote"
    assert not any(dst == "/run/kf/dnscrypt-proxy.toml" for _s, dst, _o in spec.volumes)
    # The isolation token is the one kiwi-fox always minted: same circuit as before.
    assert gateway.credentials(ex, None) == (f"kf-{p.id[:16]}", p.id)


# ------------------------------------------------------------------- launch wiring
@pytest.fixture
def tb_installed(fake_proxy, tor_module, monkeypatch, tmp_path):
    monkeypatch.setattr(torbrowser_fetch, "target_dir", lambda v: tmp_path / f"torbrowser-{v}")
    _install_fake_tb(tmp_path / "torbrowser-15.0.26")
    monkeypatch.setattr(launch, "_wayland_mount", lambda: None)
    from kiwi_fox.core import gpu

    monkeypatch.setattr(gpu, "measurement", lambda: {"accelerated": True})
    return fake_proxy


def test_launch_brings_up_the_passthrough_exit(tb_installed):
    p = _create_tb()
    launch.launch(p)
    (up,) = tb_installed.ups
    assert up.exit.id == p.id
    assert (up.exit.socks_auth, up.exit.dns.mode) == ("passthrough", "remote")
    (br,) = tb_installed.started
    # No resolver in the namespace, so nothing to point the browser at.
    assert all(dst != "/etc/resolv.conf" for _s, dst, _o in br.volumes)
    assert br.env["TOR_PROVIDER"] == "none"


def test_launch_refuses_a_non_tor_endpoint(tb_installed):
    # Force an invalid profile past the create guard to prove launch also refuses.
    p = _create_tb()
    p.endpoint.module = None
    store.save(p)
    with pytest.raises(launch.LaunchError, match="tor provider"):
        launch.launch(store.load(p.id))
    assert tb_installed.plans == [], "refused before anything was sent"


def test_launch_refuses_a_tor_module_without_isolation(tb_installed, monkeypatch):
    class _Account:
        auth = "account"

    monkeypatch.setattr(providers, "manifest_of", lambda m: _Account())
    with pytest.raises(launch.LaunchError, match="isolation"):
        launch.launch(_create_tb())


# ------------------------------------------------------------------ fetch, end to end
needs_gpg = pytest.mark.skipif(
    not torbrowser_fetch.shutil.which("gpg") or not torbrowser_fetch.shutil.which("gpgv"),
    reason="gpg/gpgv not available",
)


@pytest.fixture
def signer(tmp_path):
    """A throwaway signing key standing in for the Tor Browser Developers key."""
    home = tmp_path / "gnupg"
    home.mkdir(mode=0o700)
    env = {"GNUPGHOME": str(home), "PATH": os.environ.get("PATH", "/usr/bin:/bin")}

    def gpg(*args, **kw):
        return subprocess.run(
            ["gpg", "--batch", *args], env=env, check=True, capture_output=True, **kw
        )

    gpg("--pinentry-mode", "loopback", "--passphrase", "", "--quick-generate-key",
        "tb test <t@example.com>", "rsa2048", "sign", "0")  # fmt: skip
    key = gpg("--armor", "--export").stdout
    fpr = next(
        line.split(":")[9]
        for line in gpg("--with-colons", "--fingerprint").stdout.decode().splitlines()
        if line.startswith("fpr")
    )

    def sign(data: bytes) -> bytes:
        blob = tmp_path / "blob"
        blob.write_bytes(data)
        return gpg("--armor", "--detach-sign", "--output", "-", str(blob)).stdout

    return SimpleNamespace(key=key, fpr=fpr, sign=sign)


def _bundle_bytes(tmp_path) -> bytes:
    browser = tmp_path / "src" / "tor-browser" / "Browser"
    browser.mkdir(parents=True)
    (browser / "firefox").write_text("#!/bin/sh\n")
    (browser / "firefox").chmod(0o755)
    tar = tmp_path / "bundle.tar.xz"
    with tarfile.open(tar, "w:xz") as tf:
        tf.add(browser.parent, arcname="tor-browser")
    return tar.read_bytes()


def _serve(monkeypatch, *, key: bytes, tarball: bytes, asc: bytes) -> None:
    def get(url, timeout=60):
        if url == torbrowser_fetch.WKD_KEY:
            return key
        assert url.endswith(".tar.xz.asc"), url
        return asc

    class Response(io.BytesIO):
        headers = {"Content-Length": str(len(tarball))}

    monkeypatch.setattr(torbrowser_fetch, "_get", get)
    monkeypatch.setattr(
        torbrowser_fetch.urllib.request, "urlopen", lambda url, timeout=0: Response(tarball)
    )


@needs_gpg
def test_fetch_installs_a_verified_bundle_marked_packaged(signer, monkeypatch, tmp_path):
    tarball = _bundle_bytes(tmp_path)
    monkeypatch.setattr(torbrowser_fetch, "TBB_KEY_FINGERPRINT", signer.fpr)
    _serve(monkeypatch, key=signer.key, tarball=tarball, asc=signer.sign(tarball))

    dest = torbrowser_fetch.fetch("15.0.26")

    assert dest == torbrowser_fetch.target_dir("15.0.26")
    assert (dest / "Browser" / "firefox").exists()
    assert (dest / "Browser" / "is-packaged-app").exists()  # off the read-only mount
    assert (dest / ".version").read_text() == "15.0.26\n"
    assert torbrowser_fetch.installed() == ["15.0.26"]


@needs_gpg
def test_fetch_refuses_a_tarball_the_signature_does_not_cover(signer, monkeypatch, tmp_path):
    tarball = _bundle_bytes(tmp_path)
    monkeypatch.setattr(torbrowser_fetch, "TBB_KEY_FINGERPRINT", signer.fpr)
    _serve(monkeypatch, key=signer.key, tarball=tarball + b"\0", asc=signer.sign(tarball))

    with pytest.raises(torbrowser_fetch.FetchError, match="did not verify"):
        torbrowser_fetch.fetch("15.0.26")
    assert torbrowser_fetch.installed() == []
    # Nothing trusted-looking is left in the cache either.
    assert not list(torbrowser_fetch.paths.cache_dir().glob("tor-browser-*"))


@needs_gpg
def test_fetch_refuses_a_key_that_is_not_the_pinned_one(signer, monkeypatch, tmp_path):
    tarball = _bundle_bytes(tmp_path)
    _serve(monkeypatch, key=signer.key, tarball=tarball, asc=signer.sign(tarball))

    with pytest.raises(torbrowser_fetch.FetchError, match="not the pinned"):
        torbrowser_fetch.fetch("15.0.26")
    assert torbrowser_fetch.installed() == []
