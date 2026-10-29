"""Assertions on a live profile's browser container.

The namespace itself — the kill switch, the one permitted destination, DNS
through the exit, the blocklist — is kiwi-proxy's, and so are those leak tests
(kiwi-proxy `tests/leak/`; run them with `--exit <profile name>`). What is
left here is what kiwi-fox adds: the browser that joins it.

Every one of these was verified by hand on the dev machine before being written
down; they exist so a regression cannot pass silently.
"""

import pytest
from kiwi_proxy import podman

from kiwi_fox.core import paths


def test_browser_container_has_no_capabilities(running_profile):
    name = paths.browser_name(running_profile.id)
    if not podman.is_running(name):
        pytest.skip("browser not running")
    caps = podman._run(
        ["inspect", name, "--format", "{{.EffectiveCaps}}"], check=False
    ).stdout.strip()
    # Only SYS_CHROOT, and only because Firefox's content sandbox needs it to
    # chroot content processes. Anything else is a regression.
    extra = [
        c
        for c in caps.strip("[]").replace(",", " ").split()
        if c.upper().removeprefix("CAP_") != "SYS_CHROOT"
    ]
    assert not extra, f"browser holds unexpected capabilities: {caps}"


def test_browser_has_no_network_namespace_of_its_own(running_profile):
    name = paths.browser_name(running_profile.id)
    if not podman.is_running(name):
        pytest.skip("browser not running")
    mode = podman._run(
        ["inspect", name, "--format", "{{.HostConfig.NetworkMode}}"], check=False
    ).stdout.strip()
    assert mode.startswith("container:"), f"browser must join the gateway netns, got {mode!r}"
