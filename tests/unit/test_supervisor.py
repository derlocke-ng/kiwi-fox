"""The container's launcher as process 1 (containers/browser/entrypoint.sh):
starting, quitting and keeping, against a fake engine — a shell script that
records its arguments and runs until told to stop."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "containers" / "browser" / "entrypoint.sh"

FAKE_ENGINE = """#!/bin/sh
printf '%s\\n' "$@" > "$HOME/args.txt"
[ -n "${FAKE_EXIT:-}" ] && exit "$FAKE_EXIT"
trap 'exit 0' TERM
while :; do sleep 0.05; done
"""


@pytest.fixture
def box(tmp_path):
    engine = tmp_path / "engine"
    engine.mkdir()
    (engine / "camoufox").write_text(FAKE_ENGINE)
    (engine / "camoufox").chmod(0o755)
    (engine / "gfxtest").write_text("#!/bin/sh\n")
    (engine / "gfxtest").chmod(0o755)
    control = tmp_path / "control"
    control.mkdir()
    profile = tmp_path / "profile"
    procs = []

    def start(*args, start_browser=True, **env):
        e = {
            "PATH": os.environ["PATH"],
            "KF_ENGINE_DIR": str(engine),
            "KF_ENGINE_BIN": "camoufox",
            "KF_PROFILE_DIR": str(profile),
            "KF_CONTROL": str(control),
            "KF_START_BROWSER": "1" if start_browser else "0",
            **env,
        }
        proc = subprocess.Popen(
            ["bash", str(SCRIPT), *args], env=e, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        procs.append(proc)
        return proc

    yield start, control, profile
    for proc in procs:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def state(control: Path) -> str:
    try:
        return (control / "browser").read_text().strip()
    except OSError:
        return ""


def until(cond, timeout=5.0) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return
        time.sleep(0.05)
    raise AssertionError("timed out")


def test_the_browser_starts_and_the_container_ends_with_it(box):
    start, control, profile = box
    proc = start("--name", "kf.work")
    until(lambda: state(control).startswith("open "))
    until(lambda: (profile / "args.txt").exists())
    args = (profile / "args.txt").read_text().split()
    assert args[:3] == ["-profile", str(profile), "-no-remote"] and args[3:] == [
        "--name",
        "kf.work",
    ]
    proc.send_signal(signal.SIGUSR2)  # Quit browser
    assert proc.wait(5) == 0
    assert state(control) == "closed 0"


def test_kept_it_waits_for_the_next_browser(box):
    start, control, profile = box
    (control / "keep").touch()
    proc = start("--name", "kf.work", start_browser=False)
    until(lambda: state(control) == "closed -")
    (profile / ".parentlock").parent.mkdir(parents=True, exist_ok=True)
    (profile / ".parentlock").write_text("stale")
    (control / "url").write_text("https://example.com/\n")
    proc.send_signal(signal.SIGUSR1)  # Start browser
    until(lambda: state(control).startswith("open "))
    until(lambda: (profile / "args.txt").exists())
    assert (profile / "args.txt").read_text().split()[-1] == "https://example.com/"
    assert not (control / "url").exists() and not (profile / ".parentlock").exists()
    proc.send_signal(signal.SIGUSR2)
    until(lambda: state(control) == "closed 0")
    time.sleep(1.5)
    assert proc.poll() is None  # kept
    (profile / "args.txt").unlink()
    proc.send_signal(signal.SIGUSR1)  # again, without pages
    until(lambda: state(control).startswith("open "))
    until(lambda: (profile / "args.txt").exists())
    assert (profile / "args.txt").read_text().split()[-1] == "kf.work"
    proc.send_signal(signal.SIGTERM)  # Stop container: the browser goes too
    assert proc.wait(5) == 0
    assert state(control) == "closed 0"


def test_a_crashed_browser_ends_the_container_with_its_code(box):
    start, control, _profile = box
    proc = start(FAKE_EXIT="3")
    assert proc.wait(5) == 3
    assert state(control) == "closed 3"


def test_without_a_control_folder_the_engine_is_process_1(box, tmp_path):
    start, control, profile = box
    proc = start("--x", KF_CONTROL="")
    until(lambda: (profile / "args.txt").exists())
    assert not (control / "browser").exists()
    proc.send_signal(signal.SIGTERM)
    assert proc.wait(5) == 0
