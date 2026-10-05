# Kiwi-Fox

Isolated Windows 11 browser identities in rootless Podman.

Each profile is one persistent identity: its own storage, its own proxy exit, its
own ad-blocking DNS resolver and its own frozen fingerprint. A website sees a
coherent Windows 11 machine; the profile next to it sees a different one.

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

## Changing a profile

Everything a profile reports can be changed after it was created — in the GUI
under **Edit…**, or:

```
kiwi-fox set work --screen 2560x1440 --cores 12
kiwi-fox set work --country SE --timezone Europe/Stockholm
kiwi-fox set work --font-add Lato --font-remove "Open Sans"    # kiwi-fox fonts work
kiwi-fox set work --appearance dark                            # or light, or host
kiwi-fox set work --user-agent "Mozilla/5.0 …"                 # --default-user-agent undoes it
kiwi-fox set work --endpoint socks5://user:pass@host:port
```

Edits are checked together and nothing is saved unless the result is coherent. One
thing is not there because it does not exist: the Windows version. Firefox sends
the same user agent on Windows 10 and 11.

## Graphics

Firefox never tells a page which graphics card you have — only the *series* it
belongs to, and an RTX 4090 and a GTX 1650 are the same series. So that is what a
profile reports, and what you choose from:

```
kiwi-fox gpus                                    # the six series, with real-world share
kiwi-fox new work ENDPOINT                       # default: the series this machine really has
kiwi-fox new work ENDPOINT --series "RTX 3060"   # any card name; you get the series it is in
kiwi-fox webgl work --series intel-hd            # change it later; applies at the next launch
kiwi-fox webgl work --mode off                   # no WebGL at all
```

Also `--mode custom` with your own `--vendor`/`--renderer`, and `--mode raw` to
spoof nothing. `docs/detection-notes.md` says what each mode reports and what none
of them can change.

The browser has to draw on a real GPU: frames drawn in software are how a virtual
machine looks, whatever the profile says. `kiwi-fox doctor` measures it with the
engine's own probe and says which GPU it got, or that it got none. Where the
desktop runs on an NVIDIA card with the proprietary driver, that driver is brought
into the container by `nvidia-container-toolkit` (CDI); without it kiwi-fox falls
back to another GPU if there is one. `KIWI_FOX_GPU=mesa|nvidia|software` overrides
the choice.

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
