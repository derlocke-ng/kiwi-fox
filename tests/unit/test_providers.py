"""The provider plugin subsystem: discovery, loading, and the container lifecycle.

A provider module is a directory under modules_dir() holding a provider.py that
exposes PROVIDER and MANIFEST. These tests write fake modules into the (hermetic,
tmp) data dir and exercise the loader and ContainerProvider against a monkeypatched
podman, so nothing here needs a real podman or a real network.
"""

from __future__ import annotations

import datetime as dt

import pytest

from kiwi_fox.core import launch, paths, podman, providers
from kiwi_fox.core.models import Endpoint, Profile

# A minimal provider module, written to disk and loaded by file path. It imports
# the contract from kiwi_fox exactly as an installed plugin would.
MODULE_SRC = """
from kiwi_fox.core.models import ContainerSpec, Lease, ProviderManifest
from kiwi_fox.core.providers.base import ContainerProvider

MANIFEST = ProviderManifest(
    name="{name}",
    title="{title}",
    description="a fake provider for tests",
    socks_port={port},
    auth="{auth}",
)


class FakeProvider(ContainerProvider):
    manifest = MANIFEST

    def container_spec(self, ctx, *, lease=None, country=None):
        return ContainerSpec(
            name=ctx.container_name(lease),
            image=ctx.image,
            network=ctx.network,
            labels={{"kiwi-fox.module": self.name, "kiwi-fox.role": "provider"}},
        )

    def leases(self, ctx):
        return [Lease(id="de", country="DE", city="Berlin"), Lease(id="se", country="SE")]


PROVIDER = FakeProvider()
"""


def install_module(name="faketor", *, title="Fake Tor", port=9050, auth="isolation") -> None:
    mdir = paths.module_dir(name)
    mdir.mkdir(parents=True, exist_ok=True)
    (mdir / "provider.py").write_text(
        MODULE_SRC.format(name=name, title=title, port=port, auth=auth)
    )


@pytest.fixture
def fake_module():
    install_module()
    return "faketor"


# --------------------------------------------------------------------- discovery
def test_discover_lists_installed_modules(fake_module):
    install_module("vpn", title="VPN", port=1080, auth="none")
    assert providers.discover() == ["faketor", "vpn"]


def test_discover_empty_when_nothing_installed():
    assert providers.discover() == []


def test_a_digit_named_module_loads_by_file_path():
    # "9proxy" is not a legal Python import name; the loader must load by path.
    install_module("9proxy", title="9proxy", port=1080, auth="account")
    provider, manifest = providers.load("9proxy")
    assert manifest.name == "9proxy"
    assert provider.name == "9proxy"


def test_is_installed(fake_module):
    assert providers.is_installed("faketor")
    assert not providers.is_installed("nope")


def test_manages_only_installed_container_providers(fake_module):
    assert providers.manages("faketor") is True
    assert providers.manages("nope") is False
    assert providers.manages(None) is False


# ----------------------------------------------------------------------- loading
def test_load_returns_provider_and_manifest(fake_module):
    provider, manifest = providers.load("faketor")
    assert manifest.name == "faketor"
    assert manifest.socks_port == 9050
    assert isinstance(provider, providers.Provider)


def test_load_rejects_name_mismatch():
    mdir = paths.module_dir("mislabelled")
    mdir.mkdir(parents=True, exist_ok=True)
    (mdir / "provider.py").write_text(
        MODULE_SRC.format(name="other", title="x", port=1, auth="none")
    )
    with pytest.raises(providers.ProviderError, match="does not match manifest"):
        providers.load("mislabelled")


def test_load_rejects_missing_provider():
    mdir = paths.module_dir("empty")
    mdir.mkdir(parents=True, exist_ok=True)
    (mdir / "provider.py").write_text("MANIFEST = None\n")
    with pytest.raises(providers.ProviderError):
        providers.load("empty")


def test_load_missing_module_raises():
    with pytest.raises(providers.ProviderError, match="not installed"):
        providers.load("ghost")


def test_context_for_uses_shared_network_and_derived_image(fake_module):
    ctx = providers.context_for("faketor")
    assert ctx.network == paths.PROVIDERS_NETWORK
    assert ctx.image == "kiwi-fox/faketor:latest"
    assert ctx.socks_port == 9050
    assert ctx.module_dir == paths.module_dir("faketor")


