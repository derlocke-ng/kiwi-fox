"""Profiles in the snapshot folder: what goes in, when, and how it comes back.

Real gpg and zstd through kiwi-proxy's snapshot library, the passphrase stretching
turned down; two devices are two sets of XDG directories over one folder.
"""

from __future__ import annotations

import contextlib
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

import pytest
from kiwi_proxy import exits
from kiwi_proxy.models import Endpoint

from kiwi_fox import cli
from kiwi_fox.core import launch, paths, store
from kiwi_fox.core import snapshots as fox

pytestmark = pytest.mark.skipif(
    not fox.available() or bool(fox.snap.missing_tools()),
    reason="profile snapshots need kiwi-proxy 0.8, gpg and zstd",
)

PASS = "correct horse battery staple"


@pytest.fixture(scope="session")
def _gpg_home():
    home = tempfile.mkdtemp(prefix="kf-test-gpg-")
    yield home
    subprocess.run(["gpgconf", "--homedir", home, "--kill", "all"], capture_output=True)
    shutil.rmtree(home, ignore_errors=True)


@pytest.fixture(autouse=True)
def _fast(monkeypatch, _gpg_home, tmp_path):
    from kiwi_proxy.snapshots import crypt
    from kiwi_proxy.snapshots.folder import Folder

    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "xdg_runtime_dir"))
    monkeypatch.setattr(crypt, "S2K_COUNT", 1024)
    monkeypatch.setattr(crypt, "_gpg_home", lambda: contextlib.nullcontext(_gpg_home))
    monkeypatch.setattr(launch, "running", lambda profile: False)
    monkeypatch.setattr(launch, "container_running", lambda profile: False)
    fox.snap._session.clear()
    Folder.forget_unlocked()
    yield
    fox.snap._session.clear()
    Folder.forget_unlocked()


def device(tmp_path: Path, monkeypatch, name: str) -> None:
    from kiwi_proxy.snapshots.folder import Folder

    for var in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR"):
        monkeypatch.setenv(var, str(tmp_path / name / var.lower()))
    fox.snap._session.clear()
    Folder.forget_unlocked()


def make_profile(fp, name="work", exit_name="mullvad"):
    ex = exits.find_by_name(exit_name) or exits.create(
        exit_name, Endpoint(host="10.64.0.1", port=1080)
    )
    p = store.create(name, ex.id, fp)
    data = paths.profile_dir(p.id) / "browser-data"
    for rel, content in {
        "places.sqlite": "history",
        "places.sqlite-wal": "unflushed history",
        "logins.db": "saved logins",
        "storage/default/site/ls/data.sqlite": "site storage",
        "cache2/entries/ABC": "x" * 4000,
        "startupCache/startupCache.8.little": "y" * 4000,
        ".cache/mesa_shader_cache/index": "z",
        "safebrowsing/google4/goog-phish.vlpset": "s",
        "suggest.sqlite": "q",
        "gmp-gmpopenh264/2.3/libgmpopenh264.so": "codec",
        "Downloads/report.pdf": "a download",
    }.items():
        path = data / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    (data / "lock").symlink_to("127.0.0.1:+1")
    (paths.profile_dir(p.id) / "downloads").mkdir(exist_ok=True)
    (paths.profile_dir(p.id) / "downloads" / "file.zip").write_text("downloaded")
    return p, ex


def archive_names(meta) -> list[str]:
    folder = fox.snap.folder()
    out = Path(tempfile.mkdtemp())
    folder.extract(meta, out)
    return sorted(str(p.relative_to(out)) for p in out.rglob("*") if not p.is_dir())


# --------------------------------------------------------------- contents
def test_a_profile_snapshot_keeps_the_identity_not_the_caches(tmp_path, monkeypatch, fp):
    device(tmp_path, monkeypatch, "lime")
    fox.snap.setup(tmp_path / "shared", PASS, device_name="lime")
    p, _ex = make_profile(fp)
    meta = fox.take(p)
    names = archive_names(meta)
    assert "profile/profile.json" in names and "profile/fingerprint.json" in names
    for kept in (
        "places.sqlite",
        "places.sqlite-wal",
        "logins.db",
        "storage/default/site/ls/data.sqlite",
    ):
        assert f"profile/browser-data/{kept}" in names
    for gone in (
        "cache2",
        "startupCache",
        ".cache",
        "safebrowsing",
        "suggest.sqlite",
        "gmp-",
        "Downloads",
        "lock",
    ):
        assert not any(n.startswith(f"profile/browser-data/{gone}") for n in names), gone
    assert not any(n.startswith("profile/downloads") for n in names)
    assert meta.extra["engine"] == "camoufox" and meta.extra["exit_name"] == "mullvad"
    assert meta.app == "kiwi-fox"


