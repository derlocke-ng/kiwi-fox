"""kiwi-fox as a kiwi-proxy consumer: a profile references an exit — a proxy the
user defined in kiwi-proxy, or one kiwi-fox made as a shortcut — or none at all,
and every profile on an exit shares its one gateway.

kiwi-proxy's own tests cover what a gateway does; these pin what kiwi-fox
promises: profiles from before 0.4 keep the names and tokens a host already has,
the exit's settings are kiwi-proxy's alone, a closing window only releases, and
a profile without a proxy runs on this machine's connection with no proxy
configured at all.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from kiwi_proxy import exits, gateway, providers
from kiwi_proxy import paths as proxy_paths
from kiwi_proxy import secrets as proxy_secrets

from kiwi_fox.core import launch, paths, store
from kiwi_fox.core.engines import firefox_fetch, get_engine
from kiwi_fox.core.models import DnsConfig, Endpoint, ExitInfo


def _endpoint(**kw):
    return Endpoint(host="10.64.0.1", port=1080, **kw)


def _exit(name="work", **kw):
    """A proxy the user made in kiwi-proxy (`kiwi-proxy add`)."""
    return exits.create(name, _endpoint(), **kw)


def _firefox(name="plain", exit_id=None, **kw):
    return store.create(name, exit_id, None, engine="firefox", engine_version="159.0", **kw)


@pytest.fixture
def firefox_installed(monkeypatch, tmp_path):
    monkeypatch.setattr(firefox_fetch, "target_dir", lambda v: tmp_path / f"firefox-{v}")
    eng = tmp_path / "firefox-159.0"
    eng.mkdir(parents=True)
    (eng / "firefox").write_text("#!/bin/sh\n")
    monkeypatch.setattr(launch, "_wayland_mount", lambda: None)
    from kiwi_fox.core import gpu

    monkeypatch.setattr(gpu, "measurement", lambda: {"accelerated": True})


# ----------------------------------------------------------------- the exit
def test_a_profile_references_an_exit_the_user_made():
    ex = _exit("kiwi-master-tor")
    p = _firefox(exit_id=ex.id)
    assert p.exit == ex.id
    assert store.exit_of(p) == ex
    assert exits.load(ex.id).owner is None, "the user's exit is not claimed"
    assert paths.gateway_name(p.exit) == proxy_paths.gateway_name(ex.id)


def test_the_shortcut_makes_an_exit_named_after_the_profile():
    ex = store.create_exit("plain", _endpoint(), password="pw", dns=DnsConfig(mode="remote"))
    p = _firefox(exit_id=ex.id)
    assert (ex.name, ex.owner, ex.socks_auth, ex.dns.mode) == (
        "plain",
        "kiwi-fox",
        "inject",
        "remote",
    )
    assert proxy_secrets.lookup(ex.id, kind="endpoint") == "pw", "the password is kiwi-proxy's"
    assert store.describe_exit(store.exit_of(p)).startswith("plain · 10.64.0.1:1080 · dns remote")


def test_the_shortcut_refuses_a_name_kiwi_proxy_has():
    _exit("work")
    with pytest.raises(store.StoreError, match="already exists"):
        store.create_exit("work", _endpoint())


def test_a_profile_needs_an_exit_that_exists():
    with pytest.raises(store.StoreError, match="no exit"):
        _firefox(exit_id="00000000-0000-0000-0000-000000000000")


def test_an_exit_gone_from_kiwi_proxy_is_a_clear_error_not_a_crash(fake_proxy):
    p = _firefox(exit_id=_exit().id)
    exits.delete(p.exit)  # `kiwi-proxy rm work`
    with pytest.raises(launch.LaunchError, match="gone from kiwi-proxy.*--exit NAME"):
        launch.plan(p)
    assert store.load(p.id).exit, "the reference stays; the user picks another"


def test_the_exits_settings_are_never_written_back():
    ex = _exit(dns=DnsConfig(mode="remote", upstream="quad9"))
    p = _firefox(exit_id=ex.id)
    p.name = "renamed"
    store.save(p)
    store.touch(store.load(p.id))
    assert exits.load(ex.id) == ex


def test_profile_json_carries_the_exit_id_and_no_endpoint():
    p = _firefox(exit_id=_exit().id)
    raw = json.loads((paths.profile_dir(p.id) / "profile.json").read_text())
    assert raw["exit"] == p.exit
    assert "endpoint" not in raw and "dns" not in raw


# -------------------------------------------------------------- migration
def _write_0_3_profile(name="desk", *, password=False) -> str:
    """profile.json as kiwi-fox 0.3 wrote it: endpoint and DNS on the profile."""
    pid = "d97dd7a3-20b6-422d-a313-02f6dab76942"
    raw = {
        "id": pid,
        "name": name,
        "created": "2026-10-04T18:42:42Z",
        "engine": "firefox",
        "engine_version": "159.0",
        "endpoint": {
            "host": "10.64.0.1",
            "port": 1080,
            "username": "u" if password else None,
            "has_password": password,
        },  # fmt: skip
        "dns": {"mode": "resolver", "upstream": "google", "blocklists": ["oisd-big"]},
    }
    pdir = paths.profile_dir(pid)
    pdir.mkdir(parents=True)
    (pdir / "profile.json").write_text(json.dumps(raw))
    (pdir / "dns.json").write_text(json.dumps(raw["dns"]))
    return pid


def test_a_0_3_profile_keeps_the_exit_it_owned_as_the_proxy_it_uses():
    pid = _write_0_3_profile()
    # 0.3's setup registered the exit under the profile's id with owner kiwi-fox.
    exits.create("desk", _endpoint(), exit_id=pid, owner="kiwi-fox")
    p = store.load(pid)
    assert p.exit == pid, "same exit id, so the gateway is still kf-gw-<profile id>"
    assert p.endpoint is None and p.dns is None
    assert paths.gateway_name(p.exit) == f"kf-gw-{pid[:12]}"
    raw = json.loads((paths.profile_dir(pid) / "profile.json").read_text())
    assert raw["exit"] == pid and "endpoint" not in raw
    assert not (paths.profile_dir(pid) / "dns.json").exists()


def test_a_0_3_profile_that_never_got_an_exit_gets_it_now():
    pid = _write_0_3_profile("desk")
    p = store.load(pid)
    ex = exits.load(pid)
    assert (p.exit, ex.name, ex.owner, ex.dns.mode) == (pid, "desk", "kiwi-fox", "resolver")
    assert (ex.endpoint.host, ex.endpoint.port) == ("10.64.0.1", 1080)


def test_a_0_3_profile_whose_name_an_exit_has_gets_a_suffixed_one():
    _exit("desk")  # made with the kiwi-proxy CLI meanwhile
    pid = _write_0_3_profile("desk")
    assert exits.load(store.load(pid).exit).name == f"desk-{pid[:8]}"


def test_a_0_3_password_moves_from_kiwi_fox_s_keyring_to_kiwi_proxy_s(monkeypatch):
    pid = _write_0_3_profile("desk", password=True)
    monkeypatch.setattr("kiwi_fox.core.secrets.lookup", lambda i: "s3cret" if i == pid else None)
    store.load(pid)
    assert proxy_secrets.lookup(pid, kind="endpoint") == "s3cret"


def test_migration_happens_once(monkeypatch):
    pid = _write_0_3_profile()
    store.load(pid)
    saved = exits.load(pid)
    monkeypatch.setattr(exits, "create", lambda *a, **k: pytest.fail("created again"))
    assert store.load(pid).exit == pid
    assert exits.load(pid) == saved


# ------------------------------------------------------------------ deleting
def test_delete_takes_a_shortcut_exit_with_its_last_profile():
    ex = store.create_exit("plain", _endpoint())
    a, b = _firefox("a", ex.id), _firefox("b", ex.id)
    store.delete(a.id, purge=True)
    assert exits.exists(ex.id), "b is still on it"
    store.delete(b.id, purge=True)
    assert not exits.exists(ex.id)


def test_delete_leaves_the_users_exit_alone():
    ex = _exit("kiwi-master-tor")
    p = _firefox(exit_id=ex.id)
    store.delete(p.id, purge=True)
    assert exits.exists(ex.id)


# ----------------------------------------------------------------- launching
def test_two_profiles_on_one_exit_share_its_gateway(fake_proxy, firefox_installed):
    ex = _exit("shared")
    a, b = _firefox("a", ex.id), _firefox("b", ex.id)
    ra, rb = launch.launch(a), launch.launch(b)
    assert [u.exit.id for u in fake_proxy.ups] == [ex.id, ex.id]
    assert ra.gateway == rb.gateway == paths.gateway_name(ex.id)
    assert {br.network for br in fake_proxy.started} == {f"container:{paths.gateway_name(ex.id)}"}
    # The gateway is the exit's, so no profile is named on it; kiwi-pentesting
    # finds it by kiwi-proxy.role=gateway, app=kiwi-fox is the fallback.
    assert all(u.labels == {"app": "kiwi-fox", "kiwi-fox.role": "gateway"} for u in fake_proxy.ups)
    # The password is kiwi-proxy's to look up; kiwi-fox hands none over.
    assert all(u.password is None for u in fake_proxy.ups)
    # Measured once, on the host, before the window: not again through the gateway.
    assert all(u.measure is False for u in fake_proxy.ups)


def test_stop_releases_the_exit_ignoring_only_its_own_browser(fake_proxy):
    ex = _exit("shared")
    a = _firefox("a", ex.id)
    launch.stop(a)
    assert fake_proxy.removed == [paths.browser_name(a.id)]
    assert fake_proxy.released == [(ex.id, (paths.browser_name(a.id),))]


def test_down_releases_too_never_tearing_a_shared_gateway_down(fake_proxy):
    a = _firefox("a", _exit().id)
    launch.down(a)
    assert fake_proxy.downed == []
    assert fake_proxy.released == [(a.exit, (paths.browser_name(a.id),))]


def test_resolver_mode_mounts_the_gateways_resolv_conf(fake_proxy, firefox_installed):
    launch.launch(_firefox(exit_id=_exit().id))
    (br,) = fake_proxy.started
    assert ("/run/kiwi-proxy/resolv.conf", "/etc/resolv.conf", "ro,z") in br.volumes


def test_remote_dns_mounts_no_resolv_conf(fake_proxy, firefox_installed):
    launch.launch(_firefox(exit_id=_exit(dns=DnsConfig(mode="remote")).id))
    (br,) = fake_proxy.started
    assert all(dst != "/etc/resolv.conf" for _s, dst, _o in br.volumes)


def test_a_browser_that_fails_to_start_releases_the_gateway(
    fake_proxy, firefox_installed, monkeypatch
):
    from kiwi_proxy import podman

    def boom(spec, **_k):
        raise podman.PodmanError("no")

    monkeypatch.setattr(podman, "start", boom)
    p = _firefox(exit_id=_exit().id)
    with pytest.raises(launch.LaunchError, match="browser failed to start"):
        launch.launch(p)
    assert fake_proxy.released == [(p.exit, (paths.browser_name(p.id),))]


def test_a_gateway_error_is_a_launch_error(fake_proxy, firefox_installed, monkeypatch):
    def refuse(ex, **_k):
        raise gateway.GatewayError("exit 'work' is up with other settings and in use")

    monkeypatch.setattr(gateway, "up", refuse)
    with pytest.raises(launch.LaunchError, match="in use"):
        launch.launch(_firefox(exit_id=_exit().id))


def test_a_module_left_in_kiwi_fox_s_old_directory_is_pointed_out(fake_proxy, monkeypatch):
    old = paths.data_dir() / "modules" / "tor"
    old.mkdir(parents=True)

    def missing(ex, password=None, **_k):
        raise providers.ProviderError("provider module 'tor' is not installed")

    monkeypatch.setattr(gateway, "plan", missing)
    ex = exits.create("t", _endpoint(module="tor"))
    p = _firefox("t", ex.id)
    with pytest.raises(launch.LaunchError, match="update kiwi-plugin-tor"):
        launch.plan(p)


# ------------------------------------------------------------------ no proxy
def test_a_profile_with_no_proxy_runs_on_this_machines_connection(
    fake_proxy, firefox_installed, monkeypatch
):
    seen = ExitInfo(ip="203.0.113.7", country="DE", seen=dt.datetime.now(dt.UTC))
    monkeypatch.setattr(launch, "measure_direct", lambda timeout=10: seen)
    p = _firefox("direct", None)
    res = launch.launch(p)
    assert fake_proxy.ups == [] and fake_proxy.plans == []
    (br,) = fake_proxy.started
    assert br.network == "pasta"
    assert all(dst != "/etc/resolv.conf" for _s, dst, _o in br.volumes)
    assert res.gateway is None and res.exit_info == seen
    assert "no proxy: this machine's own connection" in res.notes
    prefs = get_engine("firefox").prefs(None, p)
    assert prefs["network.proxy.type"] == 0 and "network.proxy.socks" not in prefs


def test_no_proxy_means_nothing_to_release_or_probe(fake_proxy):
    p = _firefox("direct", None)
    launch.stop(p)
    assert fake_proxy.released == []
    with pytest.raises(launch.LaunchError, match="no proxy"):
        launch.start_gateway(p)


def test_a_direct_measurement_that_fails_is_a_note_not_an_error(monkeypatch):
    def down(timeout=10):
        raise OSError("offline")

    monkeypatch.setattr(launch, "measure_direct", down)
    pre = launch.plan(_firefox("direct", None))
    assert pre.info is None and any("could not measure" in n for n in pre.notes)


# ------------------------------------------------------------------ reaping
def test_reap_releases_a_gateway_whose_browser_is_gone(fake_proxy, monkeypatch):
    a = _firefox("a", store.create_exit("a", _endpoint()).id)
    b = _firefox("b", store.create_exit("b", _endpoint()).id)
    fake_proxy.running = {paths.gateway_name(a.exit)}
    monkeypatch.setattr(gateway, "reap", lambda: [paths.gateway_name(b.exit), "kf-gw-elsewhere"])
    cleaned = launch.reap()
    assert fake_proxy.released == [(a.exit, (paths.browser_name(a.id),))]
    # kiwi-proxy's own sweep comes back by gateway; kiwi-fox names the exit.
    assert cleaned == ["a", "b", "kf-gw-elsewhere"]


# ------------------------------------------------------------------ the CLI
def test_new_on_an_existing_exit(capsys):
    from kiwi_fox import cli

    ex = _exit("kiwi-master-tor")
    assert cli.main(["new", "mt", "--exit", "kiwi-master-tor", "--engine", "firefox"]) == 0
    p = store.find_by_name("mt")
    assert p is not None and p.exit == ex.id
    assert "exit    : kiwi-master-tor · 10.64.0.1:1080" in capsys.readouterr().out


def test_new_with_an_endpoint_makes_the_exit_and_a_failed_create_removes_it(capsys):
    from kiwi_fox import cli

    # Tor Browser on a plain endpoint is refused — and the shortcut exit goes too.
    assert cli.main(["new", "tb", "10.64.0.1:1080", "--engine", "torbrowser"]) == 1
    assert "tor module" in capsys.readouterr().err
    assert exits.find_by_name("tb") is None
    assert (
        cli.main(["new", "ff", "10.64.0.1:1080", "--engine", "firefox", "--dns-mode", "remote"])
        == 0
    )
    ex = exits.find_by_name("ff")
    assert ex is not None and ex.owner == "kiwi-fox" and ex.dns.mode == "remote"
    assert store.find_by_name("ff").exit == ex.id


def test_new_says_where_one_way(capsys):
    from kiwi_fox import cli

    _exit("work")
    assert cli.main(["new", "x", "--engine", "firefox"]) == 1
    assert "one way" in capsys.readouterr().err
    assert cli.main(["new", "x", "10.64.0.1:1080", "--exit", "work", "--engine", "firefox"]) == 1
    assert "one way" in capsys.readouterr().err
    assert (
        cli.main(["new", "x", "--exit", "work", "--dns-mode", "remote", "--engine", "firefox"]) == 1
    )
    assert "keeps its own" in capsys.readouterr().err
    assert cli.main(["new", "x", "--exit", "nope", "--engine", "firefox"]) == 1
    assert "kiwi-proxy list" in capsys.readouterr().err


def test_new_refuses_a_profile_name_kiwi_proxy_uses_and_points_at_exit(capsys):
    from kiwi_fox import cli

    _exit("work")
    assert cli.main(["new", "work", "10.64.0.1:1080", "--engine", "firefox"]) == 1
    assert "--exit work" in capsys.readouterr().err


def test_new_no_proxy(capsys):
    from kiwi_fox import cli

    assert cli.main(["new", "bare", "--no-proxy", "--engine", "firefox"]) == 0
    assert store.find_by_name("bare").exit is None
    assert "no proxy" in capsys.readouterr().out
    assert cli.main(["new", "tb", "--no-proxy", "--engine", "torbrowser"]) == 1
    assert "tor module" in capsys.readouterr().err


def test_list_shows_the_exit_by_name(capsys):
    from kiwi_fox import cli

    _firefox("a", _exit("kiwi-master-tor").id)
    _firefox("b", None)
    missing = _firefox("c", _exit("gone").id)
    exits.delete(missing.exit)
    assert cli.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "kiwi-master-tor" in out and "no proxy" in out and "MISSING" in out


def test_set_moves_a_profile_between_exits_and_off_them(capsys):
    from kiwi_fox import cli

    a, b = _exit("a"), _exit("b")
    _firefox("plain", a.id)
    assert cli.main(["set", "plain", "--name", "renamed", "--exit", "b"]) == 0
    p = store.find_by_name("renamed")
    assert p is not None and p.exit == b.id
    assert cli.main(["set", "renamed", "--no-proxy"]) == 0
    assert store.find_by_name("renamed").exit is None
    assert cli.main(["set", "renamed", "--exit", "a", "--no-proxy"]) == 1
    assert "exclude" in capsys.readouterr().err


def test_set_holds_tor_browser_to_the_tor_module(capsys):
    from kiwi_fox import cli

    tor = exits.create(
        "tor", Endpoint(host="10.89.231.5", port=9050, module="tor"), socks_auth="passthrough"
    )
    _exit("plain")
    store.create("tb", tor.id, None, engine="torbrowser", engine_version="15.0.26")
    assert cli.main(["set", "tb", "--exit", "plain"]) == 1
    assert "tor module" in capsys.readouterr().err
    assert cli.main(["set", "tb", "--no-proxy"]) == 1
    assert store.find_by_name("tb").exit == tor.id


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
def _fake_modules(monkeypatch, names=("tor",), runs_container=True):
    from kiwi_fox.core.models import ProviderManifest

    manifests = {
        n: ProviderManifest(name=n, title=n.title(), runs_container=runs_container) for n in names
    }
    monkeypatch.setattr(providers, "discover", lambda: list(names))
    monkeypatch.setattr(providers, "is_installed", lambda n: n in manifests)
    monkeypatch.setattr(providers, "load", lambda n: (None, manifests[n]))


def test_installed_modules_are_listed(monkeypatch):
    from kiwi_fox.core import modules

    _fake_modules(monkeypatch, ("tor", "vpn"))
    assert [(m.name, m.title, m.produces_endpoint) for m in modules.installed()] == [
        ("tor", "Tor", True),
        ("vpn", "Vpn", True),
    ]


def test_a_missing_module_names_the_app_to_install():
    from kiwi_fox.core import modules

    assert modules.install_hint("mysterium") == "kiwi install kiwi-plugin-myst"


def test_no_engine_installed_is_a_launch_error_not_a_traceback(fake_proxy, monkeypatch):
    # engine_dir() raises RuntimeError when none of that engine is installed; the
    # CLI only reports LaunchError and friends, so it escaped as a traceback.
    monkeypatch.setattr(firefox_fetch, "latest_installed", lambda: None)
    p = store.create("unpinned", _exit().id, None, engine="firefox")
    with pytest.raises(launch.LaunchError, match="engine fetch --engine firefox"):
        launch.launch(p)


def test_a_pinned_engine_that_is_gone_names_the_right_fetch(fake_proxy, monkeypatch, tmp_path):
    monkeypatch.setattr(firefox_fetch, "target_dir", lambda v: tmp_path / f"firefox-{v}")
    with pytest.raises(launch.LaunchError, match="engine fetch 159.0 --engine firefox"):
        launch.launch(_firefox(exit_id=_exit().id))


# ------------------------------------------------- the CLI on non-camoufox profiles
def test_set_refuses_identity_flags_on_a_firefox_profile(capsys):
    from kiwi_fox import cli

    _firefox("plain", _exit().id)
    assert cli.main(["set", "plain", "--screen", "2560x1440"]) == 1
    assert "spoofs nothing" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [["webgl", "plain"], ["fonts", "plain"], ["selfcheck", "plain"]])
def test_camoufox_only_commands_say_why(argv, capsys):
    from kiwi_fox import cli

    _firefox("plain", _exit().id)
    assert cli.main(argv) == 1
    assert "is a Firefox profile" in capsys.readouterr().err
