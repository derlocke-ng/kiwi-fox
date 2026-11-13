# Install

This page says what kiwi-fox needs, how to install it, what the first setup
does, and how to update and remove it. kiwi-fox is installed for your own user
only. It needs no root rights, because its containers run in rootless Podman,
which means Podman containers that run as your own user.

## What you need

| What | Why |
|---|---|
| Linux on x86_64 with rootless Podman | Every browser runs in a Podman container as your user. The engines kiwi-fox downloads are x86_64 builds. |
| [kiwi-proxy](https://kiwi-network.eu/docs/clients/kiwi-proxy/) | It runs the exits and their gateways. kiwi-fox imports it and runs its setup. |
| Python 3.12 or newer, with pydantic 2.6 or newer | The command and the app are written in Python. |
| A Wayland session | The browser window opens through your Wayland socket. Without one, the browser starts but its window cannot open. |
| GTK 4, libadwaita and PyGObject | Only for the app, **Kiwi Fox**. The command works without them. |
| `secret-tool` | `kiwi install` checks for it, and the environment check reports it when it is missing. |
| `gpg` and `gpgv` | They verify the Firefox and Tor Browser downloads. Without them, those two engines cannot be installed. |
| `systemd-run` (optional) | Each profile's watcher runs as a systemd user unit. Without a user manager it runs as a detached process instead. |
| `nvidia-container-toolkit` with its CDI file | Only on a machine whose desktop runs on the proprietary NVIDIA driver. See [Hardware rendering](#hardware-rendering). |

[Snapshots](snapshots.md) need kiwi-proxy 0.8.1 or newer and whatever
kiwi-proxy's snapshots need. Everything else works without them.

## Supported systems

kiwi-fox belongs to the Kiwi desktop, a Fedora Atomic workstation. The browser
image is based on Fedora 43. These are the tests that run automatically:

| What is tested | Where |
|---|---|
| Unit tests and the linter, against kiwi-proxy's newest release | GitHub Actions, `ubuntu-latest` with Python 3.12 |
| The app's windows, under Xvfb | GitHub Actions, Ubuntu 24.04 |
| The browser image: built without a cache, then checked from inside | GitHub Actions, `ubuntu-latest` with Podman |

No test in CI starts a profile. The leak tests in `tests/leak` need a running
profile and are run by hand.

## Install with kiwi

```bash
kiwi install kiwi-fox
kiwi-fox setup
```

kiwi-fox is in the [Kiwi catalog](https://kiwi-network.eu/docs/desktop/catalogs/)
with user scope. It depends on kiwi-proxy, so `kiwi install` installs
kiwi-proxy first when it is missing.

## Install from a checkout

```bash
git clone https://github.com/derlocke-ng/kiwi-fox
cd kiwi-fox
./install.sh install
kiwi-fox setup
```

`install.sh` expects kiwi-proxy in `~/.local/lib/kiwi-proxy` and says so when
it is not there. It reads these environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `KIWI_PREFIX` | `~/.local` | Where the program, the commands and the app entry go. |
| `KIWI_GUI` | `1` | `0` installs without the app, for a machine without a desktop. |
| `KIWI_SCOPE` | `user` | With any other scope, the installer does nothing: kiwi-fox is a user app only. |

## What the installer writes

| Path | What it is |
|---|---|
| `~/.local/lib/kiwi-fox/` | The Python package, the browser image's container files and the icons a profile can have in the app grid. |
| `~/.local/bin/kiwi-fox` | The command. |
| `~/.local/bin/kiwi-fox-gui` | The app (not with `KIWI_GUI=0`). |
| `~/.local/share/applications/eu.kiwinetwork.KiwiFox.desktop` and its icon | The app's entry in your app grid. |

The installer also rewrites the app-grid entries of your profiles, so that
they point to the new install (`kiwi-fox desktop sync`). It removes the
blocklist timer that kiwi-fox had before 0.3.0, because kiwi-proxy's timer
replaces it.

kiwi-fox keeps its own data in these folders:

| Path | What it holds |
|---|---|
| `~/.local/share/kiwi-fox/profiles/` | One folder per profile: its settings, its fingerprint and its browser data. |
| `~/.local/share/kiwi-fox/engines/` | The installed versions of Camoufox, Firefox and Tor Browser. |
| `~/.config/kiwi-fox/` | The app's preferences (`settings.json`) and window size. |

## First setup

`kiwi-fox setup` prepares everything a profile needs before it can start. It
is not part of the install because it downloads a lot. It is safe to run again
at any time.

1. It builds the browser image, `kiwi-fox/browser:latest`, from
   `containers/browser/Containerfile`. The image is based on Fedora 43.
2. It downloads the newest Camoufox release from the
   [Camoufox releases on GitHub](https://github.com/daijro/camoufox/releases),
   if no version is installed yet. The download of Camoufox 158.0.1 is about
   1.3 GB. `--engine-version` asks for a specific version.
3. It adjusts that Camoufox build so that it behaves like stock Firefox: it
   reverts some of Camoufox's changes to the browser's interface, sets
   DuckDuckGo as the default search, and adds Firefox's GPU probe helpers from
   Mozilla. [Browser engines](engines.md#camoufox) says what these are.
4. It measures which GPU the browser will draw with.
5. It runs `kiwi-proxy setup`: the gateway image, the DNS data, the default
   blocklist and the images of the provider modules you installed.

Firefox and Tor Browser are not downloaded by `setup`. Install them when you
want them; see [Browser engines](engines.md#install-an-engine).

## Check the setup

```bash
kiwi-fox doctor
```

`doctor` lists Podman, `secret-tool`, the installed engines, your Wayland
session, kiwi-proxy's version, the DNS data, the images, your profiles and the
provider modules. When Camoufox is installed, it also measures how the browser
draws, as described in the next section. It ends with exit code 1 when Podman,
an engine or an image is missing, or when the browser would draw in software. In the app, **Check environment** on the
**Maintenance** page of Preferences lists what is missing.

## Hardware rendering

The browser must draw on a real GPU. A browser that draws in software produces
the frames that virtual machines and headless servers produce, and sites can
read those frames, whatever the profile claims.

`kiwi-fox doctor` and `kiwi-fox setup` measure this with the probe that
Firefox itself runs at startup. They run it in a throwaway container with no
network and print either the GPU it found or `SOFTWARE`.

- On most machines, the browser container gets the GPU's device nodes and uses
  Mesa, the graphics drivers of your distribution.
- Where the desktop runs on an NVIDIA card with the proprietary driver, a
  container with Mesa cannot use that card. kiwi-fox then passes the host's
  NVIDIA driver into the container through `nvidia-container-toolkit`, which
  needs its CDI file (`/etc/cdi/nvidia.yaml` or `/var/run/cdi/nvidia.yaml`).
- Without that file, kiwi-fox tries the other GPU of the machine, if it has
  one. The measurement says whether that worked.

To override the choice, set `KIWI_FOX_GPU` to `mesa`, `nvidia` or `software`.
[Detection notes](detection-notes.md#first-is-the-browser-drawing-on-a-gpu)
has the measurements behind this.

## Update

`kiwi update` updates kiwi-fox like every other Kiwi app, and kiwi-proxy with
it. After an update, run `kiwi-fox setup` again. It rebuilds the browser image
only when the new version changed the files the image is built from, and does
nothing otherwise. Until then, `kiwi-fox doctor` reports the image as
outdated.

## Uninstall

```bash
kiwi uninstall kiwi-fox            # or: ./install.sh uninstall
kiwi uninstall kiwi-fox --purge    # or: ./install.sh uninstall --purge
```

An uninstall first stops every profile. It then removes the program, the
commands, the app entry, the icon and the app-grid entries of your profiles. It
keeps `~/.local/share/kiwi-fox`, so a new install continues with your profiles
and their identities. `--purge` deletes that folder as well, with every
profile, identity and engine, and the exits that kiwi-fox 0.4 or 0.5 created
for a profile. The exits you created in kiwi-proxy stay, and so does
kiwi-proxy; remove it separately if you no longer need it.
