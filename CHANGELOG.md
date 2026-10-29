# Changelog

## 0.3.0

The proxy engine is its own app now: [kiwi-proxy](https://github.com/derlocke-ng/kiwi-proxy).
kiwi-fox keeps everything browser-shaped and drives kiwi-proxy for the network
half, which kiwi-pentesting, applications on the host and kiwi-server machines can
use too.

- **kiwi-proxy.** The gateway (the sealed namespace, its credential forwarder and
  resolver), the provider modules and the DNS data moved there, with their tests.
  `kiwi install kiwi-fox` brings it along (`DEPENDS=kiwi-proxy`), `kiwi-fox setup`
  runs its setup, and `kiwi-fox module …` is `kiwi-proxy module …`.
- **One exit per profile.** Every profile is a kiwi-proxy exit under the profile's
  own id, so the gateway (`kf-gw-…`), the Tor circuit token and the labels
  kiwi-pentesting looks for are unchanged. `kiwi-proxy list` shows every
  identity; `kiwi-proxy set` edits its endpoint or DNS and kiwi-fox picks that up.
  Profiles from 0.2 get their exit at `kiwi-fox setup` or their next launch.
- **Shared gateways.** Closing a window releases the gateway instead of removing
  it, so a pentest tool or a `kiwi-proxy up` of the same identity keeps its
  connection; a second launch joins a gateway already up for the identity.
  Deleting a profile takes its gateway down.
- **Tor Browser engine.** `--engine torbrowser`: the unmodified bundle through the
  tor module, Whonix-style — no bundled tor (`TOR_PROVIDER=none`), its own uniform
  fingerprint, a circuit per site through the forwarder's passthrough mode, DNS at
  the exit for `.onion`. The download is verified with gpgv against the Tor
  Browser Developers' key, pinned by fingerprint. Any exit but the tor module is
  refused.

Upgrading: kiwi-proxy takes over the DNS data kiwi-fox had downloaded, and
kiwi-fox's own blocklist timer is removed (kiwi-proxy's replaces it). Provider
modules install into kiwi-proxy's directory from their 0.2.0 releases; until a
module is updated, a launch that needs it says which app to update. Run
`kiwi-fox setup` once after updating.

## Earlier

0.2.0 added the stock Firefox engine, 0.1.4 exits from provider modules. See the
[releases](https://github.com/derlocke-ng/kiwi-fox/releases).
