import pytest
from kiwi_proxy import podman

from kiwi_fox.core import paths, store


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
