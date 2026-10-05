#!/usr/bin/env python3
"""SOCKS5 relay: accepts unauthenticated local connections, adds the upstream's
credentials on the way out.

Firefox prefs cannot authenticate against SOCKS5, and 9proxy's local ports
should have auth on, so this exists to hold the credential where the browser
cannot read it. It is also the single destination the firewall has to permit,
and the per-profile isolation knob: sending distinct credentials per profile to
a Tor SOCKS port triggers IsolateSOCKSAuth so profiles do not share circuits.

stdlib only.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import socket
import struct
import sys
from pathlib import Path

LOG = logging.getLogger("forwarder")

VER = 0x05
NO_AUTH = 0x00
USER_PASS = 0x02
CMD_CONNECT = 0x01
ATYP_IPV4, ATYP_DOMAIN, ATYP_IPV6 = 0x01, 0x03, 0x04
REP_OK, REP_GENERAL, REP_NOT_ALLOWED, REP_REFUSED, REP_CMD = 0x00, 0x01, 0x02, 0x05, 0x07


class Upstream:
    def __init__(self, host: str, port: int, user: str | None, password: str | None) -> None:
        self.host, self.port = host, port
        self.user, self.password = user or None, password or None

    @property
    def authed(self) -> bool:
        return bool(self.user)


async def _read(reader: asyncio.StreamReader, n: int) -> bytes:
    return await reader.readexactly(n)


def _describe(atyp: int, raw: bytes) -> str:
    """Human-readable target, for logs only — never fed back into the protocol."""
    if atyp == ATYP_IPV4:
        return socket.inet_ntoa(raw)
    if atyp == ATYP_IPV6:
        return socket.inet_ntop(socket.AF_INET6, raw)
    return raw.decode("ascii", "replace")


async def socks5_handshake(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter, up: Upstream
) -> None:
    """Negotiate with the upstream as a SOCKS5 client."""
    methods = bytes([USER_PASS]) if up.authed else bytes([NO_AUTH])
    writer.write(bytes([VER, len(methods)]) + methods)
    await writer.drain()
    ver, method = await _read(reader, 2)
    if ver != VER:
        raise OSError("upstream is not SOCKS5")
    if method == USER_PASS:
        if not up.authed:
            raise OSError("upstream demands credentials but none are configured")
        u = up.user.encode()  # type: ignore[union-attr]
        p = (up.password or "").encode()
        writer.write(bytes([0x01, len(u)]) + u + bytes([len(p)]) + p)
        await writer.drain()
        _, status = await _read(reader, 2)
        if status != 0x00:
            raise OSError("upstream rejected the credentials")
    elif method != NO_AUTH:
        raise OSError(f"upstream demands unsupported auth {method:#x}")


async def pipe(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
    """Relay one direction, then propagate the half-close.

    Closing `dst` outright here would tear down the other direction while it is
    still in use; signalling EOF instead lets each side finish and close on its
    own, which is what stops connections accumulating.
    """
    try:
        while chunk := await src.read(65536):
            dst.write(chunk)
            await dst.drain()
    except (ConnectionError, asyncio.IncompleteReadError, OSError):
        pass
    finally:
        with contextlib.suppress(OSError, NotImplementedError):
            if dst.can_write_eof():
                dst.write_eof()


async def shutdown(*writers: asyncio.StreamWriter) -> None:
    for w in writers:
        with contextlib.suppress(OSError):
            w.close()
    for w in writers:
        with contextlib.suppress(OSError, ConnectionError, asyncio.CancelledError):
            await w.wait_closed()


async def handle(
    client_r: asyncio.StreamReader, client_w: asyncio.StreamWriter, up: Upstream
) -> None:
    peer = client_w.get_extra_info("peername")
    try:
        ver, nmethods = await _read(client_r, 2)
        if ver != VER:
            client_w.close()
            return
        await _read(client_r, nmethods)
        client_w.write(bytes([VER, NO_AUTH]))  # local side needs no auth
        await client_w.drain()

        ver, cmd, _rsv, atyp = await _read(client_r, 4)
        # Keep the target as bytes and forward it verbatim. Domain names in
        # SOCKS5 are already punycoded ASCII, so there is nothing to decode —
        # and decoding with the "idna" codec raises, because that codec rejects
        # an `errors` argument. That bug closed every connection addressed by
        # name while IP-addressed ones (dnscrypt-proxy's own) kept working,
        # which looked exactly like a DNS fault.
        if atyp == ATYP_IPV4:
            host_bytes = await _read(client_r, 4)
        elif atyp == ATYP_DOMAIN:
            length = (await _read(client_r, 1))[0]
            host_bytes = await _read(client_r, length)
        elif atyp == ATYP_IPV6:
            host_bytes = await _read(client_r, 16)
        else:
            await deny(client_w, REP_GENERAL)
            return
        port = struct.unpack("!H", await _read(client_r, 2))[0]
        host = _describe(atyp, host_bytes)

        if cmd != CMD_CONNECT:
            # No BIND, no UDP ASSOCIATE: SOCKS5 UDP is unavailable upstream anyway.
            await deny(client_w, REP_CMD)
            return

        try:
            up_r, up_w = await asyncio.wait_for(
                asyncio.open_connection(up.host, up.port), timeout=20
            )
        except (TimeoutError, OSError) as exc:
            LOG.warning("upstream unreachable: %s", exc)
            await deny(client_w, REP_REFUSED)
            return

        try:
            await socks5_handshake(up_r, up_w, up)
            # Pass the address through in the form the client used, rather than
            # re-encoding everything as a domain: an upstream is entitled to
            # reject a numeric string sent as a hostname.
            if atyp == ATYP_DOMAIN:
                request = bytes([VER, CMD_CONNECT, 0x00, atyp, len(host_bytes)]) + host_bytes
            else:
                request = bytes([VER, CMD_CONNECT, 0x00, atyp]) + host_bytes
            up_w.write(request + struct.pack("!H", port))
            await up_w.drain()
            ver, rep, _rsv, atyp = await _read(up_r, 4)
            if atyp == ATYP_IPV4:
                await _read(up_r, 4 + 2)
            elif atyp == ATYP_DOMAIN:
                length = (await _read(up_r, 1))[0]
                await _read(up_r, length + 2)
            elif atyp == ATYP_IPV6:
                await _read(up_r, 16 + 2)
            if rep != REP_OK:
                LOG.info("upstream refused %s:%s (code %s)", host, port, rep)
                await deny(client_w, rep)
                up_w.close()
                return
        except (OSError, asyncio.IncompleteReadError) as exc:
            LOG.warning("upstream handshake failed: %s", exc)
            await deny(client_w, REP_GENERAL)
            up_w.close()
            return

        client_w.write(bytes([VER, REP_OK, 0x00, ATYP_IPV4]) + b"\x00\x00\x00\x00\x00\x00")
        await client_w.drain()
        try:
            await asyncio.gather(pipe(client_r, up_w), pipe(up_r, client_w))
        finally:
            await shutdown(up_w, client_w)
    except (asyncio.IncompleteReadError, ConnectionError):
        pass
    except Exception:
        LOG.exception("relay error for %s", peer)
    finally:
        await shutdown(client_w)


async def deny(writer: asyncio.StreamWriter, code: int) -> None:
    with contextlib.suppress(OSError, ConnectionError):
        writer.write(bytes([VER, code, 0x00, ATYP_IPV4]) + b"\x00\x00\x00\x00\x00\x00")
        await writer.drain()
        writer.close()


def read_credentials(path: str) -> tuple[str | None, str | None]:
    """0600 file, two lines. Never an env var: `podman inspect` shows env."""
    p = Path(path)
    if not p.exists():
        return None, None
    lines = p.read_text().splitlines()
    user = lines[0].strip() if lines else ""
    password = lines[1] if len(lines) > 1 else ""
    return (user or None), (password or None)


async def main() -> int:
    logging.basicConfig(level=logging.INFO, format="forwarder: %(message)s", stream=sys.stderr)
    host = os.environ.get("KF_ENDPOINT_IP")
    port = int(os.environ.get("KF_ENDPOINT_PORT", "0"))
    listen_port = int(os.environ.get("KF_FORWARDER_PORT", "1080"))
    creds = os.environ.get("KF_CREDS_FILE", "/run/kf/endpoint.creds")
    if not host or not port:
        LOG.error("KF_ENDPOINT_IP and KF_ENDPOINT_PORT are required")
        return 2
    user, password = read_credentials(creds)
    up = Upstream(host, port, user, password)
    server = await asyncio.start_server(
        lambda r, w: handle(r, w, up), "127.0.0.1", listen_port, reuse_address=True
    )
    LOG.info(
        "listening on 127.0.0.1:%s -> %s:%s (%s)",
        listen_port,
        host,
        port,
        "authenticated" if up.authed else "no auth",
    )
    async with server:
        await server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
