"""A profile's container and its browser as two things: starting either, quitting
the browser, the preference that keeps the container, the watcher, repair."""

from __future__ import annotations

import subprocess

import pytest
from kiwi_proxy import exits, podman

from kiwi_fox.core import launch, paths, settings, store
from kiwi_fox.core.engines import firefox_fetch
from kiwi_fox.core.models import Endpoint


@pytest.fixture
def plain(fake_proxy, monkeypatch, tmp_path):
    monkeypatch.setattr(launch, "_wayland_mount", lambda: None)
    from kiwi_fox.core import gpu

    monkeypatch.setattr(gpu, "measurement", lambda: {"accelerated": True})
    monkeypatch.setattr(firefox_fetch, "target_dir", lambda v: tmp_path / f"firefox-{v}")
    eng = tmp_path / "firefox-159.0"
    eng.mkdir(parents=True)
    (eng / "firefox").write_text("#!/bin/sh\n")
    (eng / "firefox").chmod(0o755)
    ex = exits.create("plain-exit", Endpoint(host="10.64.0.1", port=1080))
    p = store.create("plain", ex.id, None, engine="firefox", engine_version="159.0")
    watchers = []
    monkeypatch.setattr(launch, "ensure_watcher", lambda profile: watchers.append(profile.id))
    fake_proxy.watchers = watchers
    return p, fake_proxy


def say(p, text: str) -> None:
    (launch.control_dir(p.id) / "browser").write_text(text + "\n")


def test_the_container_carries_the_launcher_and_its_control_folder(plain):
    p, rec = plain
    launch.launch(p)
    (spec,) = rec.started
    mounts = {dst: (src, opts) for src, dst, opts in spec.volumes}
    assert mounts[launch.LAUNCHER_MOUNT] == (str(launch.launcher_script()), "ro")
    assert mounts[launch.CONTROL_MOUNT][0] == str(launch.control_dir(p.id))
    assert spec.env["KF_CONTROL"] == launch.CONTROL_MOUNT and spec.env["KF_START_BROWSER"] == "1"
    import os

    assert os.access(launch.launcher_script(), os.X_OK)  # crun runs only an executable file
    assert rec.watchers == [p.id]  # whoever starts it, a watcher follows
    assert not (launch.control_dir(p.id) / "keep").exists()  # default: stop with the browser


def test_the_preference_keeps_the_container(plain):
    p, rec = plain
    settings.save(settings.Settings(keep_container=True))
    launch.launch(p, start_url="https://example.com/")
    assert (launch.control_dir(p.id) / "keep").exists()
    assert (launch.control_dir(p.id) / "url").read_text() == "https://example.com/\n"


def test_a_container_without_its_browser(plain):
    p, rec = plain
    launch.launch(p, browser=False)
    (spec,) = rec.started
    assert spec.env["KF_START_BROWSER"] == "0"
    assert (launch.control_dir(p.id) / "keep").exists()  # it waits for a browser


def test_the_browser_starts_in_a_running_container(plain, monkeypatch):
    p, rec = plain
    rec.running.add(paths.browser_name(p.id))
    say(p, "closed -")
    signals = []

    def signal(profile, sig):
        signals.append(sig)
        say(profile, "open 42")

    monkeypatch.setattr(launch, "_signal", signal)
    assert not launch.running(p) and launch.container_running(p)
    res = launch.launch(p, start_url="https://example.org/")
    assert signals == ["USR1"] and rec.started == []  # no new container
    assert res.browser == paths.browser_name(p.id)
    assert launch.running(p)
    with pytest.raises(launch.LaunchError, match="already open"):
        launch.launch(p)


def test_a_browser_that_does_not_come_up_is_an_error(plain, monkeypatch):
    p, rec = plain
    rec.running.add(paths.browser_name(p.id))
    say(p, "closed -")
    monkeypatch.setattr(launch, "_signal", lambda profile, sig: None)
    monkeypatch.setattr(launch, "OPEN_TIMEOUT", 0.3)
    with pytest.raises(launch.LaunchError, match="did not start"):
        launch.launch(p)


