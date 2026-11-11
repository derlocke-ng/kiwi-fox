"""Engine versions: releases, who uses what, pins, moves, removal, new releases."""

from __future__ import annotations

import pytest
from kiwi_proxy import exits

from kiwi_fox.core import engine_versions as ev
from kiwi_fox.core import paths, settings, store
from kiwi_fox.core.models import Endpoint


@pytest.fixture
def engines(monkeypatch):
    for name, binary in (
        ("firefox-158.0", "firefox"),
        ("firefox-159.0.1", "firefox"),
        ("torbrowser-15.0.1", "Browser/firefox"),
        ("torbrowser-15.0.2", "Browser/firefox"),
    ):
        f = paths.engines_dir() / name / binary
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x")
    listed = {"camoufox": ["157.0.1"], "firefox": ["160.0", "159.0.1"], "torbrowser": ["15.0.2"]}
    monkeypatch.setattr(ev, "_fetch_releases", lambda e: [ev.Release(v) for v in listed[e]])
    return listed


def _exit():
    return exits.create("e", Endpoint(host="10.64.0.1", port=1080)).id


def test_follow_pin_and_remove(engines):
    ff = store.create("ff", _exit(), None, engine="firefox")
    assert ev.version_of(ff) == "159.0.1" and not ev.pinned(ff)
    with pytest.raises(ev.VersionError, match="in use: ff"):
        ev.remove("firefox", "159.0.1")
    ff, warn = ev.pin(ff, "158.0")
    assert ev.version_of(ff) == "158.0" and warn == []
    ev.set_default("firefox", "158.0")
    ev.remove("firefox", "159.0.1")  # nobody on it now
    assert "159.0.1" not in ev.installed_versions("firefox")


def test_an_old_tor_browser_pin_warns_and_the_floor_holds(engines):
    tor = exits.create(
        "t", Endpoint(host="10.89.231.5", port=9050, module="tor"), socks_auth="passthrough"
    )
    tb = store.create("tb", tor.id, None, engine="torbrowser")
    tb, warn = ev.pin(tb, "15.0.1")
    assert warn and "stands out" in warn[0]


def test_releases_newest_first_with_what_is_installed(engines):
    assert [r.version for r in ev.releases("firefox")] == ["160.0", "159.0.1", "158.0"]
    assert ev.newest("firefox") == "160.0"


def test_new_releases_follow_the_preference(engines, monkeypatch):
    installed = []
    monkeypatch.setattr(ev, "install", lambda e, v, progress=None: installed.append((e, v)))
    found = ev.news()
    assert [(n.engine, n.version, n.installed) for n in found.news] == [("firefox", "160.0", False)]
    assert ev.news().news == []  # once a day
    settings.save(settings.Settings(engine_updates="auto"))
    ev._state().unlink()
    ev.news()
    assert installed == [("firefox", "160.0")]
    settings.save(settings.Settings(engine_updates="off"))
    ev._state().unlink()
    assert not ev.news().checked


def test_downgrading_is_seen_from_the_profile(engines):
    ff = store.create("ff", _exit(), None, engine="firefox")
    data = paths.profile_dir(ff.id) / "browser-data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "compatibility.ini").write_text(
        "[Compatibility]\nLastVersion=159.0.1_20260101/20260101\n"
    )
    assert ev.downgrading(ff, "158.0") and not ev.downgrading(ff, "160.0")


def test_a_camoufox_profile_moves_with_its_fingerprint(fp, monkeypatch):
    for v in ("152.0.4", "156.0.1"):
        f = paths.engines_dir() / f"camoufox-{v}" / "camoufox"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x")
    p = store.create("cf", _exit(), fp)
    refused, _warn = ev.move(p, "156.0.1")
    assert refused == [] and store.fingerprint_of(p).engine_version == "156.0.1"
    with pytest.raises(ev.VersionError, match="not installed"):
        ev.move(p, "999.0")
