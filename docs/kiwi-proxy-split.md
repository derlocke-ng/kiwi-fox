# Handoff: kiwi-fox's proxy engine is now kiwi-proxy

For the Claude session developing kiwi-fox. Read this before touching anything in
`core/launch.py`'s network half, `core/providers/`, `core/proxy.py`, `core/dns.py`,
`core/podman.py` or `containers/gateway/`.

The proxy engine — gateways, the credential forwarder, the in-namespace resolver,
the provider plugins — has been extracted into
[derlocke-ng/kiwi-proxy](https://github.com/derlocke-ng/kiwi-proxy) so it can serve
kiwi-fox, kiwi-pentesting, applications on the host (one local SOCKS5 port per VPN),
and kiwi-server nodes/masters. kiwi-fox becomes one consumer of it. Everything
browser-shaped stays here.

State when this was written (2026-10-29):

| Repo | Branch | What |
| --- | --- | --- |
| kiwi-proxy | `claude/quirky-brahmagupta-2edkpi` | 0.1.0, the engine (forked from kiwi-fox `main` at `17d5bca`, so it already has forwarder passthrough #9) |
| kiwi-plugin-tor / -vpn / -9proxy / -myst | `claude/quirky-brahmagupta-2edkpi` | 0.2.0 each: import `kiwi_proxy`, install into kiwi-proxy's modules dir |
| kiwi-fox | `claude/quirky-brahmagupta-2edkpi` | only this document |

Nothing in kiwi-fox's code has been changed. **The split itself is yours to do**,
on top of whatever you have in flight (the Tor Browser engine).

## What moved, and where

| kiwi-fox (today) | kiwi-proxy | Notes |
| --- | --- | --- |
| `containers/gateway/*` | `containers/gateway/*` | + `kf-exitinfo`, + a host listener (`KF_EXPOSE_PORT`), + `KF_ENDPOINT_HOST`/`KF_CREDS_TABLE` for kiwi-server. Your #9 passthrough is in, byte-identical. Image is `kiwi-proxy/gateway:latest` |
| `core/proxy.py` | `kiwi_proxy.endpoint` | `ProxyError` kept as an alias of `EndpointError`; `parse_geo()` split out |
| `core/dns.py` | `kiwi_proxy.dns` | unchanged API; data under `~/.local/share/kiwi-proxy/blocklists` (install copies yours over) |
| `core/podman.py` | `kiwi_proxy.podman` | + `publish`, `labels()`, `dependents()`; `ps()` filters on `kiwi-proxy.role` |
| `core/providers/*` | `kiwi_proxy.providers.*` | same contract; lifecycle adds `kiwi-proxy.role/module/lease` labels itself |
| `models.Endpoint, ExitInfo, DnsConfig, Lease, ProviderManifest, ProviderStatus, ProviderRecord, ContainerSpec` | `kiwi_proxy.models` | same fields; `ContainerSpec` gained `publish` |
| `paths.PROVIDERS_*`, `provider_*`, `gateway_name`, `modules_dir` | `kiwi_proxy.paths` | podman names unchanged (`kf-gw-…`, `kf-prov-…`, `kf-providers`, `kf-creds-…`) |
| `launch.write_credentials, write_resolver_config, write_resolv_conf, gateway_spec, EndpointPlan, ensure_provider, preflight, _start_gateway, start_gateway, _provider_users, release_provider, reconcile_providers` and the gateway half of `stop`/`reap` | `kiwi_proxy.gateway` | see the mapping below |
| `store.load_providers, record_provider` | `kiwi_proxy.exits` | `providers.json` under kiwi-proxy's data dir |
| `setup`: gateway image, dns stamps, blocklist, module setup | `kiwi_proxy.setup.run()` | call it from kiwi-fox's setup |
| `cli`: `module …`, `dns …`, `test` | `kiwi-proxy module …`, `dns …`, `test` | keep thin wrappers in kiwi-fox if you like, or point at kiwi-proxy |
| `docs/plugin-system.md`, network part of `docs/decisions.md` | kiwi-proxy `docs/` | replace with a pointer |
| `tests/unit/test_forwarder.py, test_dns.py, test_proxy.py`, most of `test_providers.py`, `tests/leak/` network parts | kiwi-proxy `tests/` | |

What **stays** in kiwi-fox: profiles, fingerprints, engines (Camoufox, Firefox,
Tor Browser), the browser container and its spec, user.js/langpacks/geometry/GPU,
the probe, the GUI, the keyring for profile passwords, `secrets.py` (as is).

## The model: a profile has an exit

kiwi-proxy's unit is an **exit** (`kiwi_proxy.models.Exit`): `id, name, endpoint,
dns, expose, socks_auth, owner, last_exit, notes`. Register **one exit per profile,
with the profile id as the exit id** and `owner="kiwi-fox"`:

```python
from kiwi_proxy import exits
ex = exits.create(profile.name, endpoint, dns=dns_cfg, exit_id=profile.id, owner="kiwi-fox")
```

Using the profile id is what keeps the upgrade invisible: the gateway is still
`kf-gw-<profile id[:12]>`, the Tor isolation token is still `kf-<profile id[:16]>`
(same circuit as before), and kiwi-pentesting still finds it.

Recommended shape (your call): the exit becomes the source of truth for
`endpoint` and `dns`; `Profile` keeps a reference. A minimal path that keeps
`profile.json` loading: leave `Profile.endpoint`/`Profile.dns` in the model, and on
load (or at first launch) make sure an exit with `id == profile.id` exists, creating
it from those fields. `kiwi-fox set --endpoint/--dns` then edits the exit
(`exits.save`). Exit names must be unique in kiwi-proxy; a clash with a CLI-made exit
should be a clear error at `kiwi-fox new`.

Passwords: keep kiwi-fox's keyring (`secrets.lookup(profile.id)`) and pass the value
to `gateway.up(ex, password=…)`. kiwi-proxy never needs its own copy for kiwi-fox's
exits.

## launch.py, function by function

```python
from kiwi_proxy import gateway, exits
from kiwi_proxy.gateway import FORWARDER_PORT          # 1080, was engines.gecko.FORWARDER_PORT

LABELS = lambda p: {"app": "kiwi-fox", "kiwi-fox.role": "gateway", "kiwi-fox.profile": p.id}
```

| today | becomes |
| --- | --- |
| `preflight(profile)` (decide upstream + measure, before validation) | `gateway.plan(ex, password)` → `EndpointPlan(ip, port, network, info, notes)`. For a provider exit `info` is None (the host can't reach the bridge); `gateway.up()` measures those from inside and returns `Gateway.info` |
| `write_credentials`, `write_resolver_config`, `_start_gateway(profile, plan)` | `gw = gateway.up(ex, password=…, labels=LABELS(profile))` — idempotent; returns `Gateway(name, resolv_conf, resolver, info, reused, notes)`. It removes stale members itself (the old "rm the browser first"), and waits for the gateway's ready line |
| `start_gateway(profile)` (the probe) | `gateway.up(ex, password=…, labels=LABELS(profile))`; the probe joins `gw.name` as before |
| `write_resolv_conf(profile)` in `browser_spec` | mount `gw.resolv_conf` (None in remote DNS mode) |
| `gateway_spec(..., socks_auth=, dns_mode=)` | set `ex.socks_auth` / `ex.dns.mode` on the exit (see Tor Browser) |
| `stop(profile)` | `podman.rm(browser)` then `gateway.release(profile.id, ignore=(browser_name,))` — the gateway stays up if a pentest tool or a `kiwi-proxy up` of this exit still uses it. `gateway.down(profile.id)` is the unconditional version |
| `wait_and_teardown` | unchanged shape: wait for the browser, then the `stop` above |
| `release_provider`, `_provider_users` | gone: `down()` releases the provider once no gateway (from any app) uses it, by label |
| `reconcile_providers()` | `gateway.reconcile()` |
| `reap()` | browser-gone check stays in kiwi-fox (`podman.rm` the dead browser, then `release`); then `gateway.reap()` |
| `LaunchError` from provider failures | catch `gateway.GatewayError` and re-raise as `LaunchError` |

Note the change in behaviour you get for free: a second `up()` of a running exit
with the same settings returns it (`reused=True`) instead of replacing it, so a
browser launch no longer cuts off a pentest tool on the same identity, and vice
versa. Settings that differ while someone is inside raise `GatewayError` unless
`replace=True`.

## Tor Browser (your Stage 3b)

The engine itself — `core/engines/torbrowser.py`, `torbrowser_fetch.py`, the
browser entrypoint branch, the store/CLI changes — is browser code and belongs
**here in kiwi-fox**, not in kiwi-proxy. The patch on kiwi-proxy's
`handoff/torbrowser-engine` branch was read and nothing in it needs to land in
kiwi-proxy; that branch can be deleted once your stash is safe.

Its proxy bits map onto the exit:

| your patch (launch.py) | with kiwi-proxy |
| --- | --- |
| gateway `socks_auth="passthrough"` | `ex.socks_auth = "passthrough"` on the Tor Browser profile's exit, then `exits.save(ex)`; `gateway_spec` emits `KF_SOCKS_AUTH=passthrough` exactly as your #9 did |
| gateway `dns_mode="remote"` / `effective_dns_mode` | `ex.dns.mode = "remote"` on that exit (so no resolver, no blocklist mount; `Gateway.resolv_conf` is None) |
| refuse TB on a non-tor / non-isolation endpoint | keep that check in kiwi-fox (it is a browser rule). kiwi-proxy additionally refuses passthrough when there is no token to put in front (`GatewayError("… passthrough needs …")`) |
| `TOR_SOCKS_HOST/PORT=127.0.0.1/1080` | unchanged: the forwarder is still `127.0.0.1:1080` (`gateway.FORWARDER`) |

kiwi-plugin-tor 0.2.0 is your 0.1.1 (KeepAliveIsolateSOCKSAuth, ExtendedErrors)
ported to kiwi-proxy; nothing else changed in its torrc.

## Packaging

- `kiwi.manifest`: `DEPENDS=kiwi-proxy podman python3 secret-tool`.
- Launchers (`install.sh`): put kiwi-proxy on the path —
  `export PYTHONPATH="$LIBDIR:$KIWI_PREFIX/lib/kiwi-proxy${PYTHONPATH:+:$PYTHONPATH}"`
  for both `kiwi-fox` and `kiwi-fox-gui`.
- Drop kiwi-fox's own `kiwi-fox-blocklists.{service,timer}` (kiwi-proxy installs
  `kiwi-proxy-blocklists.timer`); remove the old units on update.
- `setup.run()`: build only the browser image here; call `kiwi_proxy.setup.run(progress)`
  for the gateway image, DNS data and module images. `doctor`: show kiwi-proxy's
  image state too (`kiwi_proxy.setup.image_state`).
- `containers/gateway/` and `make images`' gateway line go away.
- Dev/tests: find a sibling checkout the way the plugins find you —
  `../kiwi-proxy/src` or `KIWI_PROXY_SRC` — and add it to `pythonpath` in
  `pyproject.toml`'s pytest section (or `conftest.py`).
- Optional, to soften the change for anything still importing the old paths:
  thin re-export shims (`core/providers/base.py`: `from kiwi_proxy.providers.base import *`).
  The four first-party plugins no longer need them.
- Version: a minor bump (0.3.0), CHANGELOG entry naming the split.

## Merge order

1. kiwi-proxy 0.1.0 (its release workflow tags it).
2. kiwi-fox consuming it (this work).
3. The four plugins' 0.2.0 — before step 2 is released, an updated plugin would
   install where old kiwi-fox does not look.

kiwi-pentesting needs nothing to keep working (kiwi-fox keeps `app=kiwi-fox` and
`kiwi-fox.role=gateway` on its gateways), and can later use `kiwi-proxy up/list/check
--json` for headless identities — see kiwi-proxy's `docs/consumers.md`.

## Do not change

- The podman names (`kf-…`) and the providers subnet: the bridge cannot be renamed
  on a host that already has it.
- Exit id = profile id for kiwi-fox's exits (gateway name, Tor token).
- Credentials as podman secrets; passwords never in env.

## Reference

kiwi-proxy: `README.md`, `docs/consumers.md` (the API), `docs/architecture.md`,
`docs/decisions.md`. Its `tests/unit/test_gateway.py` shows every lifecycle case
against a fake podman.