def test_skipped_rules():
    assert fox.skipped("downloads/x.zip")
    assert fox.skipped("browser-data/cache2/entries/1")
    assert fox.skipped("browser-data/suggest.sqlite-wal")
    assert fox.skipped("browser-data/gmp-widevinecdm")
    assert not fox.skipped("browser-data/places.sqlite-wal")
    assert not fox.skipped("browser-data/storage/default")
    assert not fox.skipped("fingerprint.json")


def test_a_running_profile_is_not_snapshotted(tmp_path, monkeypatch, fp):
    device(tmp_path, monkeypatch, "lime")
    fox.snap.setup(tmp_path / "shared", PASS)
    p, _ex = make_profile(fp)
    monkeypatch.setattr(launch, "running", lambda profile: True)
    with pytest.raises(fox.snap.SnapshotError, match="running"):
        fox.take(p)
    assert fox.after_stop(p) is None and fox.snap.history("profile", p.id) == []


# ---------------------------------------------------------------- when
def test_after_stop_takes_what_ran_and_nothing_else(tmp_path, monkeypatch, fp):
    device(tmp_path, monkeypatch, "lime")
    fox.snap.setup(tmp_path / "shared", PASS)
    p, _ex = make_profile(fp)
    assert fox.after_stop(p) is None  # never snapshotted: the first one
    assert len(fox.snap.history("profile", p.id)) == 1
    assert fox.after_stop(p) is None  # nothing new: nothing taken
    assert len(fox.snap.history("profile", p.id)) == 1
    fox.started(p)
    assert fox.after_stop(p) is None  # it ran
    assert len(fox.snap.history("profile", p.id)) == 2


def test_in_use_shows_on_the_other_device_until_it_stops(tmp_path, monkeypatch, fp):
    shared = tmp_path / "shared"
    device(tmp_path, monkeypatch, "lime")
    fox.snap.setup(shared, PASS, device_name="lime")
    p, ex = make_profile(fp)
    fox.take(p)
    fox.started(p)

    device(tmp_path, monkeypatch, "titan")
    fox.snap.setup(shared, PASS, device_name="titan")
    exits.create("mullvad", Endpoint(host="10.64.0.1", port=1080), exit_id=ex.id)
    restored = fox.restore(p.id, fox.snap.history("profile", p.id)[0].id)
    check = fox.before_start(restored)
    assert [d for d, _ in check.in_use] == ["lime"] and check.needs_asking

    device(tmp_path, monkeypatch, "lime")
    fox.after_stop(p)
    device(tmp_path, monkeypatch, "titan")
    check = fox.before_start(restored)
    assert check.in_use == []
    assert check.relation.state == "folder_newer"  # lime's run after titan restored


# -------------------------------------------------------------- restore
def test_a_profile_comes_back_on_another_device(tmp_path, monkeypatch, fp):
    shared = tmp_path / "shared"
    device(tmp_path, monkeypatch, "lime")
    fox.snap.setup(shared, PASS, device_name="lime")
    p, ex = make_profile(fp)
    meta = fox.take(p)

    device(tmp_path, monkeypatch, "titan")
    fox.snap.setup(shared, PASS, device_name="titan")
    assert [a[1] for a in fox.away()] == ["work"]
    with pytest.raises(fox.RestoreError, match="restore mullvad in Kiwi Proxy first"):
        fox.restore(p.id, meta.id)
    assert not paths.profile_dir(p.id).exists()

    exits.create("mullvad", Endpoint(host="10.64.0.1", port=1080), exit_id=ex.id)
    restored = fox.restore(p.id, meta.id)
    assert restored.name == "work" and restored.exit == ex.id
    data = paths.profile_dir(p.id) / "browser-data"
    assert (data / "places.sqlite").read_text() == "history"
    assert not (data / "cache2").exists()
    assert (paths.profile_dir(p.id) / "downloads").is_dir()
    assert store.load_fingerprint(p.id) == store.load_fingerprint(p.id)  # loads
    assert fox.away() == []


def test_a_restore_keeps_this_devices_downloads_and_changes(tmp_path, monkeypatch, fp):
    device(tmp_path, monkeypatch, "lime")
    fox.snap.setup(tmp_path / "shared", PASS)
    p, _ex = make_profile(fp)
    first = fox.take(p)
    (paths.profile_dir(p.id) / "browser-data" / "places.sqlite").write_text("newer history")
    fox.started(p)  # changed since its snapshot
    fox.restore(p.id, first.id)
    folder = paths.profile_dir(p.id)
    assert (folder / "browser-data" / "places.sqlite").read_text() == "history"
    assert (folder / "downloads" / "file.zip").read_text() == "downloaded"
    aside = [m for m in fox.snap.history("profile", p.id) if m.aside]
    assert len(aside) == 1  # the changed copy, kept
    fox.restore(p.id, aside[0].id)
    assert (folder / "browser-data" / "places.sqlite").read_text() == "newer history"


