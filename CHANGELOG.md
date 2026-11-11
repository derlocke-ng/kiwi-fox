# Changelog

## 0.10.4

- **Tor Browser in dark.** Its window follows the profile's appearance (the
  desktop's by default), like the other browsers; pages still see light, as in
  every Tor Browser. Edit… shows Appearance for Tor Browser profiles too, and
  `kiwi-fox new --engine torbrowser --appearance` keeps it.
- Preferences → Engines: "157.0.1 · not installed", the middle dot like the other rows.

## 0.10.3

- **New Identity, the circuit display and onion-site keys in Tor Browser.** On a
  Tor exit with kiwi-proxy 0.10's control filter, Tor Browser talks to its own
  Tor through the gateway (TOR_SKIP_LAUNCH, 127.0.0.1:9151) instead of running
  proxy-only; with an older kiwi-proxy it stays proxy-only, as before.

## 0.10.2

- **An icon per profile in the app grid** (Edit… → Its icon, `kiwi-fox set
  --icon`): Kiwi Fox's own, a colored Kiwi Fox (orange to start with; more go into
  `data/profile-icons/kiwi-fox-*.svg`), the icon an installed engine ships (your
  own copy of Firefox's, Camoufox's or Tor Browser's; a copy is kept if the engine
  goes), or the icon theme's generic browser.
- **A Tor exit's Only and Never lists** show wherever a profile names its exit;
  the old single country showed nothing for them.
- DNS reads in words: "names at the exit", "a resolver in the gateway, via
  google", not "remote" and "resolver via google" for an exit that does not use it.

## 0.10.1

- **Tor Browser 16.0.2 was offered and its download was a 404.** A version folder
  on dist.torproject.org need not hold a Linux release; the list now keeps only
  versions whose Linux download is there (16.0.1 today).

## 0.10.0

**Engine versions.**

- **Browser engines** (the menu) lists every version of Camoufox, Firefox and Tor
  Browser: installed or not, which profiles use it, Install and Remove, older
  releases behind an expander, and "Repair search" on a Camoufox build whose
  address bar cannot search. "Look for new versions" asks the publishers now.
- **A version in use cannot be removed**; the dialog names the profiles.
  Installing never removes one.
- **Per profile, Version… in its menu:** a Firefox or Tor Browser profile follows
  the newest installed version or is pinned to one; a Camoufox profile moves to
  another version only when its fingerprint fits it (its user agent moves along).
  Going back is one more click, and the browser is told the downgrade is meant.
- **Preferences → Engines:** when a new version is out (tell me and I install it,
  the default; install it by itself; do nothing), and per engine the version new
  Camoufox profiles get or unpinned profiles use. Kiwi Fox looks once a day.
- **Tor Browser** is never offered below the floor the app enforces, and pinning
  an older one than the newest installed warns that it stands out and misses fixes.
- New Firefox and Tor Browser profiles follow the newest installed version; they
  were pinned to the version of the day before. Existing pins stay as they are.
- Command line: `kiwi-fox engine list --available`, `engine remove`, `engine
  default`, `engine check`, `engine use PROFILE VERSION|newest`, `prefs
  --engine-updates tell|auto|off`.

## 0.9.1

- **Preferences → General, complete:** besides the browser and container, what a
  new profile starts with (engine, and an exit or "Ask every time") and the window
  size with a Reset.
- **Short texts, the rest behind a (?)** that opens the explanation and a link to
  kiwi-network.eu (shared with Kiwi Proxy 0.8.3).
- The menu in the same order as the other two apps, with About Kiwi Fox; the list
  of profiles up to 920 px wide.

## 0.9.0

**The browser and its container, two buttons.** Needs kiwi-proxy 0.8.2.

- **Start browser / Quit browser and Start container / Stop container** on every
  profile, with "browser open · container running" on its row. The container's
  first process is now a small supervisor (the launcher, mounted from the app so
  no image rebuild is needed): it starts the browser, quits it on request, and
  ends with it unless told to keep running. `kiwi-fox up` starts the container
  alone, `kiwi-fox quit` closes the browser, `kiwi-fox list` says open, container
  or stopped.
