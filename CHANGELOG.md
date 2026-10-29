# Changelog

## 0.3.1

The GUI and the texts catch up with 0.3.0.

- **GUI for every engine and exit.** New profile chooses the browser — Camoufox,
  Firefox or Tor Browser — and the exit: an endpoint, or an installed provider
  module with its country and lease. The Windows identity and graphics sections
  are Camoufox's; Tor Browser is held to the tor module.
- **Firefox and Tor Browser profiles open in the GUI.** Details and Edit raised
  "has no fingerprint" for them. Rows now say which browser and exit ("Tor
  Browser · tor · DE"), and Duplicate keeps both.
- **Browser engines** in the menu downloads and updates Firefox and Tor Browser
  (signature-verified) and sets Camoufox up.
- The environment check names the engines and modules the profiles need, and no
  longer fails silently on a machine without podman.
- **`kiwi-fox set` works on Firefox and Tor Browser profiles** (name, endpoint,
  DNS, appearance); it loaded a fingerprint first. `webgl`, `fonts`, `selfcheck`
  and `compare` say they are about Camoufox's Windows machine instead of "has no
  fingerprint".
- A missing Firefox or Tor Browser is a plain error with the right
  `kiwi-fox engine fetch … --engine …`, not a traceback or the wrong command.
- Texts: the install message, `setup`/`list`/`new` help and hints, the README,
  the desktop entry and the About dialog describe three engines, provider modules
  and kiwi-proxy. `kiwi-fox list` shows the browser.
- New screenshots (`make screenshots` renders them from the GUI), and the GUI tests
  run in CI.

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
