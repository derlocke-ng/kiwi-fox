# kiwi-fox documentation

kiwi-fox gives you a separate browser for each account you manage and for each
client network you work in. A **profile** is one such browser identity, with
its own storage, in its own rootless Podman container. An **engine** is the
browser a profile runs: Camoufox, which shows a page a spoofed Windows 11
machine, stock Firefox, or Tor Browser. An **exit** is the proxy connection a
profile goes out through; exits and their **gateways**, the containers that
seal a profile's network, belong to
[kiwi-proxy](https://kiwi-network.eu/docs/clients/kiwi-proxy/).

| Page | For | What it covers |
|---|---|---|
| [Install](install.md) | everyone | requirements, install, first setup, hardware rendering, update, uninstall |
| [Using kiwi-fox](usage.md) | everyone | profiles, the browser and its container, preferences, tags, the app grid, every command |
| [Proxies and provider modules](proxies.md) | everyone | putting a profile on an exit, sharing an exit, Tor, VPN and other modules |
| [Browser engines](engines.md) | everyone | Camoufox, Firefox and Tor Browser, their downloads and versions |
| [The Camoufox identity](camoufox.md) | everyone with Camoufox profiles | what a new profile reports, changing it, graphics, language, location |
| [Snapshots](snapshots.md) | everyone with several devices | encrypted copies of your profiles for your other devices |
| [Isolation and its limits](isolation.md) | everyone | how a profile is sealed, and what it does not hide |
| [Detection notes](detection-notes.md) | the curious, contributors | what a detector can still see, measured |
| [Decisions](decisions.md) | contributors | why things are the way they are |
| [Development](development.md) | contributors | running from a checkout, tests, CI, releases |

These pages are also on
[kiwi-network.eu](https://kiwi-network.eu/docs/clients/kiwi-fox/), where they
are pulled from this folder at every release.
