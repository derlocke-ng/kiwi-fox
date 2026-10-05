"""The SOCKS5 relay, exercised against a fake upstream.

Written after a real bug: the relay decoded domain targets with the "idna"
codec, which raises when given an `errors` argument, so every connection
addressed by *name* died while IP-addressed ones kept working — a failure that
looked exactly like broken DNS.
"""

from __future__ import annotations

import asyncio
import importlib.util
import socket
import struct
from pathlib import Path

import pytest

SRC = Path(__file__).parents[2] / "containers" / "gateway" / "forwarder.py"
spec = importlib.util.spec_from_file_location("kf_forwarder", SRC)
assert spec and spec.loader
fwd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fwd)

PAYLOAD = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nhi"


class FakeUpstream:
    """Minimal SOCKS5 server that records what it was asked for."""

    def __init__(self) -> None:
        self.requests: list[tuple[int, bytes, int]] = []
        self.server: asyncio.Server | None = None

    async def start(self) -> int:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        return self.server.sockets[0].getsockname()[1]

    async def _handle(self, r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        ver, n = await r.readexactly(2)
        await r.readexactly(n)
        w.write(bytes([5, 0]))
        await w.drain()
        _ver, _cmd, _rsv, atyp = await r.readexactly(4)
        if atyp == 1:
            host = await r.readexactly(4)
        elif atyp == 3:
            host = await r.readexactly((await r.readexactly(1))[0])
        else:
            host = await r.readexactly(16)
        port = struct.unpack("!H", await r.readexactly(2))[0]
        self.requests.append((atyp, host, port))
        w.write(bytes([5, 0, 0, 1]) + b"\x00\x00\x00\x00\x00\x00")
        w.write(PAYLOAD)
        await w.drain()
        w.close()


async def _roundtrip(atyp: int, target: bytes, port: int = 443):
    upstream = FakeUpstream()
    up_port = await upstream.start()
    up = fwd.Upstream("127.0.0.1", up_port, None, None)
    server = await asyncio.start_server(lambda r, w: fwd.handle(r, w, up), "127.0.0.1", 0)
    local_port = server.sockets[0].getsockname()[1]

    reader, writer = await asyncio.open_connection("127.0.0.1", local_port)
    writer.write(b"\x05\x01\x00")
    await writer.drain()
    assert await reader.readexactly(2) == bytes([5, 0])
    if atyp == 3:
        req = bytes([5, 1, 0, atyp, len(target)]) + target
    else:
        req = bytes([5, 1, 0, atyp]) + target
    writer.write(req + struct.pack("!H", port))
    await writer.drain()
    reply = await reader.readexactly(4)
    rest = {1: 6, 3: 0, 4: 18}[reply[3]]
    if rest:
        await reader.readexactly(rest)
    body = await reader.read(len(PAYLOAD))
    writer.close()
    server.close()
    upstream.server.close()  # type: ignore[union-attr]
    return reply, body, upstream.requests


def test_domain_target_relays():
    reply, body, requests = asyncio.run(_roundtrip(3, b"example.com"))
    assert reply[1] == 0, "a hostname CONNECT must succeed"
    assert body == PAYLOAD
    assert requests == [(3, b"example.com", 443)]


def test_internationalised_domain_does_not_crash_the_handler():
    # Already punycoded by the client; nothing here may try to re-decode it.
    reply, body, requests = asyncio.run(_roundtrip(3, b"xn--bcher-kva.example"))
    assert reply[1] == 0
    assert requests[0][1] == b"xn--bcher-kva.example"


def test_ipv4_target_relays_as_ipv4():
    raw = socket.inet_aton("93.184.216.34")
    reply, body, requests = asyncio.run(_roundtrip(1, raw, port=80))
    assert reply[1] == 0
    # Passed through as IPv4, not re-encoded as a numeric "hostname": an
    # upstream is entitled to reject that.
    assert requests == [(1, raw, 80)]


def test_ipv6_target_relays_as_ipv6():
    raw = socket.inet_pton(socket.AF_INET6, "2606:2800:220:1:248:1893:25c8:1946")
    reply, _body, requests = asyncio.run(_roundtrip(4, raw))
    assert reply[1] == 0
    assert requests == [(4, raw, 443)]


def test_credentials_come_from_a_file_not_the_environment(tmp_path):
    creds = tmp_path / "endpoint.creds"
    creds.write_text("someuser\nsomepass\n")
    assert fwd.read_credentials(str(creds)) == ("someuser", "somepass")


def test_missing_credentials_file_means_no_auth(tmp_path):
    assert fwd.read_credentials(str(tmp_path / "absent")) == (None, None)


def test_empty_credentials_mean_no_auth(tmp_path):
    creds = tmp_path / "c"
    creds.write_text("\n\n")
    assert fwd.read_credentials(str(creds)) == (None, None)


@pytest.mark.parametrize("cmd", [2, 3])
def test_bind_and_udp_associate_are_refused(cmd):
    # SOCKS5 UDP is unavailable upstream anyway; refuse rather than hang.
    async def go():
        up = fwd.Upstream("127.0.0.1", 1, None, None)
        server = await asyncio.start_server(lambda r, w: fwd.handle(r, w, up), "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"\x05\x01\x00")
        await reader.readexactly(2)
        writer.write(bytes([5, cmd, 0, 3, 11]) + b"example.com" + struct.pack("!H", 443))
        await writer.drain()
        reply = await reader.readexactly(4)
        writer.close()
        server.close()
        return reply

    assert asyncio.run(go())[1] != 0, "non-CONNECT commands must be refused"
