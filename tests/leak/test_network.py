"""Kill-switch and DNS assertions against a live profile namespace.

Every one of these was verified by hand on the dev machine before being written
down; they exist so a regression cannot pass silently.
"""

import pytest

from kiwi_fox.core import paths

from .conftest import dig_status, sh

# A domain present in oisd big, and one that must keep working.
BLOCKED = "accounts.doubleclick.net"
BLOCKED_APEX = "0-02.net"
ALLOWED = "wikipedia.org"


def test_direct_egress_is_blocked(gateway):
    for target in ("1.1.1.1/443", "8.8.8.8/53", "9.9.9.9/443"):
        out = sh(
            gateway,
            f'timeout 5 bash -c "echo > /dev/tcp/{target}" 2>/dev/null && echo LEAK || echo blocked',
        )
        assert out == "blocked", f"egress to {target} was not blocked"


def _permitted_destination(gateway) -> tuple[str, str]:
    """The address the gateway's firewall actually permits, read from the gateway
    itself. For a plain endpoint this equals the profile's endpoint; for a managed
    local provider it is the provider's live bridge address (resolved at launch),
    which the stored endpoint host does NOT equal — so read the live value rather
    than assuming the two are the same."""
    ip = sh(gateway, "printenv KF_ENDPOINT_IP")
    port = sh(gateway, "printenv KF_ENDPOINT_PORT")
    return ip, port


def test_the_proxy_endpoint_is_reachable(gateway):
    ip, port = _permitted_destination(gateway)
    assert ip and port, "gateway is missing KF_ENDPOINT_IP/PORT"
    out = sh(
        gateway,
        f'timeout 5 bash -c "echo > /dev/tcp/{ip}/{port}" 2>/dev/null && echo ok || echo unreachable',
    )
    assert out == "ok", "the one permitted destination must be reachable"


def test_only_the_permitted_destination_is_reachable_on_its_segment(gateway):
    # On the kf-providers bridge the gateway has on-link neighbours (the bridge's
    # own gateway, sibling provider/gateway containers) that routing alone would
    # not stop — only the nftables default-drop does. Prove a neighbour one address
    # away from the permitted provider is still blocked. (On a plain pasta endpoint
    # this neighbour is simply dropped too, so the assertion holds either way.)
    ip, port = _permitted_destination(gateway)
    if ip.count(".") != 3:
        pytest.skip(f"not an IPv4 permitted destination: {ip!r}")
    octets = ip.split(".")
    last = int(octets[3])
    octets[3] = str((last + 1) % 256 if last != 1 else 2)
    neighbour = ".".join(octets)
    out = sh(
        gateway,
        f'timeout 5 bash -c "echo > /dev/tcp/{neighbour}/{port}" 2>/dev/null && echo LEAK || echo blocked',
    )
    assert out == "blocked", f"a non-permitted on-link neighbour {neighbour} was reachable"


def test_udp_dns_cannot_leave(gateway):
    # SOCKS5 carries no UDP, so nothing should even try; prove it cannot.
    out = sh(gateway, "timeout 5 dig +time=3 +tries=1 @8.8.8.8 example.com 2>&1 | tail -1")
    assert "connection timed out" in out or "no servers could be reached" in out, out


def test_nft_is_dropping(gateway):
    out = sh(gateway, "nft list ruleset | grep -A1 'kf-dropped' | head -2")
    assert "packets" in out
    dropped = int(out.split("packets")[1].split()[0])
    assert dropped > 0, "nothing was dropped; is the ruleset actually loaded?"


def test_resolver_answers_through_the_proxy(gateway):
    assert dig_status(gateway, ALLOWED) == "NOERROR"
    answer = sh(gateway, f"dig +short +time=10 @127.0.0.2 {ALLOWED} | head -1")
    assert answer and answer[0].isdigit(), f"no address for {ALLOWED}: {answer!r}"


@pytest.mark.parametrize("name", [BLOCKED, BLOCKED_APEX])
def test_blocklist_refuses(gateway, name):
    assert dig_status(gateway, name) == "REFUSED"


def test_blocklist_covers_subdomains(gateway):
    # oisd's bare-domain entries must match subdomains too, which is exactly
    # dnscrypt-proxy's bare-name rule and why domainswild2 is the right format.
    assert dig_status(gateway, f"deeper.sub.{BLOCKED_APEX}") == "REFUSED"


def test_browser_container_has_no_capabilities(running_profile):
    from kiwi_fox.core import podman

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
    from kiwi_fox.core import podman

    name = paths.browser_name(running_profile.id)
    if not podman.is_running(name):
        pytest.skip("browser not running")
    mode = podman._run(
        ["inspect", name, "--format", "{{.HostConfig.NetworkMode}}"], check=False
    ).stdout.strip()
    assert mode.startswith("container:"), f"browser must join the gateway netns, got {mode!r}"