# ------------------------------------------------------------------- lifecycle
def _stub_podman(monkeypatch, *, running=True, ip="10.89.0.7", calls=None):
    calls = calls if calls is not None else {}
    monkeypatch.setattr(podman, "available", lambda: True)
    monkeypatch.setattr(podman, "network_ensure", lambda name: calls.__setitem__("net", name))
    monkeypatch.setattr(
        podman, "start", lambda spec, **k: calls.__setitem__("started", spec.name) or "cid"
    )
    monkeypatch.setattr(podman, "is_running", lambda name: running)
    monkeypatch.setattr(podman, "container_ip", lambda name, net: ip)
    monkeypatch.setattr(podman, "logs", lambda name, tail=50: "boom")


def test_up_returns_live_socks_endpoint(fake_module, monkeypatch):
    calls: dict[str, str] = {}
    _stub_podman(monkeypatch, running=True, ip="10.89.0.7", calls=calls)
    provider, manifest = providers.load("faketor")
    ctx = providers.context_for("faketor", manifest)
    endpoint = provider.up(ctx, lease="de")
    assert endpoint.host == "10.89.0.7"
    assert endpoint.port == 9050
    assert endpoint.module == "faketor"
    assert endpoint.lease == "de"
    assert calls["net"] == paths.PROVIDERS_NETWORK


def test_up_fails_when_container_exits(fake_module, monkeypatch):
    _stub_podman(monkeypatch, running=False)
    provider, manifest = providers.load("faketor")
    ctx = providers.context_for("faketor", manifest)
    with pytest.raises(providers.ProviderError, match="exited during start"):
        provider.up(ctx, lease="de")


def test_up_times_out_without_an_address(fake_module, monkeypatch):
    _stub_podman(monkeypatch, running=True, ip=None)
    provider, manifest = providers.load("faketor")
    provider.ready_timeout = 0.3
    ctx = providers.context_for("faketor", manifest)
    with pytest.raises(providers.ProviderError, match="did not become ready"):
        provider.up(ctx, lease="de")


def test_up_rejects_a_spec_on_the_wrong_network(fake_module, monkeypatch):
    _stub_podman(monkeypatch, running=True)
    provider, manifest = providers.load("faketor")
    ctx = providers.context_for("faketor", manifest)
    orig = provider.container_spec

    def bad_spec(c, **k):
        spec = orig(c, **k)
        spec.network = "pasta"  # a provider must attach to the providers bridge
        return spec

    monkeypatch.setattr(provider, "container_spec", bad_spec)
    with pytest.raises(providers.ProviderError, match="must attach to"):
        provider.up(ctx, lease="de")


def test_down_removes_the_provider_container(fake_module, monkeypatch):
    removed: list[str] = []
    monkeypatch.setattr(podman, "rm", lambda name, **k: removed.append(name))
    provider, manifest = providers.load("faketor")
    ctx = providers.context_for("faketor", manifest)
    provider.down(ctx, lease="de")
    assert removed == [paths.provider_container_name("faketor", "de")]


def test_leases_listed(fake_module):
    provider, manifest = providers.load("faketor")
    ctx = providers.context_for("faketor", manifest)
    assert [lease.id for lease in provider.leases(ctx)] == ["de", "se"]


# --------------------------------------------------------------- naming + spec
def test_provider_container_name_is_keyed_on_module_and_lease():
    assert paths.provider_container_name("tor") == "kf-prov-tor"
    assert paths.provider_container_name("9proxy", "40001") == "kf-prov-9proxy-40001"
    # separators that are illegal in container names are flattened
    assert "/" not in paths.provider_container_name("vpn", "nl/amsterdam")


def test_providers_network_name():
    assert paths.PROVIDERS_NETWORK == "kf-providers"


def test_rendered_provider_spec_attaches_to_the_bridge(fake_module):
    provider, manifest = providers.load("faketor")
    ctx = providers.context_for("faketor", manifest)
    spec = provider.container_spec(ctx, lease="de")
    args = podman.spec_args(spec)
    assert args[:2] == ["run", "--replace"]
    assert "--network" in args and paths.PROVIDERS_NETWORK in args
    assert spec.image == "kiwi-fox/faketor:latest"
    assert "--privileged" not in args


