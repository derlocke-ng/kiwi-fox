# Kiwi Fox

Isolated browser identities in rootless Podman.

Each profile is one persistent identity: its own storage and, usually, a proxy —
a kiwi-proxy exit with a sealed gateway and an ad-blocking resolver of its own —
in one of three browsers. In **Camoufox** (the default) it also has a frozen
fingerprint: a website sees a coherent, ordinary Windows 11 machine with its own
region. **Firefox** is stock Firefox, spoofing nothing; **Tor Browser** is Tor
Browser, through Tor.

For people who manage several accounts they own or are authorised to run and do
not want those accounts cross-linked by browser fingerprint or IP.

The network half — the proxies (kiwi-proxy calls them exits), their sealed
gateways, the provider modules — is
[kiwi-proxy](https://github.com/derlocke-ng/kiwi-proxy), which kiwi-fox installs
and drives. A proxy is defined once, in kiwi-proxy, and shared: several profiles
can use it, and so can kiwi-pentesting's tools and applications on the host. A
profile can also run with no proxy at all, on this machine's own connection.

## Install

```
kiwi install kiwi-fox      # brings kiwi-proxy along; or: ./install.sh install
kiwi-fox setup             # images, browser engine, DNS data (first run only)
```

`setup` is a separate step on purpose: it builds container images and downloads a
~630 MB browser engine, which should not happen silently during an install. It
runs kiwi-proxy's setup too (the gateway image, resolver stamps, the ad-block
list, module images), so it is still one command.

## Use

```
kiwi-proxy add kiwi-master-tor socks5://10.8.0.1:9050 --dns remote   # a proxy, defined once, in kiwi-proxy
kiwi-fox new work --exit kiwi-master-tor         # a profile on it: probes it, draws a matching identity
kiwi-fox new bare --no-proxy                     # this machine's own connection, nothing sealed
kiwi-fox list                                    # --tag shop, --by-tag
kiwi-fox run work                                # the browser (and its container); or use the GUI
kiwi-fox quit work                               # close the browser; the container follows unless kept
kiwi-fox up work                                 # the container alone: the exit up, the browser starts at once later
kiwi-fox stop work                               # the container, browser and all
kiwi-fox check                                   # is every profile still coherent?
kiwi-fox selfcheck work                          # measure what pages see, then audit it
kiwi-fox-gui                                     # "Kiwi Fox" in your app grid
```

The GUI does all of it: **New profile** picks the browser and the proxy — one
kiwi-proxy has, or none; **Open Kiwi Proxy** is right there for a new one —
**Browser engines** in the menu downloads Firefox and Tor Browser, and **Set up
environment** is `kiwi-fox setup`.

kiwi-fox makes no proxies itself. An endpoint goes to kiwi-proxy (`kiwi-proxy add
NAME socks5://user:pass@host:port`, also `http://…`, `https://…`, or the vendor
paste format `host:port:user:pass`), and the profile is put on it with `--exit`.

## Browser and container

Each profile has two buttons: **Browser** and **Container**. The container holds
the profile's network namespace on its exit; the browser runs in it. When the
browser quits — Quit browser, `kiwi-fox quit`, or its window closed — its container
stops too and lets go of the exit, which Kiwi Proxy takes down when nothing else
uses it. Preferences → General → "When the browser quits" can keep the container
running instead, so the browser starts again at once.

That happens however the profile was started: the window, the command line or
the app grid. Each container gets a watcher (a transient systemd user unit,
`kiwi-fox-watch-…`) that takes a snapshot when the browser closes and lets go of
the exit when the container ends.

**Repair on start** (Preferences → General, on by default) removes Kiwi Fox's
containers an unclean shutdown left, clears stale profile locks and gives running
containers their watcher; `kiwi-fox repair` does it by hand. **Check and repair**
in the menu runs podman's quick storage check and names every broken container,
Kiwi's or not, before anything is removed.

## Tags

A profile can carry tags, for grouping and finding: `--tag shop --tag eu` on
`new`, `kiwi-fox set work --tag shop` and `--untag`, `kiwi-fox list --tag shop` or
`--by-tag`. The GUI groups the list by each profile's first tag and shows the
rest on the row, and a profile's desktop entry lists its tags as keywords, so
the app grid finds it by them.

