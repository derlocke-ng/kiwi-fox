import datetime as dt

import pytest

from kiwi_fox.core.fingerprint import generate
from kiwi_fox.core.models import Endpoint, Profile

ENGINE = "152.0.4"


@pytest.fixture(autouse=True)
def _hermetic(tmp_path, monkeypatch):
    """No test reads or writes the real profile store, and none depends on which
    GPU or window size this particular machine happens to have: a fingerprint
    drawn here must be the same one drawn anywhere."""
    for var in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME"):
        monkeypatch.setenv(var, str(tmp_path / var.lower()))
    from kiwi_fox.core import gpu

    monkeypatch.setattr(
        gpu, "plan", lambda prefer=None: gpu.Plan("mesa", ("/dev/dri/renderD128",), {}, None, "")
    )
    monkeypatch.setattr("kiwi_fox.core.desktop.prefers_dark", lambda: None)

    def langpack(version, locale):  # never the network: a stand-in for Mozilla's file
        pack = tmp_path / "langpacks" / version / f"{locale}.xpi"
        pack.parent.mkdir(parents=True, exist_ok=True)
        pack.write_bytes(f"langpack {locale} {version}".encode())
        return pack

    monkeypatch.setattr("kiwi_fox.core.engines.fetch.langpack", langpack)


@pytest.fixture
def fp():
    return generate(engine_version=ENGINE, country="DE", seed="a" * 32)


@pytest.fixture
def profile():
    return Profile(
        id="11111111-2222-3333-4444-555555555555",
        name="work",
        created=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        endpoint=Endpoint(host="10.64.0.1", port=1080),
    )
