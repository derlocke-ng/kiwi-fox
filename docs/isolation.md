# Isolation and its limits

This page says how kiwi-fox keeps a profile's traffic on its exit and its data
apart from your other profiles, and what it does not hide. Read it before you
rely on a profile to keep two identities apart.

## How a profile is sealed

Two containers make up a profile that runs on an exit:

```text
gateway container   kiwi-proxy's, one per exit; it owns the network namespace
                    and is shared by every profile and tool on that exit
                    firewall: everything is dropped except the one permitted destination
                    forwarder: adds the proxy's credentials; the browser never sees them
                    DNS: names are resolved through the same exit, with the exit's blocklists
browser container   joins the gateway's network namespace and has no route of its own
```

A network namespace is a separate network stack with its own routes and
firewall. The browser container joins the gateway's namespace, so the only way
out is the one the gateway allows. This is the kill switch: there is no route
to fall back on, rather than software that has to notice a failure. If the
gateway stops, the profile loses its connection.

Other profiles on the same exit, a kiwi-pentesting tool or `kiwi-proxy up` can
be in the same namespace. When a browser closes, the gateway stays for the
others; kiwi-proxy takes it down when nothing uses it any more. How the gateway
is built is on
[kiwi-proxy's architecture page](https://kiwi-network.eu/docs/clients/kiwi-proxy/architecture/).

A profile with no proxy has no gateway. Its browser container gets a network
of its own on this machine's connection, and nothing is sealed.

## The browser container

- It runs in rootless Podman as your user.
- Every Linux capability is dropped except `SYS_CHROOT`, which Firefox's own
  sandbox needs for its content processes. The container runs with
  `no-new-privileges`.
- SELinux labelling is turned off for the container (`label=disable`), so the
  boundary is the network namespace and the mounts, not SELinux.
- Of your machine's files, it sees only the engine (read-only), the profile's
  own browser data and downloads, a few files kiwi-fox writes for it (fonts,
  DNS, its start script), and your Wayland socket for the window. It does not
  see your X11 display, your home folder or the other profiles.
- It reaches the GPU's device nodes for rendering; see
  [Hardware rendering](install.md#hardware-rendering).

## Between profiles

Each profile has its own folder in `~/.local/share/kiwi-fox/profiles/`, with
its own browser data and downloads, and its own container. Profiles do not
share cookies, storage, history or caches. A Camoufox profile also has its own
fingerprint, and `kiwi-fox check` makes sure that no two profiles share the
seeds it is drawn from.

Profiles on the same exit share its IP address and its Tor circuits; see
[Proxies and provider modules](proxies.md#profiles-on-one-exit-share-it).

## What it does not hide

kiwi-fox does not promise that a profile is undetectable.

- **Hardware.** Profiles are separated in storage, IP address and every value
  the engine can spoof, but not in signals that come from the hardware: the
  frames your GPU actually draws and the timing of your hardware. These are the
  same for every profile on one machine, so a detector that measures them can
  see that two profiles run on the same computer.
  [Detection notes](detection-notes.md) has the measurements.
- **Software rendering.** A browser that draws without a GPU looks like a
  virtual machine, whatever it claims; see
  [Hardware rendering](install.md#hardware-rendering).
- **Downloads by kiwi-fox itself.** Engines, language packs and the GPU probe
  helpers are downloaded on this machine's own connection, not through an
  exit.
- **What you do.** Logging in to the same account from two profiles links
  them, whatever kiwi-fox does.

kiwi-fox has no automation. It does not run bots and does not create accounts
in bulk. It is made for interactive browsing only.
