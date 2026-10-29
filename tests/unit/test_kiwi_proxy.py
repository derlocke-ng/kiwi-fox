"""kiwi-fox as a kiwi-proxy consumer: one exit per profile, under the profile's
own id, and what launch asks of the gateway.

kiwi-proxy's own tests cover what a gateway does; these pin what kiwi-fox
promises across the split — the names and tokens a host already has stay what
they were, edits on either side meet, and a closing window only releases.
"""

from __future__ import annotations

import pytest
from kiwi_proxy import exits, gateway, providers
from kiwi_proxy import paths as proxy_paths

from kiwi_fox.core import launch, paths, secrets, store
from kiwi_fox.core.engines import firefox_fetch
from kiwi_fox.core.models import DnsConfig, Endpoint


def _endpoint(**kw):
    return Endpoint(host="10.64.0.1", port=1080, **kw)


def _firefox(name="plain", **kw):
    return store.create(name, _endpoint(), None, engine="firefox", engine_version="159.0", **kw)


@pytest.fixture
def firefox_installed(monkeypatch, tmp_path):
    monkeypatch.setattr(firefox_fetch, "target_dir", lambda v: tmp_path / f"firefox-{v}")
    eng = tmp_path / "firefox-159.0"
    eng.mkdir(parents=True)
    (eng / "firefox").write_text("#!/bin/sh\n")
    monkeypatch.setattr(launch, "_wayland_mount", lambda: None)
    from kiwi_fox.core import gpu

    monkeypatch.setattr(gpu, "measurement", lambda: {"accelerated": True})


# ------------------------------------------------------------------ the exit
def test_a_new_profile_registers_its_exit_under_its_own_id():
    p = _firefox()
    ex = exits.load(p.id)
    assert (ex.id, ex.name, ex.owner) == (p.id, p.name, "kiwi-fox")
    assert ex.endpoint == p.endpoint and ex.dns == p.dns
    assert ex.socks_auth == "inject"


def test_gateway_name_is_the_one_it_always_was():
    p = _firefox()
    assert paths.gateway_name(p.id) == f"kf-gw-{p.id[:12]}"
    assert proxy_paths.gateway_name(exits.load(p.id).id) == paths.gateway_name(p.id)


def test_a_cli_exit_with_the_name_is_a_clear_error():
    exits.create("work", _endpoint())
    with pytest.raises(store.StoreError, match="kiwi-proxy already has an exit named 'work'"):
        _firefox("work")


def test_save_writes_endpoint_and_dns_to_the_exit():
    p = _firefox()
    p.dns = DnsConfig(mode="remote")
    p.endpoint = Endpoint(host="198.51.100.7", port=9050)
    store.save(p)
    ex = exits.load(p.id)
    assert ex.dns.mode == "remote"
    assert (ex.endpoint.host, ex.endpoint.port) == ("198.51.100.7", 9050)


def test_an_edit_made_with_kiwi_proxy_is_what_kiwi_fox_loads():
    p = _firefox()
    ex = exits.load(p.id)
    ex.dns = DnsConfig(mode="remote")
    ex.endpoint = Endpoint(host="198.51.100.7", port=9050)
    exits.save(ex)  # what `kiwi-proxy set plain --dns remote …` does
    loaded = store.load(p.id)
    assert loaded.dns.mode == "remote"
    assert loaded.endpoint.host == "198.51.100.7"


def test_a_profile_from_before_kiwi_proxy_still_loads_and_gets_its_exit():
    p = _firefox()
    exits.delete(p.id)  # as if made by kiwi-fox 0.2
    assert store.load(p.id).endpoint == p.endpoint
    ex = store.sync_exit(store.load(p.id))
    assert ex.id == p.id and ex.name == p.name and ex.owner == "kiwi-fox"


def test_a_name_taken_meanwhile_is_kept_off_the_exit_not_refused():
    p = _firefox("work")
    exits.delete(p.id)
    exits.create("work", _endpoint())  # someone made one with the CLI since
    ex = store.sync_exit(p)
    assert ex.id == p.id and ex.name == f"work-{p.id[:8]}"
    store.save(p)  # and saving again neither fails nor fights over the name
    assert exits.load(p.id).name == f"work-{p.id[:8]}"