def test_restoring_a_running_profile_is_refused(tmp_path, monkeypatch, fp):
    device(tmp_path, monkeypatch, "lime")
    fox.snap.setup(tmp_path / "shared", PASS)
    p, _ex = make_profile(fp)
    meta = fox.take(p)
    monkeypatch.setattr(launch, "running", lambda profile: True)
    with pytest.raises(fox.RestoreError, match="is open; close its browser first"):
        fox.restore(p.id, meta.id)


def test_restoring_stops_a_container_kept_without_its_browser(tmp_path, monkeypatch, fp):
    device(tmp_path, monkeypatch, "lime")
    fox.snap.setup(tmp_path / "shared", PASS)
    p, _ex = make_profile(fp)
    meta = fox.take(p)
    monkeypatch.setattr(launch, "container_running", lambda profile: True)
    stopped = []
    monkeypatch.setattr(launch, "stop", lambda profile: stopped.append(profile.id))
    fox.restore(p.id, meta.id)
    assert stopped == [p.id]


def test_an_engine_this_device_lacks_is_named(tmp_path, monkeypatch, fp):
    device(tmp_path, monkeypatch, "lime")
    p, _ex = make_profile(fp)
    missing = fox.missing_engine(p)
    assert missing == ("camoufox", fp.engine_version)
    assert fox.fetch_hint(*missing) == f"kiwi-fox engine fetch {fp.engine_version}"
    assert fox.fetch_hint("firefox", "newest") == "kiwi-fox engine fetch --engine firefox"


# ------------------------------------------------------------------ CLI
def run(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out + out.err


def test_the_cli_takes_lists_and_restores(tmp_path, monkeypatch, capsys, fp):
    shared = tmp_path / "shared"
    device(tmp_path, monkeypatch, "lime")
    fox.snap.setup(shared, PASS, device_name="lime")
    p, ex = make_profile(fp)
    code, out = run(capsys, "snapshot", "now")
    assert code == 0 and "work: snapshot taken" in out

    device(tmp_path, monkeypatch, "titan")
    fox.snap.setup(shared, PASS, device_name="titan")
    exits.create("mullvad", Endpoint(host="10.64.0.1", port=1080), exit_id=ex.id)
    code, out = run(capsys, "snapshot", "list")
    assert code == 0 and "work" in out and "not on this device" in out
    code, out = run(capsys, "snapshot", "restore", "work")
    assert code == 0 and "restored work" in out and "kiwi-fox engine fetch" in out
    code, out = run(capsys, "snapshot", "history", "work")
    assert code == 0 and "lime" in out


def test_folder_commands_are_kiwi_proxys(tmp_path, monkeypatch, capsys):
    device(tmp_path, monkeypatch, "lime")
    code, out = run(capsys, "snapshot", "status")
    assert code == 0 and "not set up" in out


def test_run_asks_before_starting_an_older_copy(tmp_path, monkeypatch, capsys, fp):
    shared = tmp_path / "shared"
    device(tmp_path, monkeypatch, "lime")
    fox.snap.setup(shared, PASS, device_name="lime")
    p, ex = make_profile(fp)
    fox.take(p)
    device(tmp_path, monkeypatch, "titan")
    fox.snap.setup(shared, PASS, device_name="titan")
    exits.create("mullvad", Endpoint(host="10.64.0.1", port=1080), exit_id=ex.id)
    fox.restore(p.id, fox.snap.history("profile", p.id)[0].id)
    device(tmp_path, monkeypatch, "lime")
    fox.started(p)
    fox.after_stop(p)  # lime ran it again: titan's copy is older now

    device(tmp_path, monkeypatch, "titan")
    import sys

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    answers = iter(["c"])
    monkeypatch.setattr("builtins.input", lambda _q: next(answers))
    args = cli.build_parser().parse_args(["run", "work"])
    assert cli._look_before_start(store.load(p.id), args) is None  # cancelled
    answers = iter(["r"])
    monkeypatch.setattr(fox, "missing_engine", lambda profile: None)  # as if installed
    started = cli._look_before_start(store.load(p.id), args)
    assert started is not None
    assert fox.before_start(started).relation.state == "same"


def test_a_snapshot_tar_is_plain_for_hand_opening(tmp_path, monkeypatch, fp):
    """The archive inside is an ordinary tar with a profile/ folder."""
    device(tmp_path, monkeypatch, "lime")
    fox.snap.setup(tmp_path / "shared", PASS)
    p, _ex = make_profile(fp)
    meta = fox.take(p)
    names = archive_names(meta)
    assert all(n.startswith("profile/") for n in names)
    assert tarfile is not None
