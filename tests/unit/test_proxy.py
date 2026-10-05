import pytest

from kiwi_fox.core.proxy import ProxyError, parse, resolve


@pytest.mark.parametrize(
    ("spec", "host", "port", "user", "has_pw"),
    [
        ("socks5://1.2.3.4:1080", "1.2.3.4", 1080, None, False),
        ("socks5://u:p@1.2.3.4:1080", "1.2.3.4", 1080, "u", True),
        ("socks5h://u:p@host.example:9050", "host.example", 9050, "u", True),
        ("http://proxy:8080", "proxy", 8080, None, False),
        ("10.64.0.1:1080", "10.64.0.1", 1080, None, False),
        ("1.2.3.4:9050:user:sec:ret", "1.2.3.4", 9050, "user", True),
    ],
)
def test_parse(spec, host, port, user, has_pw):
    ep, pw = parse(spec)
    assert (ep.host, ep.port, ep.username) == (host, port, user)
    assert bool(pw) is has_pw
    assert ep.has_password is has_pw


def test_password_is_not_stored_on_the_endpoint():
    ep, pw = parse("socks5://u:topsecret@1.2.3.4:1080")
    assert "topsecret" not in ep.model_dump_json()
    assert pw == "topsecret"


@pytest.mark.parametrize("spec", ["", "nonsense", "ftp://h:21", "host:notaport", "socks5://h"])
def test_parse_rejects(spec):
    with pytest.raises(ProxyError):
        parse(spec)


def test_resolve_passes_literals_through():
    assert resolve("10.64.0.1") == "10.64.0.1"


def test_resolve_rejects_garbage():
    with pytest.raises(ProxyError):
        resolve("no-such-host.invalid")