def test_renaming_the_profile_renames_its_exit():
    p = _firefox("old")
    p.name = "new"
    store.save(p)
    assert exits.load(p.id).name == "new"


def test_delete_removes_the_exit():
    p = _firefox()
    store.delete(p.id, purge=True)
    assert not exits.exists(p.id)


# ------------------------------------------------------------------ launching
def test_launch_hands_kiwi_proxy_the_exit_the_keyring_password_and_its_labels(
    fake_proxy, firefox_installed, monkeypatch
):
    p = _firefox()
    monkeypatch.setattr(secrets, "lookup", lambda pid: "s3cret" if pid == p.id else None)
    result = launch.launch(p)

    (pre,) = fake_proxy.plans
    assert pre.exit.id == p.id and pre.password == "s3cret"
    (up,) = fake_proxy.ups
    assert up.exit.id == p.id and up.password == "s3cret"
    # kiwi-pentesting finds a browser identity's gateway by these.
    assert up.labels == {"app": "kiwi-fox", "kiwi-fox.role": "gateway", "kiwi-fox.profile": p.id}
    # Measured once, on the host, before the window: not again through the gateway.
    assert up.measure is False
    (br,) = fake_proxy.started
    assert br.network == f"container:{paths.gateway_name(p.id)}"
    assert result.gateway == paths.gateway_name(p.id)
    assert "gateway up" in result.notes


def test_resolver_mode_mounts_the_gateways_resolv_conf(fake_proxy, firefox_installed):
    launch.launch(_firefox())
    (br,) = fake_proxy.started
    assert ("/run/kiwi-proxy/resolv.conf", "/etc/resolv.conf", "ro,z") in br.volumes


def test_remote_dns_mounts_no_resolv_conf(fake_proxy, firefox_installed):
    launch.launch(_firefox(dns=DnsConfig(mode="remote")))
    (br,) = fake_proxy.started
    assert all(dst != "/etc/resolv.conf" for _s, dst, _o in br.volumes)


def test_a_browser_that_fails_to_start_releases_the_gateway(
    fake_proxy, firefox_installed, monkeypatch
):
    from kiwi_proxy import podman

    def boom(spec, **_k):
        raise podman.PodmanError("no")

    monkeypatch.setattr(podman, "start", boom)
    p = _firefox()
    with pytest.raises(launch.LaunchError, match="browser failed to start"):
        launch.launch(p)
    assert fake_proxy.released == [(p.id, (paths.browser_name(p.id),))]


def test_a_gateway_error_is_a_launch_error(fake_proxy, firefox_installed, monkeypatch):
    def refuse(ex, **_k):
        raise gateway.GatewayError("exit 'plain' is up with other settings and in use")

    monkeypatch.setattr(gateway, "up", refuse)
    with pytest.raises(launch.LaunchError, match="in use"):
        launch.launch(_firefox())


def test_a_module_left_in_kiwi_fox_s_old_directory_is_pointed_out(fake_proxy, monkeypatch):
    old = paths.data_dir() / "modules" / "tor"
    old.mkdir(parents=True)

    def missing(ex, password=None, **_k):
        raise providers.ProviderError("provider module 'tor' is not installed")

    monkeypatch.setattr(gateway, "plan", missing)
    p = store.create("t", _endpoint(module="tor"), None, engine="firefox")
    with pytest.raises(launch.LaunchError, match="update kiwi-plugin-tor"):
        launch.plan(p)


# ------------------------------------------------------------------ stopping
def test_down_tears_the_gateway_down_whoever_is_inside(fake_proxy):
    p = _firefox()
    launch.down(p)
    assert fake_proxy.removed == [paths.browser_name(p.id)]
    assert fake_proxy.downed == [p.id]