## A profile in the app grid

A profile can have a desktop entry of its own, so GNOME launches it like any app:

```
kiwi-fox new work --exit mullvad --desktop-entry   # or later: kiwi-fox set work --desktop-entry
kiwi-fox set work --no-desktop-entry               # takes it away
kiwi-fox desktop sync                              # rewrite every entry (after a move of the install)
```

In the GUI it is the **Show in the app grid** switch. The entry carries the
profile's name, the Kiwi Fox icon and a Stop action; a rename updates it and
deleting the profile removes it. The browser window announces the entry's id, so
the dock and the overview show the profile's name and icon while it runs — a
profile without an entry shows as Kiwi Fox.

## A profile on your other devices

Profiles go into the same encrypted snapshot folder as Kiwi Proxy's exits; your
sync client (Nextcloud) carries it to your other devices. A snapshot holds the
profile's settings, its fingerprint and its browser data — logins, cookies,
history, bookmarks, site storage, extensions, open tabs — and leaves out what the
browser rebuilds (caches, safe-browsing lists, crash reports) and the downloads:
a profile of 243 MB on disk is a 9 MB snapshot.

```bash
kiwi-proxy snapshot setup ~/Nextcloud/kiwi-snapshots   # once per device; the same in Preferences
kiwi-fox snapshot list
kiwi-fox snapshot restore work --fetch                 # --fetch installs its engine if missing
```

- **When:** after a profile ran and stopped, after you change its settings, and
  whenever you ask (Snapshots… in its menu, or "Snapshot everything now"). Never
  while its browser runs.
- **Starting an older copy asks first.** When the folder holds a newer snapshot
  from another device, Launch (and the app-grid entry) asks: restore and start,
  start as it is, or cancel. When both devices changed it, you choose which wins.
- **In use elsewhere:** a profile open on another device says so in its row and
  before it starts here. The folder can only tell as fast as it syncs.
- **Its exit comes from Kiwi Proxy.** A profile whose exit is not on this device
  says "restore it in Kiwi Proxy first"; Kiwi Fox never makes or restores proxies.
- **Its engine:** a restored profile that needs an engine version this device
  lacks offers to install it (downloaded and verified like any other).

