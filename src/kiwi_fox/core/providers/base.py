"""The provider contract: a module turns some upstream into a ready SOCKS5 exit.

Every provider module (tor, vpn, 9proxy, mysterium) adapts its upstream — the Tor
network, a VPN tunnel, a residential-proxy account, a Mysterium node — into plain
SOCKS5 and exposes nothing else. That is the load-bearing network decision (see
docs/decisions.md, "Every provider exposes SOCKS5 and nothing else"): the gateway,
forwarder, firewall rule and DNS design stay single-shaped, and adapting is the
module's job.

A local provider runs its own container with its own exit to the internet, on the
shared ``kf-providers`` bridge. It cannot share the gateway's network namespace —
the gateway default-drops everything but one destination, which would strand the
provider's own upstream — so the two meet on that bridge, and the gateway permits
exactly the provider's address on it. Plain, already-remote SOCKS5 endpoints never
touch any of this; those gateways stay on pasta.

``Provider`` is the interface kiwi-fox depends on. ``ContainerProvider`` implements
the whole container lifecycle generically, so a plugin only declares its manifest,
its container spec, and its leases. Plugins live in their own repositories and
import ``ContainerProvider`` from here; they are discovered under
``paths.modules_dir()`` by the loader.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from .. import paths, podman
from ..models import ContainerSpec, Endpoint, Lease, ProviderManifest, ProviderStatus


class ProviderError(RuntimeError):
    pass


@dataclass
class ProviderContext:
    """Everything host-side a provider is handed, so it never reaches into kiwi-fox
    internals directly. One context per module."""

    name: str
    module_dir: Path  # where the module is installed (modules_dir()/<name>)
    state_dir: Path  # per-module writable state (leases, caches)
    network: str  # the shared providers bridge
    image: str  # the provider image name (kiwi-fox/<name>:latest)
    socks_port: int

    def container_name(self, lease: str | None = None) -> str:
        return paths.provider_container_name(self.name, lease)

    def containerfile(self, subdir: str = "") -> Path:
        base = self.module_dir / "containers"
        return (base / subdir / "Containerfile") if subdir else (base / "Containerfile")

    # ------------------------------------------------------------- module secrets
    # Module-level credentials (a VPN WireGuard key, a 9proxy login) are not
    # per-profile, so they are stored as their own podman secrets and mounted into
    # the provider container. Per-profile credentials keep going through the
    # gateway forwarder, untouched.
    def secret_name(self, key: str) -> str:
        return f"{paths.PREFIX}-mod-{self.name}-{key}"

    def set_secret(self, key: str, value: str) -> None:
        podman.secret_set(self.secret_name(key), value)

    def secret_mount(self, key: str, target: str) -> tuple[str, str]:
        return (self.secret_name(key), target)


@runtime_checkable
class Provider(Protocol):
    """What kiwi-fox calls. A plugin usually gets all of this from
    ``ContainerProvider`` and overrides only ``container_spec`` and ``leases``."""

    manifest: ProviderManifest

    @property
    def name(self) -> str: ...

    def requirements(self) -> list[str]: ...

    def setup(self, ctx: ProviderContext) -> None: ...

    def leases(self, ctx: ProviderContext) -> list[Lease]: ...

    def up(
        self, ctx: ProviderContext, *, lease: str | None = None, country: str | None = None
    ) -> Endpoint: ...

    def down(self, ctx: ProviderContext, *, lease: str | None = None) -> None: ...

    def status(self, ctx: ProviderContext) -> ProviderStatus: ...


class ContainerProvider:
    """Base class for a provider that runs a container exposing SOCKS5 on the
    providers bridge. Subclasses declare ``manifest`` and implement
    ``container_spec`` (and usually ``leases``); everything else is generic.
    """

    manifest: ProviderManifest

    # How long to wait for a freshly started provider container to come up and
    # get an address on the bridge. VPN handshakes and Tor bootstraps are slow.
    ready_timeout: float = 90.0

    @property
    def name(self) -> str:
        return self.manifest.name

    def requirements(self) -> list[str]:
        return list(self.manifest.requires)

    # --------------------------------------------------------------- spec (abstract)
    def container_spec(
        self, ctx: ProviderContext, *, lease: str | None = None, country: str | None = None
    ) -> ContainerSpec:
        raise NotImplementedError(f"{self.name}: container_spec must be implemented")

    def leases(self, ctx: ProviderContext) -> list[Lease]:  # noqa: ARG002
        return []

    # --------------------------------------------------------------------- setup
    def setup(self, ctx: ProviderContext) -> None:
        """Build the provider image from the module's Containerfile, or pull it
        when the manifest names a remote image. Idempotent."""
        cf = ctx.containerfile()
        if cf.exists():
            podman.build(
                ctx.image,
                str(cf),
                str(cf.parent),
                labels={"app": "kiwi-fox", "kiwi-fox.module": self.name},
            )
            return
        if self.manifest.image and "/" in self.manifest.image:
            podman.pull(self.manifest.image)
            return
        raise ProviderError(
            f"{self.name}: no Containerfile at {cf} and no pullable image in the manifest"
        )

    # ------------------------------------------------------------------- lifecycle
    def up(
        self, ctx: ProviderContext, *, lease: str | None = None, country: str | None = None
    ) -> Endpoint:
        """Bring the provider up (idempotent) and return its live SOCKS5 endpoint.

        The host is the container's current address on the bridge, resolved every
        time because a restart can change it; the gateway needs a literal address.
        """
        if not podman.available():
            raise ProviderError("podman not found")
        podman.network_ensure(ctx.network)
        spec = self.container_spec(ctx, lease=lease, country=country)
        if spec.network != ctx.network:
            raise ProviderError(
                f"{self.name}: container_spec must attach to {ctx.network!r}, got {spec.network!r}"
            )
        if not podman.is_running(spec.name):
            podman.start(spec)
        ip = self._await_ready(ctx, spec.name)
        return Endpoint(
            host=ip,
            port=self.manifest.socks_port,
            username=None,  # per-profile isolation/account creds are set at launch
            has_password=False,
            module=self.name,
            lease=lease,
        )

    def _await_ready(self, ctx: ProviderContext, container: str) -> str:
        deadline = time.monotonic() + self.ready_timeout
        last = ""
        while time.monotonic() < deadline:
            if not podman.is_running(container):
                raise ProviderError(
                    f"{self.name}: provider container exited during start:\n"
                    + podman.logs(container)
                )
            ip = podman.container_ip(container, ctx.network)
            if ip and self.ready(ctx, container):
                return ip
            last = ip or last
            time.sleep(0.5)
        raise ProviderError(
            f"{self.name}: provider did not become ready within {self.ready_timeout:.0f}s"
            + (f" (address {last})" if last else "")
        )

    def ready(self, ctx: ProviderContext, container: str) -> bool:  # noqa: ARG002
        """True when the SOCKS5 listener is accepting connections. The default
        trusts a running container; providers with a slow handshake (a VPN tunnel,
        a Tor bootstrap) should override to probe the port."""
        return True

    def down(self, ctx: ProviderContext, *, lease: str | None = None) -> None:
        podman.rm(ctx.container_name(lease))

    def status(self, ctx: ProviderContext) -> ProviderStatus:
        running = [
            c.get("Names", [""])[0]
            for c in podman.ps()
            if c.get("Labels", {}).get("kiwi-fox.module") == self.name
            and c.get("State") == "running"
        ]
        return ProviderStatus(
            name=self.name,
            installed=True,
            image_present=podman.image_exists(ctx.image),
            running=bool(running),
            containers=running,
            leases=[lease.id for lease in _safe_leases(self, ctx)],
        )


def _safe_leases(provider: Provider, ctx: ProviderContext) -> list[Lease]:
    try:
        return provider.leases(ctx)
    except Exception:  # noqa: BLE001 - status must never raise
        return []
