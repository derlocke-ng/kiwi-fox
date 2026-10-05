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
limit is measured and documented, not hidden — see `kiwi-fox.md` and
`docs/detection-notes.md`.

No automation, no bots, no bulk account creation. Interactive browsing only.

## Requirements

Rootless Podman, a Wayland session (X11 works with a weaker boundary), Python
3.12+, GTK4 + libadwaita for the GUI, and `secret-tool` for credential storage.

## License

GPL-3.0-or-later — see [LICENSE](LICENSE).

The browser engine is [Camoufox](https://github.com/daijro/camoufox) (MPL-2.0),
pinned and fetched at setup time, never redistributed here. Three small pieces
derived from MPL-2.0 sources are included and stay under that licence:

- `src/kiwi_fox/core/fingerprint/data/webgl-windows.json` — WebGL records of real
  Windows machines, extracted from Camoufox's `webgl_data.db`
- `tests/unit/data/camoufox-properties-152.0.4.json` — Camoufox's config schema,
  used to test that only keys the engine knows are ever emitted
- `src/kiwi_fox/core/fingerprint/sanitizer.py` — a Python port of Firefox's
  `dom/canvas/SanitizeRenderer.cpp`
