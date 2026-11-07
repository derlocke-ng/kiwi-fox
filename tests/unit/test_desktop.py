"""A profile's entry in the app grid: opt-in, written and removed by the store,
naming the installed launcher, so GNOME launches the profile like any app."""

from __future__ import annotations

import pytest
from kiwi_proxy import exits

from kiwi_fox import APP_ID
from kiwi_fox.core import desktop, paths, store
from kiwi_fox.core.models import Endpoint


def _exit(name="work") -> str:
    return exits.create(name, Endpoint(host="10.64.0.1", port=1080)).id


@pytest.fixture(autouse=True)
def _launcher(monkeypatch):
    monkeypatch.setattr(desktop, "launcher", lambda: "/home/me/.local/bin/kiwi-fox")


def test_an_entry_is_written_only_when_asked_and_removed_when_not():
    p = store.create("work", _exit(), None, engine="firefox")
    path = desktop.entry_path(p.id)
    assert path.parent == paths.applications_dir()
    assert path.name == f"{APP_ID}.profile-{p.id[:8]}.desktop"
    assert not path.exists(), "opt-in"
    p.desktop_entry = True
    store.save(p)
    text = path.read_text()
    assert text.startswith("[Desktop Entry]\nType=Application\nName=work\n")
    assert f"Exec=/home/me/.local/bin/kiwi-fox run {p.id}\n" in text
    assert f"Icon={APP_ID}\n" in text
    assert "Comment=Firefox · work — a Kiwi Fox browser identity\n" in text
    assert f"X-KiwiFox-Profile={p.id}\n" in text
    assert f"StartupWMClass={APP_ID}.profile-{p.id[:8]}\n" in text
    assert "[Desktop Action stop]\nName=Stop\n" in text
    assert f"Exec=/home/me/.local/bin/kiwi-fox stop {p.id}\n" in text
    assert "Categories=Network;WebBrowser;" in text
    p.desktop_entry = False
    store.save(p)
    assert not path.exists()


def test_a_rename_rewrites_it_and_delete_removes_it():
    p = store.create("work", _exit(), None, engine="firefox")
    p.desktop_entry = True
    store.save(p)
    p.name = "renamed"
    store.save(p)
    assert "Name=renamed\n" in desktop.entry_path(p.id).read_text()
    store.delete(p.id, purge=True)
    assert not desktop.entry_path(p.id).exists()


def test_the_comment_names_the_proxy_or_its_absence():
    bare = store.create("bare", None, None, engine="firefox")
    bare.desktop_entry = True
    store.save(bare)
    assert "Comment=Firefox · no proxy — " in desktop.entry_path(bare.id).read_text()


def test_a_launcher_path_with_a_space_is_quoted(monkeypatch):
    monkeypatch.setattr(desktop, "launcher", lambda: "/home/my name/.local/bin/kiwi-fox")
    p = store.create("work", _exit(), None, engine="firefox")
    p.desktop_entry = True
    store.save(p)
    assert f'Exec="/home/my name/.local/bin/kiwi-fox" run {p.id}\n' in (
        desktop.entry_path(p.id).read_text()
    )


def test_sync_all_writes_the_wanted_and_removes_the_stale():
    a = store.create("a", _exit("a"), None, engine="firefox")
    a.desktop_entry = True
    store.save(a)
    b = store.create("b", _exit("b"), None, engine="firefox")
    stale = paths.applications_dir() / f"{desktop.ENTRY_PREFIX}deadbeef.desktop"
    stale.write_text("[Desktop Entry]\nName=gone\n")
    with_entry, removed = desktop.sync_all(store.list_profiles(), store.entry_description)
    assert with_entry == ["a"]
    assert removed == [stale.name]
    assert desktop.entry_path(a.id).exists() and not desktop.entry_path(b.id).exists()


def test_a_desktop_that_cannot_take_the_file_does_not_stop_a_save(monkeypatch, tmp_path):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("")
    monkeypatch.setattr(paths, "applications_dir", lambda: blocker / "applications")
    p = store.create("work", _exit(), None, engine="firefox")
    p.desktop_entry = True
    store.save(p)  # no exception
    assert store.load(p.id).desktop_entry is True


def test_the_window_announces_the_entry_or_kiwi_fox(monkeypatch):
    # Firefox's --name is the Wayland app id, --class the X11 class (measured on
    # the engine: without them the window says "camoufox" and GNOME shows a blank).
    from kiwi_fox.core import launch

    monkeypatch.setattr(launch, "_wayland_mount", lambda: None)
    p = store.create("work", _exit(), None, engine="firefox", engine_version="159.0")
    from kiwi_fox.core.engines import firefox_fetch

    monkeypatch.setattr(firefox_fetch, "target_dir", lambda v: paths.data_dir() / "ff")
    spec = launch.browser_spec(p, None, "kf-gw", None)
    assert spec.args[:4] == ["--name", APP_ID, "--class", APP_ID]
    p.desktop_entry = True
    store.save(p)
    spec = launch.browser_spec(p, None, "kf-gw", None)
    own = f"{APP_ID}.profile-{p.id[:8]}"
    assert spec.args[:4] == ["--name", own, "--class", own]
    assert desktop.window_app_id(p) == own
    assert desktop.entry_path(p.id).name == f"{own}.desktop", "what the shell matches it to"


def test_tags_reach_the_entry_as_keywords():
    p = store.create("work", _exit(), None, engine="firefox")
    p.desktop_entry = True
    p.tags = ["shop", "eu"]
    store.save(p)
    assert "Keywords=kiwi;browser;profile;work;shop;eu;\n" in desktop.entry_path(p.id).read_text()


def test_cli_flags_and_the_desktop_command(capsys):
    from kiwi_fox import cli

    _exit("work")
    assert cli.main(["new", "ff", "--exit", "work", "--engine", "firefox", "--desktop-entry"]) == 0
    p = store.find_by_name("ff")
    assert p.desktop_entry and desktop.entry_path(p.id).exists()
    assert "app grid:" in capsys.readouterr().out
    assert cli.main(["set", "ff", "--no-desktop-entry"]) == 0
    assert not desktop.entry_path(p.id).exists()
    assert cli.main(["set", "ff", "--desktop-entry"]) == 0
    assert desktop.entry_path(p.id).exists()
    assert cli.main(["show", "ff"]) == 0
    assert "app grid  yes" in capsys.readouterr().out
    assert cli.main(["set", "ff", "--desktop-entry", "--no-desktop-entry"]) == 1
    capsys.readouterr()
    assert cli.main(["desktop", "list"]) == 0
    assert "ff               yes" in capsys.readouterr().out
    desktop.entry_path(p.id).unlink()
    assert cli.main(["desktop", "sync"]) == 0
    assert desktop.entry_path(p.id).exists()
    assert "entries: 1 (ff)" in capsys.readouterr().out