- **When the browser quits, its container stops**, and lets go of the exit, which
  Kiwi Proxy takes down when nothing else uses it. Preferences → General → "When
  the browser quits" keeps it running instead (`kiwi-fox prefs --keep-container
  on`).
- **The same however it was started.** Before, only `kiwi-fox run --wait` tore
  down: a profile started from the window or the app grid left its container
  exited and its exit up. Every container now gets a watcher, a transient systemd
  user unit, that snapshots the profile when its browser closes and removes the
  container and lets go of the exit when it ends.
- **Repair on start** (Preferences → General, on): leftovers of an unclean
  shutdown are removed, stale locks cleared, running containers given a watcher.
  `kiwi-fox repair` by hand.
- **Check and repair** in the menu: podman's quick storage check, naming every
  broken container and whose it is; Repair removes Kiwi's, and others only when
  you say so.
- **A dead proxy fails at once:** a refused port in under a second, no answer in
  five (it took 37 to 52 seconds). The check is kiwi-proxy 0.8.2's.
- "Open in Kiwi Proxy" in a profile's menu. A restore stops a container that
  runs without its browser first, so it does not keep the replaced folder.
- Preferences has a General page now (Ctrl+,), also without snapshots set up.

## 0.8.0

**Profiles on your other devices.** Profiles go into kiwi-proxy's encrypted
snapshot folder, which your sync client (Nextcloud) carries to your other devices.
Needs kiwi-proxy 0.8.1.

- **What a snapshot holds:** the profile's settings, its fingerprint and its
  browser data — logins, cookies, history, bookmarks, site storage, extensions,
  open tabs, and the database journals an unclean stop leaves. Left out: caches,
  safe-browsing lists, remote settings, crash reports, lock files and the
  downloads. A profile of 243 MB is a 9 MB snapshot.
- **When:** after a profile ran and its browser stopped (the window notices, as do
  `kiwi-fox stop` and `run --wait`; the window catches up on what stopped while it
  was closed), after its settings change, and when asked. Never while it runs.
- **Before it starts:** when the folder holds a newer copy from another device,
  Launch asks: restore and start, start as it is, or cancel; when both changed,
  you choose which wins. The same question comes up in a small window when the
  profile is started from the app grid, and in the terminal for `kiwi-fox run`
  (`--restore` and `--as-is` answer it ahead).
- **In use elsewhere:** a profile open on another device says so in its row and
  asks before it starts here.
- **Restoring:** "In your snapshot folder, not on this device" lists profiles to
  bring here; Snapshots… in a profile's menu shows its history. A profile whose
  exit is not here says to restore that exit in Kiwi Proxy first. A missing engine
  version is offered for install. What was here is kept as a snapshot first.
- **In the app:** Preferences (Ctrl+,) with the Snapshots page, "Snapshot
  everything now", a banner when snapshots are locked, "Use a snapshot folder" on
  a device without profiles.
- **On the command line:** `kiwi-fox snapshot list | now | history | restore |
  forget`; `setup`, `status`, `unlock`, `lock` and `set` are kiwi-proxy's, the same
  folder for every app.

## 0.7.1

- **A bigger window, and the size you leave it at.** The window opened at
  760×620, smaller than its own dialogs (a profile editor is 660×780), so those
  came up squeezed. It now opens at 1040×840, and the size and maximized state
  it has when closed are kept in `config/window.json` for the next start.

## 0.7.0

- **Stock Firefox renders like a Linux desktop.** The browser image's Firefox
  font set was DejaVu alone, so every page asking for Arial, Verdana, Georgia or
  Segoe came out in DejaVu Sans and looked wrong. It now carries Liberation (the
  same metrics as Arial, Times and Courier) and Noto Sans, Serif and Mono, and
  fontconfig's own rules pick them. Camoufox's per-profile fonts are untouched.
  `kiwi-fox setup` rebuilds the image.
- **Where a profile leaves is kiwi-proxy's measurement.** The exit is kiwi-proxy's
  and so is measuring it: a profile's row and details show the exit's own record
  (`kiwi-proxy check`, `up`, a launch, another profile on the same proxy). A
  launch records what it measured on the exit — a provider exit (Tor, Mysterium)
  is measured through the gateway, which the pre-flight could not reach — so both
  apps show the same thing. A profile with no proxy keeps its own record of this
  machine's connection.

## 0.6.2

- Help text and docs still showed `kiwi-fox new … --module tor`, which 0.6.0
  removed: a profile takes one of kiwi-proxy's proxies with `--exit`, and the
  exit on a module is made with `kiwi-proxy add NAME --module tor --country de`.
  `kiwi-fox module countries tor` lists where a module can exit (kiwi-proxy 0.4).

## 0.6.1

- The tag-grouping helper lives in the store, not the GTK window module, so
  the unit tests run without GTK again (0.6.0's CI test job failed on it;
  nothing in the app changed).

## 0.6.0

The window shows up as the profile, proxies are kiwi-proxy's alone, and tags.

- **The running browser shows the profile's name and icon.** The window used to
  announce itself as `camoufox`, which no entry matches, so the dock showed a
  blank. The browser now starts with `--name` (Wayland app id) and `--class`
  (X11 class) set to the profile's own entry id when it has one, else to Kiwi
  Fox's, measured on the engine itself. Profile entries carry the matching
  `StartupWMClass`.
- **kiwi-fox makes no proxies.** `new` takes `--exit PROXY` or `--no-proxy`,
  nothing else; an endpoint given to it is answered with the `kiwi-proxy add`
  to run. `--module`, `--lease`, `--dns-mode` and `--upstream` are gone from
  `new`. The GUI's picker lost Add and Edit and gained **Open Kiwi Proxy** and
  a refresh. Exits 0.3 registered under a profile's id still go with their
  last profile.
- **Tags.** `--tag` on `new` and `set` (repeatable or comma-separated),
  `--untag`, `--no-tags`; `list --tag` filters and `--by-tag` groups; `show`
  prints them. The GUI groups the list by each profile's first tag, with the
  untagged last, shows the rest on the row, and both dialogs have a Tags row.
  A profile's desktop entry lists its tags as keywords.
- **The Firefox engine downloads again.** `engine fetch --engine firefox`
  failed with "SHA-512 did not match": the checksum was looked up by file name
  in Mozilla's SHA512SUMS, which lists that name once per locale and
  architecture, so the en-US x86_64 tarball was checked against an aarch64
  Acholi build. It is looked up by its full path now.

## 0.5.0

Kiwi Fox in the app grid, and its profiles too.

- **The window has its icon again.** GNOME matches a window to its entry by the
  app-id; ours was `dev.kiwinetwork.KiwiFox` beside a `kiwi-fox.desktop`, so the
  shell showed a blank icon and no name. The id is `eu.kiwinetwork.KiwiFox` now,
  like the other kiwi apps; the entry and the icon are named after it; the
  install writes the launcher's absolute path into `Exec` and removes the old
  file names. The app is **Kiwi Fox** in the grid, the title and About — the
  command keeps its dash, the app does not.
- **A profile can be in the app grid.** `--desktop-entry` on `new` or `set`
  (`--no-desktop-entry` takes it away), or the "Show in the app grid" switch in
  the GUI, writes a desktop entry of its own: the profile's name, the Kiwi Fox
  icon, `kiwi-fox run <id>`, and a Stop action. The store keeps it in line — a
  rename rewrites it, deleting the profile removes it — and `kiwi-fox desktop
  sync` rewrites every entry, which the install runs so a moved launcher is
  followed. An uninstall removes them all.

## 0.4.0

A proxy is defined once, in kiwi-proxy, and shared.

- **A profile references a kiwi-proxy exit** instead of owning one. Define the
  proxy in kiwi-proxy — `kiwi-proxy add kiwi-master-tor socks5://10.8.0.1:9050
  --dns remote`, or the Kiwi-Proxy app — and put profiles on it: `kiwi-fox new
  work --exit kiwi-master-tor`, or the GUI's Proxy picker, which lists
  kiwi-proxy's exits and opens kiwi-proxy's own editor for a new one. Profiles on
  one proxy share its gateway. Ad-blocking, DNS mode and credentials are the
  proxy's; a change there reaches every profile on it at the next launch.
- **No proxy at all** is a choice: `--no-proxy`, or the picker's first entry. The
  browser then runs on this machine's own connection with no proxy configured,
  in a network namespace of its own, nothing sealed. Not for Tor Browser, and
  not for `selfcheck`.
- **The shortcuts stay.** `kiwi-fox new NAME ENDPOINT` and `new NAME --module
  tor` make the proxy in kiwi-proxy, named after the profile. It goes with its
  last profile when kiwi-fox made it, and stays when you did.
- **Profiles from 0.3 migrate on first sight.** Each keeps the exit that was
  registered under its own id, so gateway names and Tor circuits are unchanged;
  its password moves into kiwi-proxy's secret store. Several profiles on the
  same upstream can be merged by hand: `kiwi-fox set NAME --exit OTHER`, then
  `kiwi-proxy rm` the spare.
- `kiwi-fox set` takes `--exit` and `--no-proxy`; its `--endpoint`, `--dns-mode`
  and `--upstream` are gone (they are `kiwi-proxy set`'s). On `new`, `--dns-mode`
  and `--upstream` describe a proxy made there. `list` and the GUI name the
  proxy; `show` says what is behind it.
- Tor Browser is held to an exit on the tor module that passes SOCKS auth
  through, which kiwi-proxy 0.3 makes the default; a Camoufox profile can share
  that exit.
- Needs kiwi-proxy 0.3.0 (ad-blocking in remote DNS mode, the passthrough
  default); `kiwi update` brings both.

## 0.3.2

The browser image builds again.

- **`kiwi-fox setup` failed on Fedora 43** at the step that gives the Firefox
  engine its fonts. It globbed `/usr/share/fonts/google-noto-emoji*`, but the
  package is `google-noto-color-emoji-fonts` and its directory is named after it,
  so the copy failed and `2>/dev/null` hid why. The font files now come from the
  packages' own file lists, whatever the directories are called. Built and
  checked on a desktop; nothing in CI builds this image.
- Needs kiwi-proxy 0.2.1: before it no gateway could start, so no profile could
  launch even with the image built. `kiwi update` brings both.

## 0.3.1

The GUI and the texts catch up with 0.3.0.

- **GUI for every engine and exit.** New profile chooses the browser — Camoufox,
  Firefox or Tor Browser — and the exit: an endpoint, or an installed provider
  module with its country and lease. The Windows identity and graphics sections
  are Camoufox's; Tor Browser is held to the tor module.
- **Firefox and Tor Browser profiles open in the GUI.** Details and Edit raised
  "has no fingerprint" for them. Rows now say which browser and exit ("Tor
  Browser · tor · DE"), and Duplicate keeps both.
- **Browser engines** in the menu downloads and updates Firefox and Tor Browser
  (signature-verified) and sets Camoufox up.
- The environment check names the engines and modules the profiles need, and no
  longer fails silently on a machine without podman.
- **`kiwi-fox set` works on Firefox and Tor Browser profiles** (name, endpoint,
  DNS, appearance); it loaded a fingerprint first. `webgl`, `fonts`, `selfcheck`
  and `compare` say they are about Camoufox's Windows machine instead of "has no
  fingerprint".
- A missing Firefox or Tor Browser is a plain error with the right
  `kiwi-fox engine fetch … --engine …`, not a traceback or the wrong command.
- Texts: the install message, `setup`/`list`/`new` help and hints, the README,
  the desktop entry and the About dialog describe three engines, provider modules
  and kiwi-proxy. `kiwi-fox list` shows the browser.
- New screenshots (`make screenshots` renders them from the GUI), and the GUI tests
  run in CI.

## 0.3.0

The proxy engine is its own app now: [kiwi-proxy](https://github.com/derlocke-ng/kiwi-proxy).
kiwi-fox keeps everything browser-shaped and drives kiwi-proxy for the network
half, which kiwi-pentesting, applications on the host and kiwi-server machines can
use too.

- **kiwi-proxy.** The gateway (the sealed namespace, its credential forwarder and
  resolver), the provider modules and the DNS data moved there, with their tests.
  `kiwi install kiwi-fox` brings it along (`DEPENDS=kiwi-proxy`), `kiwi-fox setup`
  runs its setup, and `kiwi-fox module …` is `kiwi-proxy module …`.
- **One exit per profile.** Every profile is a kiwi-proxy exit under the profile's
  own id, so the gateway (`kf-gw-…`), the Tor circuit token and the labels
  kiwi-pentesting looks for are unchanged. `kiwi-proxy list` shows every
  identity; `kiwi-proxy set` edits its endpoint or DNS and kiwi-fox picks that up.
  Profiles from 0.2 get their exit at `kiwi-fox setup` or their next launch.
- **Shared gateways.** Closing a window releases the gateway instead of removing
  it, so a pentest tool or a `kiwi-proxy up` of the same identity keeps its
  connection; a second launch joins a gateway already up for the identity.
  Deleting a profile takes its gateway down.
- **Tor Browser engine.** `--engine torbrowser`: the unmodified bundle through the
  tor module, Whonix-style — no bundled tor (`TOR_PROVIDER=none`), its own uniform
  fingerprint, a circuit per site through the forwarder's passthrough mode, DNS at
  the exit for `.onion`. The download is verified with gpgv against the Tor
  Browser Developers' key, pinned by fingerprint. Any exit but the tor module is
  refused.

Upgrading: kiwi-proxy takes over the DNS data kiwi-fox had downloaded, and
kiwi-fox's own blocklist timer is removed (kiwi-proxy's replaces it). Provider
modules install into kiwi-proxy's directory from their 0.2.0 releases; until a
module is updated, a launch that needs it says which app to update. Run
`kiwi-fox setup` once after updating.

## Earlier

0.2.0 added the stock Firefox engine, 0.1.4 exits from provider modules. See the
[releases](https://github.com/derlocke-ng/kiwi-fox/releases).
