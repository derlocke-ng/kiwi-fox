# kiwi-fox

kiwi-fox gives you a separate browser for each account you manage and for each
client network you work in. Each browser **profile** is one persistent
identity: it has its own storage, runs in its own rootless Podman container (a
container that runs as your user, without root rights), and usually goes out
through its own **exit**, a named proxy connection that
[kiwi-proxy](https://kiwi-network.eu/docs/clients/kiwi-proxy/) keeps. The
browser container has no route of its own: if the exit stops, the profile loses
its connection instead of falling back to yours.

A profile runs one of three browsers, which kiwi-fox calls **engines**:

- **Camoufox** (the default) shows a page an ordinary Windows 11 machine with
  its own region. Its values fit together and stay the same from one session
  to the next.
- **Firefox** is Mozilla's own build and spoofs nothing.
- **Tor Browser** is the unmodified Tor Browser, through an exit on Tor.

kiwi-fox is for people who manage several accounts that they own or are
authorised to run, and who do not want these accounts linked to each other
through the browser fingerprint or the IP address. It is part of the Kiwi
desktop, next to kiwi-proxy and kiwi-custodia.

- Latest release: **v0.14.1**, in the
  [Kiwi catalog](https://kiwi-network.eu/docs/desktop/catalogs/) (user scope,
  no root needed)
- Runs on: Linux with rootless Podman, Python 3.12 or newer and kiwi-proxy.
  CI runs the tests on Ubuntu and builds the browser image with Podman.
- License: GPL-3.0-or-later

## Install

```bash
kiwi install kiwi-fox
kiwi-fox setup
```

`kiwi install` installs kiwi-proxy as well, then puts kiwi-fox under
`~/.local` with the `kiwi-fox` command and the **Kiwi Fox** app. Nothing is
installed as root. `kiwi-fox setup` builds the browser image, downloads
Camoufox (about 1.3 GB) and runs kiwi-proxy's own setup. Run it once after the
install. From a checkout, `./install.sh install` does the same as
`kiwi install`. The [install page](docs/install.md) lists what kiwi-fox needs
and every file it writes.

## Quick start

```bash
kiwi-proxy add work socks5://user:pass@proxy.example.net:1080
kiwi-fox new shop --exit work
kiwi-fox run shop
kiwi-fox quit shop
```

`kiwi-proxy add` saves the exit. `kiwi-fox new` measures where the exit comes
out and creates a Camoufox profile whose region matches it. `run` starts the
exit's gateway and the browser, and `quit` closes the browser. The app, **Kiwi
Fox** in your app grid, does the same without a terminal.

## Documentation

| Page | What it covers |
|---|---|
| [Install](docs/install.md) | requirements, install, first setup, update, uninstall |
| [Using kiwi-fox](docs/usage.md) | profiles, the browser and its container, tags and colours, the app grid, every command |
| [Proxies and provider modules](docs/proxies.md) | putting a profile on an exit, Tor, VPN and other modules |
| [Browser engines](docs/engines.md) | Camoufox, Firefox and Tor Browser, their versions and downloads |
| [The Camoufox identity](docs/camoufox.md) | what a new profile reports, and how to change it |
| [Snapshots](docs/snapshots.md) | your profiles on your other devices, encrypted |
| [Isolation and its limits](docs/isolation.md) | how a profile is sealed, and what it does not hide |
| [Detection notes](docs/detection-notes.md) | what a detector can still see, measured |
| [Decisions](docs/decisions.md) | why things are the way they are |
| [Development](docs/development.md) | tests, CI, releases |

The same pages are on
[kiwi-network.eu](https://kiwi-network.eu/docs/clients/kiwi-fox/).

## Status

kiwi-fox does not promise that a profile is undetectable. Signals from the
hardware, such as the frames your GPU draws, are the same for every profile on
one machine; see [Isolation and its limits](docs/isolation.md). kiwi-fox has
no automation and is made for interactive browsing only.

## License

GPL-3.0-or-later; see [LICENSE](LICENSE).

The engines ([Camoufox](https://github.com/daijro/camoufox) under MPL-2.0,
Mozilla's Firefox and the Tor Project's Tor Browser) are downloaded to your
machine and never redistributed here. Three small pieces derived from MPL-2.0
sources are included and stay under that license:

- `src/kiwi_fox/core/fingerprint/data/webgl-windows.json`: WebGL records of
  real Windows machines, from Camoufox's `webgl_data.db`
- `tests/unit/data/camoufox-properties-*.json`: Camoufox's configuration
  schema, so that tests can check that only keys an engine knows are sent
- `src/kiwi_fox/core/fingerprint/sanitizer.py`: a port of Firefox's
  `dom/canvas/SanitizeRenderer.cpp`