# -------------------------------------------------------------- launch wiring
def _profile(module=None, lease=None, port=1080):
    return Profile(
        id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        name="work",
        created=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        endpoint=Endpoint(host="10.64.0.1", port=port, module=module, lease=lease),
    )


def test_gateway_spec_stays_on_pasta_for_a_plain_endpoint():
    spec = launch.gateway_spec(_profile(), "203.0.113.9")
    assert spec.network == "pasta"
    assert spec.env["KF_ENDPOINT_IP"] == "203.0.113.9"
    assert spec.env["KF_ENDPOINT_PORT"] == "1080"


def test_gateway_spec_joins_the_bridge_for_a_local_provider():
    spec = launch.gateway_spec(
        _profile(module="faketor", lease="de", port=9050),
        "10.89.0.7",
        endpoint_port=9050,
        network=paths.PROVIDERS_NETWORK,
    )
    assert spec.network == paths.PROVIDERS_NETWORK
    assert spec.env["KF_ENDPOINT_IP"] == "10.89.0.7"
    assert spec.env["KF_ENDPOINT_PORT"] == "9050"
    # the gateway label survives, so kiwi-pentesting can still discover it
    assert spec.labels["app"] == "kiwi-fox"
    assert spec.labels["kiwi-fox.role"] == "gateway"


def test_isolation_provider_gets_a_stable_per_profile_token(fake_module, monkeypatch):
    stored: dict[str, str] = {}
    monkeypatch.setattr(podman, "secret_set", lambda name, value: stored.update(value=value))
    monkeypatch.setattr(launch.secrets, "lookup", lambda pid: None)
    profile = _profile(module="faketor", lease="de", port=9050)
    launch.write_credentials(profile)
    user, password, _ = stored["value"].split("\n")
    assert user == f"kf-{profile.id[:16]}"
    assert password == profile.id


def test_plain_endpoint_credentials_are_whatever_the_user_gave(monkeypatch):
    stored: dict[str, str] = {}
    monkeypatch.setattr(podman, "secret_set", lambda name, value: stored.update(value=value))
    monkeypatch.setattr(launch.secrets, "lookup", lambda pid: "topsecret")
    profile = _profile()
    profile.endpoint.username = "u"
    launch.write_credentials(profile)
    assert stored["value"] == "u\ntopsecret\n"


def test_preflight_brings_up_a_managed_provider(fake_module, monkeypatch):
    _stub_podman(monkeypatch, running=True, ip="10.89.0.9")
    profile = _profile(module="faketor", lease="de", port=9050)
    plan = launch.preflight(profile)
    assert plan.ip == "10.89.0.9"
    assert plan.port == 9050
    assert plan.network == paths.PROVIDERS_NETWORK
    assert plan.info is None  # a local bridge exit is measured later, through the gateway


def test_release_provider_waits_until_no_gateway_uses_it(fake_module, monkeypatch):
    removed: list[str] = []
    monkeypatch.setattr(podman, "rm", lambda name, **k: removed.append(name))

    # No other profile is running, so the provider container is torn down.
    monkeypatch.setattr(launch, "_provider_users", lambda module, lease, *, exclude_id: 0)
    launch.release_provider(_profile(module="faketor", lease="de"))
    assert removed == [paths.provider_container_name("faketor", "de")]

    # Another profile still uses it: it is left running.
    removed.clear()
    monkeypatch.setattr(launch, "_provider_users", lambda module, lease, *, exclude_id: 1)
    launch.release_provider(_profile(module="faketor", lease="de"))
    assert removed == []


def test_release_is_a_noop_for_a_plain_endpoint(monkeypatch):
    # Should not even look at providers for a plain socks5 profile.
    launch.release_provider(_profile())  # must not raise


# ---------------------------------------------------------------- podman helpers
def test_container_ip_returns_none_when_not_running(monkeypatch):
    monkeypatch.setattr(podman, "is_running", lambda name: False)
    assert podman.container_ip("x", "kf-providers") is None
