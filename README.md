# Kiwi-Fox

Isolated Windows 11 browser identities in rootless Podman.

Each profile is one persistent identity: its own storage, its own proxy exit, its
own ad-blocking DNS resolver and its own frozen fingerprint. A website sees a
coherent, ordinary Windows 11 machine, with its own region, exit and storage.

For people who manage several accounts they own or are authorised to run and do
not want those accounts cross-linked by browser fingerprint or IP.

## Install

```
kiwi install kiwi-fox      # or: ./install.sh install
kiwi-fox setup             # images, browser engine, blocklists (first run only)
```

`setup` is a separate step on purpose: it builds container images and downloads a
~630 MB browser engine, which should not happen silently during an install.

## Use

```
kiwi-fox new work socks5://user:pass@host:port   # probes the exit, draws a matching identity
kiwi-fox list
kiwi-fox run work                                # or use the GUI
kiwi-fox stop work
kiwi-fox check                                   # is every profile still coherent?
kiwi-fox selfcheck work                          # measure what pages see, then audit it
kiwi-fox-gui                                     # "Kiwi-Fox" in your app grid
```

Endpoint formats: `socks5://user:pass@host:port`, `http://…`, `https://…`, and the
vendor paste format `host:port:user:pass`.

## What a new profile is

The commonest machine there is, because rare values are what detectors flag: a
1920x1080 screen, the fonts every Windows 11 has and no others, and this
machine's own graphics card as Firefox on Windows words it. Region, language,
timezone and voices follow the exit. Everything can be changed afterwards.

The window opens at the size Firefox itself picks on that screen and comes back
the way you left it. It is never opened larger than the screen the profile
claims — resize freely, but a *maximised* window is as big as your real monitor
allows, which can be more than the claimed screen has.

## Changing a profile

Everything a profile reports can be changed after it was created — in the GUI
under **Edit…**, or:

```
kiwi-fox set work --screen 2560x1440 --cores 12
kiwi-fox set work --country SE --timezone Europe/Stockholm
kiwi-fox set work --font-add "Yu Gothic" --font-add "MS Gothic"  # see: kiwi-fox fonts work
kiwi-fox set work --appearance dark                            # or light, or host
kiwi-fox set work --user-agent "Mozilla/5.0 …"                 # --default-user-agent undoes it
kiwi-fox set work --endpoint socks5://user:pass@host:port
```

Edits are checked together and nothing is saved unless the result is coherent. One
thing is not there because it does not exist: the Windows version. Firefox sends
the same user agent on Windows 10 and 11.

## Graphics

Firefox does not tell a page which graphics card you have. It reports the *group*
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

A profile is the Firefox of its region: a Dutch profile is a Dutch Firefox, with
Dutch menus, Dutch form messages, `nl, en-US, en` as its languages and Dutch date
formats — the list and the `Accept-Language` header are the ones that build of
Firefox ships with. The language pack comes from Mozilla on first launch.

```
kiwi-fox set work --language english    # an English Firefox used in that region
kiwi-fox set work --language local      # back to the region's own
```

## How a profile is isolated

```
gateway container   owns the network namespace
                    nftables: default drop, one permitted destination
                    forwarder: adds proxy credentials, the browser never sees them
                    dnscrypt-proxy: ad-blocking, upstream through the same exit
browser container   joins that namespace — no routing table of its own
```

The kill switch is the absence of a route, not software that has to notice. If the
gateway dies the profile simply loses connectivity.

## What it does not do

It does not promise "undetectable". Profiles are isolated for storage, IP and
every surface the engine can spoof, but **not** against hardware-level
cross-browser identifiers: the frame the GPU actually draws and hardware timing
come from the real machine and are the same for every profile on it. That
limit is measured and documented, not hidden — see
`docs/detection-notes.md`.

No automation, no bots, no bulk account creation. Interactive browsing only.

## Requirements

Rootless Podman, a Wayland session (X11 works with a weaker boundary), Python
3.12+, GTK4 + libadwaita for the GUI, and `secret-tool` for credential storage.
On a machine whose desktop runs on the proprietary NVIDIA driver, also
`nvidia-container-toolkit` with its CDI spec generated.

After updating, run `kiwi-fox setup` again: it rebuilds the container images when
the new version changed what they are built from, and does nothing otherwise.

## License

GPL-3.0-or-later — see [LICENSE](LICENSE).

The browser engine is [Camoufox](https://github.com/daijro/camoufox) (MPL-2.0),
pinned and fetched at setup time, never redistributed here. Three small pieces
derived from MPL-2.0 sources are included and stay under that licence:

- `src/kiwi_fox/core/fingerprint/data/webgl-windows.json` — WebGL records of real
  Windows machines, extracted from Camoufox's `webgl_data.db`
- `tests/unit/data/camoufox-properties-*.json` — Camoufox's config schema for two
  engine versions, used to test that only keys an engine knows are ever sent
- `src/kiwi_fox/core/fingerprint/sanitizer.py` — a Python port of Firefox's
  `dom/canvas/SanitizeRenderer.cpp`
