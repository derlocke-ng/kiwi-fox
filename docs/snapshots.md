# Snapshots

A snapshot is an encrypted copy of a profile in a folder that your sync client
(for example Nextcloud) carries to your other devices. With snapshots you can
use the same profile, with its logins and its identity, on your laptop and
your desktop, and you can go back to an earlier state of it. The folder, the
passphrase and the encryption belong to kiwi-proxy, which keeps its exits in
the same folder; see
[kiwi-proxy's snapshot page](https://kiwi-network.eu/docs/clients/kiwi-proxy/snapshots/).

Snapshots need kiwi-proxy 0.8.1 or newer, and `gpg` and `zstd`, which
kiwi-proxy uses to compress and encrypt them.

## Set it up

```bash
kiwi-proxy snapshot setup ~/Nextcloud/kiwi-snapshots   # once per device
kiwi-fox snapshot list
```

`kiwi-fox snapshot setup`, `status`, `unlock`, `lock` and `set` are the same as
the `kiwi-proxy snapshot` commands, because there is one folder and one
passphrase for every Kiwi app. In the app, the **Snapshots** page of
Preferences does the same.

## What a snapshot holds

A snapshot holds the profile's settings, its fingerprint and its browser data:
logins, cookies, history, bookmarks, site storage, extensions and open tabs.
It leaves out what the browser rebuilds by itself (caches, safe-browsing
lists, remote settings, crash reports, lock files) and the profile's
downloads. A profile of 243 MB on disk was a 9 MB snapshot.

## When snapshots are taken

- After a profile ran and its browser stopped.
- After you change its settings with `kiwi-fox set` or **Edit…**.
- When you ask: `kiwi-fox snapshot now`, **Snapshots…** in a profile's menu,
  or **Snapshot everything now** in Preferences.

The first two happen while automatic snapshots are on, which they are unless
you turn them off in kiwi-proxy's snapshot settings. A snapshot is never taken
while the profile's browser runs, and `kiwi-fox snapshot now` skips running
profiles.

## Before a profile starts

- **A newer copy elsewhere.** When the folder holds a newer snapshot from
  another device, kiwi-fox asks before it starts the profile: restore it and
  start, start as it is, or cancel. When the profile changed both here and on
  the other device, you choose which copy wins. The question comes in the app,
  in a small window when you start the profile from the app grid, and in the
  terminal for `kiwi-fox run`. `run --restore` and `run --as-is` answer it in
  advance.
- **In use elsewhere.** A profile that is open on another device says so in
  its row, and kiwi-fox asks before it starts here. The folder can tell only
  as fast as your sync client carries it.

## Restore a profile

```bash
kiwi-fox snapshot list                    # every profile, here and in the folder
kiwi-fox snapshot history shop            # the snapshots of one profile
kiwi-fox snapshot restore shop --fetch    # the newest one; --id picks another
kiwi-fox snapshot forget shop --yes       # delete every snapshot of it from the folder
```

- A restore first keeps what was on this device as a snapshot, unless the
  folder already has that state, so a restore can be undone. Replacing a profile that is here asks first; `--yes` skips the
  question.
- **Its exit comes from kiwi-proxy.** A restored profile whose exit is not on
  this device tells you to restore that exit in Kiwi Proxy first. kiwi-fox
  never creates or restores exits.
- **Its engine.** When the profile needs an engine version this device does
  not have, the app offers to install it, and `restore --fetch` downloads it.
  It is downloaded like any other version; see
  [Browser engines](engines.md#install-an-engine).

In the app, profiles that are only in the folder appear under "In your
snapshot folder, not on this device", where you can bring them here.