A restore keeps what was here as a snapshot first, so it can be undone. The
folder, the passphrase and the encryption are kiwi-proxy's; see
[kiwi-proxy's docs/snapshots.md](https://github.com/derlocke-ng/kiwi-proxy/blob/main/docs/snapshots.md).

## Proxies, and provider modules

A proxy is a kiwi-proxy exit: a SOCKS5 you were given, or one a provider module
runs for you — Tor, a VPN tunnel (gluetun), 9proxy or Mysterium. It carries its
own DNS mode and ad-blocking lists, so blocking ads on your Tor SOCKS is a setting
on that proxy, and every profile on it gets it. `kiwi-proxy list` shows them,
`kiwi-proxy set NAME …` changes one, and the Kiwi-Proxy app does the same.

Profiles on one proxy share its gateway: one namespace, one exit IP, one set of
Tor circuits. Identities that must not share an exit take different proxies.

Each module is its own kiwi app and exposes plain SOCKS5; the gateway reaches it
over a private bridge and still permits exactly one destination.

```
kiwi install kiwi-plugin-tor                  # or -vpn, -9proxy, -myst
kiwi-fox setup                                # builds the module's image
kiwi-proxy add tor-de --module tor --country de
kiwi-fox new work --exit tor-de
kiwi-fox module list                          # = `kiwi-proxy module list`; `module countries tor`
```

How modules work and how to write one: kiwi-proxy's
[docs/plugin-system.md](https://github.com/derlocke-ng/kiwi-proxy/blob/main/docs/plugin-system.md).

## Browser engine

A profile runs one of three engines, chosen at creation:

- **`camoufox`** (default) — a spoofed, frozen Windows 11 identity. A page sees a
  coherent, ordinary Windows machine. This is everything above.
- **`firefox`** — stock Mozilla Firefox, no spoofing: a page sees this machine's
  own values. Less unique, but nothing is faked and nothing can slip — for when
  a real, ordinary Firefox through the same isolated exit is what you want.
- **`torbrowser`** — the Tor Browser bundle, unmodified, through the tor
  provider module: Tor Browser's own uniform fingerprint and a circuit per
  site, Whonix-style.

```
kiwi-fox engine fetch --engine firefox        # Mozilla's build, signature-verified
kiwi-fox new plain socks5://host:port --engine firefox
kiwi-fox run plain
```

A firefox profile has no fingerprint and ignores the identity flags
(`--webgl`, `--card`, `--screen`, …); it keeps its proxy, appearance and the same
leak-proof gateway. Its traffic still exits only through the one
permitted destination, WebRTC cannot leak the host address, and the engine is
pinned and mounted read-only with updates turned off.

```
kiwi install kiwi-plugin-tor
kiwi-fox engine fetch --engine torbrowser     # signature-verified against the pinned Tor key
kiwi-proxy add tor-de --module tor --country de   # Tor Browser needs an exit on the tor module
kiwi-fox new anon --engine torbrowser --exit tor-de
kiwi-fox run anon
```

Like Whonix, Tor Browser runs without its own tor: `TOR_PROVIDER=none` points it
at the gateway, whose only route is the tor provider. Tor Browser keys a circuit
per first-party site with its SOCKS credentials, and the gateway passes those
through behind the proxy's own token, so sites stay on separate circuits and
proxies stay apart; New Identity and New Circuit work without a control port.
DNS resolves at the exit, so `.onion` works. It needs a proxy on the tor module,
which kiwi-proxy makes passthrough by default, and cannot run without one. The download is checked against the Tor Browser Developers' signing key,
pinned by fingerprint, and the bundle is mounted read-only and never patched.

## What a new profile is

A Camoufox profile is the commonest machine there is, because rare values are what detectors flag: a
1920x1080 screen, the fonts every Windows 11 has and no others, and this
machine's own graphics card as Firefox on Windows words it. Region, language,
timezone and voices follow the exit. Everything can be changed afterwards.

The window opens at the size Firefox itself picks on that screen and comes back
the way you left it. It is never opened larger than the screen the profile
claims — resize freely, but a *maximised* window is as big as your real monitor
allows, which can be more than the claimed screen has.

## Changing a profile

Everything a Camoufox profile reports can be changed after it was created — in the
GUI under **Edit…**, or:

```
kiwi-fox set work --screen 2560x1440 --cores 12
kiwi-fox set work --country SE --timezone Europe/Stockholm
kiwi-fox set work --font-add "Yu Gothic" --font-add "MS Gothic"  # see: kiwi-fox fonts work
kiwi-fox set work --appearance dark                            # or light, or host
kiwi-fox set work --user-agent "Mozilla/5.0 …"                 # --default-user-agent undoes it
kiwi-fox set work --exit other-proxy                            # or --no-proxy
```

Edits are checked together and nothing is saved unless the result is coherent. One
thing is not there because it does not exist: the Windows version. Firefox sends
the same user agent on Windows 10 and 11.

A Firefox or Tor Browser profile spoofs nothing, so only its name, proxy and
(Firefox) appearance change: `kiwi-fox set plain --name other --exit tor-de`. The
proxy's own settings — endpoint, DNS, blocklists — are kiwi-proxy's:
`kiwi-proxy set tor-de --dns remote`.

## Graphics

This and the next section are about Camoufox profiles. Firefox does not tell a page which graphics card you have. It reports the *group*
the card is in, with the same text for every card in the group — an RTX 4060 on
real Windows reads `ANGLE (NVIDIA, NVIDIA GeForce GTX 980 Direct3D11 vs_5_0
ps_5_0), or similar`, and so do a GTX 1650 and an RTX 4090. That text is what a
profile reports, and you choose the card it is derived from:

```
kiwi-fox gpus                                # every card, grouped by what Firefox shows for it
kiwi-fox new work ENDPOINT                   # default: the card this machine really has
kiwi-fox new work ENDPOINT --card "RTX 3060" # another card
kiwi-fox webgl work --card "UHD 620"         # change it later; applies at the next launch
kiwi-fox webgl work --exact                  # also name the exact model (see below)
kiwi-fox webgl work --mode off               # no WebGL at all
```

| Setting | A page sees |
| --- | --- |
| My graphics card (`host`, default) | this machine's card, worded the way Firefox on Windows words it |
| Another graphics card (`preset`) | the card you picked, worded the same way |
| Custom text (`custom`) | your own `--vendor` / `--renderer` |
| No WebGL (`off`) | no WebGL context; rare on Windows |
| Unchanged (`raw`) | nothing rewritten: Linux wording and limits under a Windows browser. For measuring and testing only |

**Show the exact model** (`--exact`) puts the card's own name into the one field
that can carry it (`UNMASKED_RENDERER_WEBGL`). Stock Firefox only does that with a
hidden setting changed, so it is the rarer choice; the main renderer field keeps
the group text either way, because Firefox itself writes it.

Whatever a profile claims, the frames are drawn by the GPU this machine has.

The browser has to draw on a real GPU: frames drawn in software are how a virtual
machine looks, whatever the profile says. `kiwi-fox doctor` measures it with the
engine's own probe and says which GPU it got, or that it got none. Where the
desktop runs on an NVIDIA card with the proprietary driver, that driver is brought
into the container by `nvidia-container-toolkit` (CDI). Without it a second GPU is
tried if the machine has one, and the measurement says whether that worked.
`KIWI_FOX_GPU=mesa|nvidia|software` overrides the choice.

## Language

A Camoufox profile is the Firefox of its region: a Dutch profile is a Dutch Firefox, with
Dutch menus, Dutch form messages, `nl, en-US, en` as its languages and Dutch date
formats — the list and the `Accept-Language` header are the ones that build of
Firefox ships with. The language pack comes from Mozilla on first launch.

```
kiwi-fox set work --language english    # an English Firefox used in that region
kiwi-fox set work --language local      # back to the region's own
```

## How a profile is isolated

```
gateway container   kiwi-proxy's, for the profile's proxy; owns the network namespace,
                    shared by every profile (and tool) on that proxy
                    nftables: default drop, one permitted destination
                    forwarder: adds proxy credentials, the browser never sees them
                    dnscrypt-proxy: ad-blocking, upstream through the same exit
browser container   joins that namespace — no routing table of its own
```

The kill switch is the absence of a route, not software that has to notice. If the
gateway dies the profile simply loses connectivity.

`kiwi-proxy list` shows the proxies. Another profile, a pentest tool or
`kiwi-proxy up` can be in the same namespace; closing the browser leaves the
gateway to them, and it goes with the last one. With no proxy there is no gateway: the browser container has a network
of its own on this machine's connection, and nothing is sealed.

## What it does not do

It does not promise "undetectable". Profiles are isolated for storage, IP and
every surface the engine can spoof, but **not** against hardware-level
cross-browser identifiers: the frame the GPU actually draws and hardware timing
come from the real machine and are the same for every profile on it. That
limit is measured and documented, not hidden — see
`docs/detection-notes.md`.

No automation, no bots, no bulk account creation. Interactive browsing only.

## Requirements

Rootless Podman, [kiwi-proxy](https://github.com/derlocke-ng/kiwi-proxy), a
Wayland session (X11 works with a weaker boundary), Python 3.12+, GTK4 +
libadwaita for the GUI, and `secret-tool` for credential storage. `gpg` and
`gpgv` verify the Firefox and Tor Browser downloads.
On a machine whose desktop runs on the proprietary NVIDIA driver, also
`nvidia-container-toolkit` with its CDI spec generated.

After updating, run `kiwi-fox setup` again: it rebuilds the container images when
the new version changed what they are built from, and does nothing otherwise.

## License

GPL-3.0-or-later — see [LICENSE](LICENSE).

The browser engines — [Camoufox](https://github.com/daijro/camoufox) (MPL-2.0),
Mozilla's Firefox and the Tor Project's Tor Browser — are fetched at setup or on
request, never redistributed here. Three small pieces
derived from MPL-2.0 sources are included and stay under that licence:

- `src/kiwi_fox/core/fingerprint/data/webgl-windows.json` — WebGL records of real
  Windows machines, extracted from Camoufox's `webgl_data.db`
- `tests/unit/data/camoufox-properties-*.json` — Camoufox's config schema for two
  engine versions, used to test that only keys an engine knows are ever sent
- `src/kiwi_fox/core/fingerprint/sanitizer.py` — a Python port of Firefox's
  `dom/canvas/SanitizeRenderer.cpp`
