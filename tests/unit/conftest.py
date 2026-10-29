import datetime as dt
from types import SimpleNamespace

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
def fake_proxy(monkeypatch):
    """kiwi-proxy at its boundary: gateways come up at once, containers are
    recorded instead of run. What kiwi-proxy does inside up() is its own tests'
    business; these check what kiwi-fox asks of it."""
    from kiwi_proxy import gateway, podman

    from kiwi_fox.core import paths

    rec = SimpleNamespace(
        plans=[], ups=[], released=[], downed=[], started=[], removed=[], running=set()
    )
    rec.plan = gateway.EndpointPlan("203.0.113.9", 1080, "pasta", None, [])

    def plan(ex, password=None, *, measure=True):
        rec.plans.append(SimpleNamespace(exit=ex, password=password, measure=measure))
        return rec.plan

    def up(ex, *, password=None, labels=None, measure=True, **_k):
        rec.ups.append(SimpleNamespace(exit=ex, password=password, labels=labels, measure=measure))
        return gateway.Gateway(
            exit_id=ex.id,
            name=paths.gateway_name(ex.id),
            resolv_conf="/run/kiwi-proxy/resolv.conf" if ex.dns.mode == "resolver" else None,
            notes=["gateway up"],
        )

    def release(exit_id, *, ignore=()):
        rec.released.append((exit_id, tuple(ignore)))
        return True

    def start(spec, **_k):
        rec.started.append(spec)
        return spec.name

    monkeypatch.setattr(gateway, "plan", plan)
    monkeypatch.setattr(gateway, "up", up)
    monkeypatch.setattr(gateway, "release", release)
    monkeypatch.setattr(gateway, "down", lambda exit_id: rec.downed.append(exit_id))
    monkeypatch.setattr(gateway, "reap", lambda: [])
    monkeypatch.setattr(podman, "available", lambda: True)
    monkeypatch.setattr(podman, "start", start)
    monkeypatch.setattr(podman, "rm", lambda name, **_k: rec.removed.append(name))
    monkeypatch.setattr(podman, "is_running", lambda name: name in rec.running)
    return rec


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
