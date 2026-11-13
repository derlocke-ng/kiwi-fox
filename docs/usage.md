# Using kiwi-fox

This page shows how you create, start and organise profiles, with the command
line and with the app. A **profile** is one browser identity with its own
storage. It runs one **engine** (Camoufox, Firefox or Tor Browser) and usually
goes out through an **exit**, a proxy connection that kiwi-proxy keeps.
Commands take a profile by its name or by the first characters of its id.

## The app

`kiwi-fox-gui`, **Kiwi Fox** in your app grid, does everything the command
does. Its window lists your profiles, grouped by tag. In the header bar:

- **New profile** (the plus) creates a profile.
- The gear opens **Preferences** (also Ctrl+,).
- The menu holds **Stop everything** and **About Kiwi Fox**.

Each profile's menu has **Details**, **Edit…**, **Version…**,
**Open in Kiwi Proxy** (when it has an exit), **Duplicate**, **Snapshots…**
and **Delete**. The window opens at 1040×840 and keeps the size you leave it
at.

## Create a profile

```bash
kiwi-fox new shop --exit work                        # Camoufox on the exit "work"
kiwi-fox new plain --exit work --engine firefox      # stock Firefox
kiwi-fox new anon --exit tor-de --engine torbrowser  # Tor Browser on a Tor exit
kiwi-fox new bare --no-proxy                         # this machine's own connection
```

Every profile needs either `--exit` with an exit from `kiwi-proxy list` or
`--no-proxy`. [Proxies and provider modules](proxies.md) says how you make an
exit. Other options that every engine takes:

| Option | Meaning |
|---|---|
| `--engine camoufox\|firefox\|torbrowser` | The browser. The default is `camoufox`. See [Browser engines](engines.md). |
| `--tag TAG` | A tag for grouping, repeatable or comma-separated. See [Tags](#tags). |
| `--desktop-entry` | An entry of its own in the app grid. See [A profile in the app grid](#a-profile-in-the-app-grid). |
| `--appearance host\|light\|dark` | Light or dark. `host`, the default, follows your desktop. |
| `--engine-version VERSION` | A specific installed version of the engine. |

A Camoufox profile takes more options for its identity, such as `--country`
and `--card`; see [The Camoufox identity](camoufox.md). In the app,
**New profile** asks for the name, the browser, the proxy and these settings.

## Start and stop a profile

```bash
kiwi-fox run shop          # start the container and the browser
kiwi-fox quit shop         # close the browser; the container follows
kiwi-fox up shop           # start the container without the browser
kiwi-fox stop shop         # stop the container, browser and all
kiwi-fox stop              # stop every profile
kiwi-fox list              # every profile, with its exit and state
```

`list` shows each profile's state as `open` (the browser runs), `container`
(only the container runs) or `stopped`. `run` takes these options:

| Option | Meaning |
|---|---|
| `--url URL` | Open this address when the browser starts. |
| `--wait` | Stay in the terminal until the browser closes. Ctrl+C leaves it running. |
| `--strict` | Refuse to start when the profile check finds warnings, not only errors. |
| `--restore`, `--as-is` | Answer the question about a newer snapshot in advance; see [Snapshots](snapshots.md#before-a-profile-starts). |

## Browser and container

A profile has two parts that start and stop separately: its **container**,
which joins the exit's gateway, and the **browser** that runs in it. In the
app, each profile has a button for each: **Start browser** or
**Quit browser**, and **Start container** or **Stop container**. Its row says,
for example, "browser open · container running".

When the browser quits, its container stops too, and lets go of the exit.
kiwi-proxy takes the exit down when nothing else uses it. This happens however
you quit the browser: with **Quit browser**, with `kiwi-fox quit`, or by
closing its window. If you want the browser to start again at once, keep the
container running instead:

- in the app: Preferences, **General**, "When the browser quits": **Keep it
  running**
- on the command line: `kiwi-fox prefs --keep-container on`

The same happens however the profile was started: from the app, the command
line or the app grid. Each container gets a **watcher**, a systemd user unit
named `kiwi-fox-watch-…`. It takes a [snapshot](snapshots.md) when the browser
closes, and removes the container and lets go of the exit when the container
ends.

### Repair

An unclean shutdown can leave containers and lock files behind.
**Repair on start** (Preferences, **General**, on by default) cleans up when
the app starts: it removes the containers kiwi-fox left, clears stale profile
locks and gives running containers their watcher. `kiwi-fox repair` does the
same by hand, and `kiwi-fox prefs --repair-on-start off` turns the automatic
repair off.

**Check and repair** on the **Maintenance** page of Preferences runs Podman's
quick storage check and names every broken container and whose it is. Repair
removes the ones that belong to Kiwi apps, and others only when you say so.

## Preferences

| Page | What you set there |
|---|---|
| **General** | What happens when the browser quits, repair on start, the engine and exit a new profile starts with (or "Ask every time"), and the window size with a Reset. |
| **Engines** | What happens when a new engine release is out, and the default version of each engine. See [Browser engines](engines.md#versions). |
| **Snapshots** | The snapshot folder, shared with kiwi-proxy. See [Snapshots](snapshots.md). |
| **Maintenance** | **Set up environment** (`kiwi-fox setup`), **Check environment**, and **Check and repair**. |

`kiwi-fox prefs` prints the preferences that the command line can change:
`--keep-container`, `--repair-on-start` and `--engine-updates`. They are kept
in `~/.config/kiwi-fox/settings.json`.

## Tags

A profile can carry tags, for grouping and finding:

```bash
kiwi-fox new shop --exit work --tag shops --tag eu
kiwi-fox set shop --tag private        # add one
kiwi-fox set shop --untag eu           # remove one
kiwi-fox set shop --no-tags            # remove all
kiwi-fox list --tag shops              # only the profiles with this tag
kiwi-fox list --by-tag                 # grouped by their first tag
```

The app groups the list by each profile's first tag, with the untagged
profiles last, and shows every tag on the row. A profile's app-grid entry
lists its tags as keywords, so the app grid finds it by them.

## A profile in the app grid

A profile can have a desktop entry of its own, so that your desktop starts it
like any app:

```bash
kiwi-fox set shop --desktop-entry      # or --desktop-entry on new
kiwi-fox set shop --no-desktop-entry   # take it away
kiwi-fox set shop --icon kiwi-fox-orange
kiwi-fox desktop list                  # which profiles have an entry, and where
kiwi-fox desktop sync                  # rewrite every entry
```

In the app, it is the **Show in the app grid** switch and the **Its icon** row
in **Edit…**. The entry is
`~/.local/share/applications/eu.kiwinetwork.KiwiFox.profile-<id>.desktop`,
where `<id>` is the start of the profile's id. It carries the profile's name,
its icon and a **Stop** action. Renaming the profile updates it, and deleting
the profile removes it. `desktop sync` is needed only after the install moved;
the installer runs it.

The icon is one of `kiwi-fox` (the default), `kiwi-fox-orange`, `firefox`,
`camoufox`, `torbrowser` or `web-browser`. The three engine icons are copies
of the icons an installed engine ships.

While the browser runs, its window carries the entry's id, so the dock and the
overview show the profile's name and icon. A profile without an entry shows as
Kiwi Fox.

## Change a profile

`kiwi-fox set` changes a profile. These options work for every engine:

| Option | Meaning |
|---|---|
| `--name NAME` | Rename it. |
| `--exit EXIT`, `--no-proxy` | Move it to another exit, or take it off its exit. |
| `--appearance host\|light\|dark` | Light or dark. |
| `--icon ICON` | Its app-grid icon. |
| `--tag`, `--untag`, `--no-tags` | Its tags. |
| `--desktop-entry`, `--no-desktop-entry` | Its app-grid entry. |

A Camoufox profile has more options for what it reports; see
[The Camoufox identity](camoufox.md#change-a-profile). A change applies when
the browser starts next. In the app, **Edit…** in the profile's menu does the
same.

## Delete a profile

```bash
kiwi-fox delete shop --yes --purge
```

This stops the profile and removes its folder with its identity and browser
data, and its app-grid entry. An exit you made in kiwi-proxy stays there.
**Delete** in the app does the same.

**Known gap:** without `--purge`, `delete` removes only the browser data, and
the profile stays in `kiwi-fox list`.

## Every command

| Command | What it does |
|---|---|
| `new NAME` | Create a profile. |
| `list` | List the profiles. |
| `show PROFILE` | Everything about one profile. |
| `set PROFILE` | Change a profile. |
| `delete PROFILE --yes` | Delete a profile. |
| `run PROFILE` | Start its container and browser. |
| `up PROFILE` | Start its container only. |
| `quit PROFILE…` | Close its browser. |
| `stop [PROFILE…]` | Stop its container and browser; all profiles without a name. |
| `repair` | Clean up what an unclean stop left. |
| `prefs` | Show or change the preferences. |
| `desktop sync`, `desktop list` | The profiles' app-grid entries. |
| `check [PROFILE]` | Check that a Camoufox profile's values fit together. |
| `selfcheck PROFILE`, `compare A B` | Measure what pages see; see [The Camoufox identity](camoufox.md#check-a-profile). |
| `webgl PROFILE`, `gpus`, `fonts [PROFILE]` | A Camoufox profile's graphics card and fonts. |
| `engine …` | Install and manage engines; see [Browser engines](engines.md). |
| `snapshot …` | Encrypted copies for your other devices; see [Snapshots](snapshots.md). |
| `test ADDRESS` | Measure where a proxy address comes out, without saving anything. |
| `module …` | kiwi-proxy's provider modules; the same as `kiwi-proxy module …`. |
| `dns sync`, `dns update` | kiwi-proxy's DNS data. |
| `setup` | The first setup; see [Install](install.md#first-setup). |
| `doctor` | Check the environment. |
| `ps` | List kiwi-fox's containers. |
| `reap` | Release gateways whose browser has exited, then run kiwi-proxy's cleanup. |

`kiwi-fox COMMAND --help` lists every option of a command.
