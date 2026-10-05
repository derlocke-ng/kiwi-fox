import pytest

from kiwi_fox.core import paths, podman, store


def pytest_addoption(parser):
    parser.addoption(
        "--profile", action="store", default=None, help="name of a running profile to probe"
    )


@pytest.fixture(scope="session")
def running_profile(pytestconfig):
    """These tests probe a *live* namespace; they cannot be faked."""
    if not podman.available():
        pytest.skip("podman unavailable")
    ref = pytestconfig.getoption("--profile")
    candidates = [store.resolve_ref(ref)] if ref else store.list_profiles()
    for p in candidates:
        if podman.is_running(paths.gateway_name(p.id)):
            return p
    pytest.skip("no running profile; start one with `kiwi-fox run <name>`")


@pytest.fixture(scope="session")
def gateway(running_profile):
    return paths.gateway_name(running_profile.id)


def sh(container: str, script: str) -> str:
    return podman.exec_(container, ["sh", "-c", script]).stdout.strip()


def dig_status(container: str, name: str) -> str:
    out = sh(container, f"dig +time=10 @127.0.0.2 {name} 2>&1")
    for line in out.splitlines():
        if "status:" in line:
            return line.split("status:")[1].split(",")[0].strip()
    return "NO-RESPONSE"
