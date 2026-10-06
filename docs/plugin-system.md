# Provider plugin system

kiwi-fox turns a chosen upstream into one isolated browser identity. *Where* the
exit comes from — a plain SOCKS5 you were given, the Tor network, a VPN tunnel, a
residential-proxy account, a Mysterium node — is the job of a **provider module**.

A provider module is a small, self-contained plugin, shipped in its own repository
and installed through kiwi-updater. kiwi-fox discovers it, builds its container
image, brings it up on demand, and points a profile's gateway at it. The suite of
first-party modules:

| Module | Repository | Upstream | Account |
| --- | --- | --- | --- |
| `tor` | kiwi-plugin-tor | the Tor network | no |
| `vpn` | kiwi-plugin-vpn | a WireGuard/OpenVPN tunnel (gluetun) | yes (a VPN subscription) |
| `9proxy` | kiwi-plugin-9proxy | 9proxy residential exits | yes |
| `mysterium` | kiwi-plugin-myst | the Mysterium dVPN | identity (free) |

The same exit then serves the [kiwi-pentesting](https://github.com/derlocke-ng/kiwi-pentesting)
suite, which attaches its tool containers to the gateway a kiwi-fox identity
already created — browsing and testing share one IP.

## The one rule

**Every provider exposes SOCKS5 and nothing else.** Adapting its upstream into
plain SOCKS5 is the module's job, so the gateway, the credential forwarder, the
single firewall rule and the DNS design stay one shape. A VPN tunnel that only
offers an HTTP proxy ships a tiny SOCKS5 adapter alongside it; a provider that
speaks SOCKS5 natively (Tor) needs none.

## How a local provider is wired

A provider that runs its own container needs its own exit to the internet *and*
has to be reachable by the gateway that forwards into it. It cannot share the
gateway's network namespace — the gateway default-drops everything but one
destination, which would strand the provider's own upstream — so the two meet on a
shared podman bridge, `kf-providers`:

```
          kf-providers bridge (rootless)
   ┌──────────────┴───────────────┐
provider container            gateway container
(own exit to internet)        nftables: default drop,
SOCKS5 on <bridge-ip>:port    permit only <provider-ip>:port
                              forwarder 127.0.0.1:1080  ─┐
                              dnscrypt-proxy 127.0.0.2:53 │
                                                          ▼
                                         browser joins the gateway netns
```

kiwi-fox resolves the provider container's current bridge address every launch
(it can change across restarts) and passes that literal address to the gateway,
which permits exactly it. The kill switch is unchanged: if the gateway dies the
profile loses its route; if the provider dies the gateway's one permitted
destination stops answering.

A plain, already-remote SOCKS5 endpoint touches none of this — its gateway stays
on `pasta` and reaches the public address directly.

## What a module ships

Installed under `~/.local/share/kiwi-fox/modules/<name>/`:

```
provider.py          exposes PROVIDER (a Provider) and MANIFEST (a ProviderManifest)
containers/
  Containerfile      the provider image, built at setup time as kiwi-fox/<name>:latest
  entrypoint.sh      brings the upstream up and exposes SOCKS5
```

The module directory name is the module id — `tor`, `vpn`, `9proxy`, `mysterium` —
and must equal `MANIFEST.name`. It is loaded by file path, not by import name, so a
name that is not a legal Python identifier (`9proxy`) is fine.

## The contract

`provider.py` imports the contract from kiwi-fox (a runtime prerequisite, exactly as
for kiwi-pentesting) and usually subclasses `ContainerProvider`, which implements the
whole container lifecycle. A module then declares only its manifest, its container
spec, and its leases:

```python
from kiwi_fox.core.models import ContainerSpec, Lease, ProviderManifest
from kiwi_fox.core.providers.base import ContainerProvider

MANIFEST = ProviderManifest(
    name="tor",
    title="Tor",
    description="exit through the Tor network",
    socks_port=9050,
    auth="isolation",      # none | isolation | account
    needs_account=False,
    requires=[],           # host binaries `module doctor` checks for
)


class TorProvider(ContainerProvider):
    manifest = MANIFEST

    def container_spec(self, ctx, *, lease=None, country=None):
        return ContainerSpec(
            name=ctx.container_name(lease),
            image=ctx.image,
            network=ctx.network,          # must attach to the providers bridge
            env={...},
            labels={"kiwi-fox.module": self.name, "kiwi-fox.role": "provider"},
        )

    def leases(self, ctx):
        return [Lease(id="de", country="DE"), ...]


PROVIDER = TorProvider()
```

`ContainerProvider` gives you `up()` (ensure the bridge, start the container, wait
for an address, return the live `Endpoint`), `down()`, `status()`, and `setup()`
(build the image from `containers/Containerfile`, or pull one named in the
manifest). Override `ready()` when the upstream has a slow handshake — a VPN tunnel
or a Tor bootstrap — so kiwi-fox waits for the SOCKS5 port, not just a running
container.

### Credentials

Three auth modes, handled by kiwi-fox so the module never touches the keyring:

- **`none`** — the SOCKS5 takes no credentials.
- **`isolation`** — any user/pass is accepted and used only to separate circuits
  per profile. kiwi-fox mints a stable per-profile token and the gateway forwarder
  sends it (Tor `IsolateSOCKSAuth`), so each profile gets its own exit.
- **`account`** — fixed credentials you hold with the provider, given as the
  profile endpoint's own username/password and forwarded as usual.

Module-level secrets that are not per-profile (a VPN WireGuard key, a 9proxy login)
are stored as their own podman secrets via `ctx.set_secret(...)` and mounted into
the provider container; `kiwi-fox module setup <name>` is where a module collects
them.

## Using it

```sh
kiwi install kiwi-plugin-tor          # installs the module under modules_dir
kiwi-fox setup                        # builds kiwi-fox/tor:latest (among others)
kiwi-fox module list                  # installed modules
kiwi-fox module leases tor            # selectable exits, if any
kiwi-fox new work --module tor --country de   # provider produces the endpoint
#   or point a profile at an already-running provider:
kiwi-fox module up tor --lease de
kiwi-fox new work socks5://<ip>:9050 --module tor --lease de
kiwi-fox run work
kiwi-fox module doctor                # image present? binaries present? running?
```

A provider container is shared across every profile on the same module+lease and is
torn down only when no running gateway still uses it.

## Residual hardening (known, for follow-up)

The leak-proof guarantee for a managed provider still rests on the gateway's
nftables default-drop, exactly as for a plain endpoint. Moving the gateway onto a
shared bridge adds a few things worth hardening further; none weakens the single
permitted-destination rule, and the leak suite asserts it on the bridge
(`tests/leak/test_network.py`):

- **The gateway pins the provider's address once, at launch.** The provider's bridge
  IP is resolved on every launch and the gateway is recreated with it, so the common
  case is covered. But if a provider container restarts *while* a gateway is running
  and its IP is reused by another container, that gateway's nft rule is stale until
  the next launch. A gateway that re-resolves and re-pins during its lifetime would
  close this.
- **`kf-providers` is one shared, NAT'd L2 segment.** It cannot be `--internal` —
  the provider needs its own egress — so a compromised gateway/browser is kept off
  the internet only by the nft rule (the same barrier as pasta), and its on-link
  neighbours are other providers and gateways. A per-provider network (one bridge
  per module+lease, only the gateways using it attached) would shrink the segment.
- **The gateway still carries `NET_RAW`.** It is pre-existing and unused by nftables,
  the resolver or the forwarder; on a shared L2 segment it also enables ARP spoofing
  of neighbours. It should be dropped from the gateway's `cap_add` once verified not
  to regress the plain-endpoint path on real podman.
