"""What a release must agree on with itself."""

import re
import tomllib
from pathlib import Path

import pytest

import kiwi_fox
from kiwi_fox import cli

ROOT = Path(__file__).resolve().parents[2]


def manifest() -> dict[str, str]:
    out = {}
    for line in (ROOT / "kiwi.manifest").read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            out[key] = value
    return out


def test_one_version_everywhere(capsys):
    # kiwi installs the latest tag and shows the manifest's VERSION; the tool, the
    # package metadata and the manifest must not drift apart.
    version = manifest()["VERSION"]
    assert re.fullmatch(r"[0-9]+(\.[0-9]+){0,3}", version), "kiwi only follows plain version tags"
    assert kiwi_fox.__version__ == version
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert pyproject["project"]["version"] == version
    with pytest.raises(SystemExit) as stop:
        cli.build_parser().parse_args(["--version"])
    assert stop.value.code == 0
    assert capsys.readouterr().out.strip() == f"kiwi-fox {version}"


def test_manifest_follows_the_kiwi_convention():
    m = manifest()
    for key in ("NAME", "DESCRIPTION", "VERSION", "AUTHOR", "HOMEPAGE", "LICENSE", "COMPONENTS",
                "CATEGORY", "SCOPES", "INSTALLER"):  # fmt: skip
        assert m.get(key), f"{key} is missing or empty"
    assert m["NAME"] == "kiwi-fox"
    assert m["SCOPES"] == "user", "rootless podman needs no root; a system scope would be a lie"
    # A value runs to the end of the line, so a trailing comment becomes part of it.
    assert not any("#" in value for value in m.values())
    # Everything the manifest points at has to exist in the repo: kiwi reads these
    # from the clone and fetches nothing.
    for key in ("ICON", "ABOUT", "INSTALLER"):
        assert (ROOT / m[key]).is_file(), f"{key}={m[key]} does not exist"
    for shot in m.get("SCREENSHOTS", "").split():
        assert (ROOT / shot).is_file(), f"screenshot {shot} does not exist"
    assert (ROOT / "LICENSE").is_file()


def test_the_package_carries_its_data_files():
    # install.sh copies src/kiwi_fox and nothing else; anything read at runtime
    # has to live inside it.
    pkg = Path(kiwi_fox.__file__).parent
    assert (pkg / "core" / "probe.html").is_file()
    assert (pkg / "core" / "fingerprint" / "data" / "webgl-windows.json").is_file()
