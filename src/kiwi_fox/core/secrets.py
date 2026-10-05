"""Secret Service via `secret-tool`. Passwords never touch JSON, logs or env."""

from __future__ import annotations

import shutil
import subprocess

SCHEMA = "org.kiwi-fox.Endpoint"


def available() -> bool:
    return shutil.which("secret-tool") is not None


def _attrs(profile_id: str) -> list[str]:
    return ["profile", profile_id]


def store(profile_id: str, password: str, label: str = "kiwi-fox endpoint") -> None:
    if not available():
        raise RuntimeError("secret-tool not found; install libsecret to store credentials")
    subprocess.run(  # noqa: S603
        ["secret-tool", "store", "--label", label, *_attrs(profile_id)],
        input=password,
        text=True,
        check=True,
        capture_output=True,
    )


def lookup(profile_id: str) -> str | None:
    if not available():
        return None
    proc = subprocess.run(  # noqa: S603
        ["secret-tool", "lookup", *_attrs(profile_id)],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout if proc.returncode == 0 and proc.stdout else None


def clear(profile_id: str) -> None:
    if available():
        subprocess.run(  # noqa: S603
            ["secret-tool", "clear", *_attrs(profile_id)], check=False, capture_output=True
        )