def test_reap_releases_a_gateway_whose_browser_is_gone(fake_proxy, monkeypatch):
    p, q = _firefox("a"), _firefox("b")
    fake_proxy.running = {paths.gateway_name(p.id)}
    monkeypatch.setattr(gateway, "reap", lambda: [paths.gateway_name(q.id), "kf-gw-elsewhere"])
    cleaned = launch.reap()
    assert fake_proxy.released == [(p.id, (paths.browser_name(p.id),))]
    # kiwi-proxy's own sweep comes back by gateway; kiwi-fox reports its profiles by name.
    assert cleaned == ["a", "b", "kf-gw-elsewhere"]


# ------------------------------------------------------------------ the CLI
def test_kiwi_fox_module_is_kiwi_proxy_module(capsys):
    from kiwi_fox import cli

    assert cli.main(["module", "list", "--json"]) == 0
    assert capsys.readouterr().out.strip() == "[]"


def test_kiwi_fox_module_help_is_kiwi_proxy_s(capsys):
    from kiwi_fox import cli

    with pytest.raises(SystemExit) as stop:
        cli.main(["module", "--help"])
    assert stop.value.code == 0
    assert "usage: kiwi-proxy module" in capsys.readouterr().out


# ------------------------------------------------------------------ modules
class _FakeProvider:
    def __init__(self):
        self.ups = []

    def up(self, ctx, *, lease=None, country=None):
        self.ups.append((lease, country))
        return Endpoint(host="10.89.231.5", port=9050, module="tor", lease=lease, country=country)

    def leases(self, ctx):
        return []


def _fake_modules(monkeypatch, names=("tor",), runs_container=True):
    from kiwi_fox.core.models import ProviderManifest

    prov = _FakeProvider()
    manifests = {
        n: ProviderManifest(name=n, title=n.title(), runs_container=runs_container) for n in names
    }
    monkeypatch.setattr(providers, "discover", lambda: list(names))
    monkeypatch.setattr(providers, "is_installed", lambda n: n in manifests)
    monkeypatch.setattr(providers, "load", lambda n: (prov, manifests[n]))
    monkeypatch.setattr(providers, "context_for", lambda n, m: None)
    return prov


def test_installed_modules_are_listed(monkeypatch):
    from kiwi_fox.core import modules

    _fake_modules(monkeypatch, ("tor", "vpn"))
    assert [(m.name, m.title, m.produces_endpoint) for m in modules.installed()] == [
        ("tor", "Tor", True),
        ("vpn", "Vpn", True),
    ]


def test_an_endpoint_from_a_module_brings_it_up_with_lease_and_country(monkeypatch):
    from kiwi_fox.core import modules

    prov = _fake_modules(monkeypatch)
    ep = modules.endpoint_from("tor", lease=None, country="de")
    assert (ep.module, ep.country) == ("tor", "de")
    assert prov.ups == [(None, "de")]


def test_a_missing_module_names_the_app_to_install(monkeypatch):
    from kiwi_fox.core import modules

    _fake_modules(monkeypatch, ())
    with pytest.raises(providers.ProviderError, match="kiwi install kiwi-plugin-myst"):
        modules.endpoint_from("mysterium")


def test_no_engine_installed_is_a_launch_error_not_a_traceback(fake_proxy, monkeypatch):
    # engine_dir() raises RuntimeError when none of that engine is installed; the
    # CLI only reports LaunchError and friends, so it escaped as a traceback.
    monkeypatch.setattr(firefox_fetch, "latest_installed", lambda: None)
    p = store.create("unpinned", _endpoint(), None, engine="firefox")
    with pytest.raises(launch.LaunchError, match="engine fetch --engine firefox"):
        launch.launch(p)


def test_a_pinned_engine_that_is_gone_names_the_right_fetch(fake_proxy, monkeypatch, tmp_path):
    monkeypatch.setattr(firefox_fetch, "target_dir", lambda v: tmp_path / f"firefox-{v}")
    with pytest.raises(launch.LaunchError, match="engine fetch 159.0 --engine firefox"):
        launch.launch(_firefox())