def test_quitting_the_browser(plain, monkeypatch):
    p, rec = plain
    signals = []
    monkeypatch.setattr(launch, "_signal", lambda profile, sig: signals.append(sig))
    rec.running.add(paths.browser_name(p.id))
    say(p, "open 42")
    launch.quit_browser(p)
    assert signals == ["USR2"] and rec.removed == []


def test_a_container_of_an_older_kiwi_fox_is_stopped_whole(plain, monkeypatch):
    p, rec = plain
    rec.running.add(paths.browser_name(p.id))  # no control folder: the browser is process 1
    assert launch.running(p) and not launch.supervised(p)
    launch.quit_browser(p)
    assert rec.removed == [paths.browser_name(p.id)]


def test_changing_the_preference_reaches_running_containers(plain):
    p, rec = plain
    say(p, "open 42")
    settings.save(settings.Settings(keep_container=True))
    launch.apply_keep_setting()
    assert (launch.control_dir(p.id) / "keep").exists()
    settings.save(settings.Settings(keep_container=False))
    launch.apply_keep_setting()
    assert not (launch.control_dir(p.id) / "keep").exists()


class FakeWait:
    """`podman wait` that returns after `polls` looks."""

    def __init__(self, polls):
        self.polls = polls

    def poll(self):
        self.polls -= 1
        return 0 if self.polls < 0 else None

    def kill(self):
        pass


def test_the_watcher_snapshots_when_the_browser_closes_and_lets_go_at_the_end(plain, monkeypatch):
    p, rec = plain
    say(p, "open 42")
    rec.running.add(paths.browser_name(p.id))
    monkeypatch.setattr(launch, "container_id", lambda profile: "c" * 64)
    monkeypatch.setattr(launch, "WATCH_POLL", 0)
    states = iter(["open 42", "open 42", "closed 0", "closed 0"])

    def look(profile):
        try:
            state = next(states)
        except StopIteration:
            state = "closed 0"
        return tuple(state.split(" ", 1))

    monkeypatch.setattr(launch, "browser_state", look)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: FakeWait(4))
    removed = []
    monkeypatch.setattr(
        podman,
        "_run",
        lambda args, **k: (removed.append(args), subprocess.CompletedProcess(args, 0, "", ""))[1],
    )
    taken = []
    from kiwi_fox.core import snapshots

    monkeypatch.setattr(snapshots, "after_stop", lambda profile: taken.append(profile.id))
    assert launch.watch(p) == 0
    assert taken == [p.id, p.id]  # when the browser closed, and at the end (no-op there)
    assert ["rm", "--force", "c" * 64] in removed
    assert rec.released and rec.released[-1][0] == p.exit
    assert not (launch.control_dir(p.id) / f"watch-{'c' * 12}").exists()


def test_a_second_watcher_for_the_same_container_leaves(plain, monkeypatch):
    p, _rec = plain
    monkeypatch.setattr(launch, "container_id", lambda profile: "d" * 64)
    (launch.control_dir(p.id) / f"watch-{'d' * 12}").write_text("1")
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("no second wait"))
    assert launch.watch(p) == 0


def test_repair_clears_locks_and_lets_go_of_exits(plain, monkeypatch):
    p, rec = plain
    data = paths.profile_dir(p.id) / "browser-data"
    data.mkdir(parents=True, exist_ok=True)
    (data / ".parentlock").write_text("x")
    from kiwi_proxy import storage

    monkeypatch.setattr(storage, "remove_leftovers", lambda app: [])
    from conftest import REAL_REPAIR

    done = REAL_REPAIR()
    assert f"cleared {p.name}'s stale lock" in done
    assert not (data / ".parentlock").exists()
    assert rec.released and rec.released[-1][0] == p.exit


def test_a_launcher_without_its_executable_bit_is_copied_with_it(monkeypatch, tmp_path):
    import os

    from kiwi_fox.core import setup

    src = tmp_path / "containers" / "browser"
    src.mkdir(parents=True)
    (src / "entrypoint.sh").write_text("#!/bin/sh\n")
    (src / "entrypoint.sh").chmod(0o644)
    monkeypatch.setattr(setup, "containers_dir", lambda: tmp_path / "containers")
    script = launch.launcher_script()
    assert script != src / "entrypoint.sh" and os.access(script, os.X_OK)
    assert script.read_text() == "#!/bin/sh\n"
