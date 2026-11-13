# Browser engines

A profile runs one of three browsers, which kiwi-fox calls **engines**. You
choose the engine when you create the profile, and it stays fixed after that,
because the browser data of one engine cannot be carried into another. This
page says what each engine shows a page, how kiwi-fox downloads and checks it,
and how you manage its versions.

| Engine | What a page sees |
|---|---|
| `camoufox` (the default) | An ordinary Windows 11 machine with its own region. The values are spoofed, fit together and stay the same from one session to the next. |
| `firefox` | Stock Mozilla Firefox, which spoofs nothing. A page sees this machine's own values. |
| `torbrowser` | The unmodified Tor Browser with its own uniform fingerprint, through an exit on the Tor network. |

Every engine runs in the same kind of container and through the same gateway,
as [Isolation and its limits](isolation.md) describes. Every engine is mounted
read-only into the container, so a profile cannot change it.

## Install an engine

```bash
kiwi-fox engine fetch                       # Camoufox, the newest release
kiwi-fox engine fetch --engine firefox      # Mozilla's Firefox
kiwi-fox engine fetch --engine torbrowser   # Tor Browser
kiwi-fox engine list                        # what is installed, and where
```

`kiwi-fox setup` installs Camoufox. Firefox and Tor Browser are installed only
when you ask for them. Engines are kept in
`~/.local/share/kiwi-fox/engines/`, one folder per engine and version. In the
app, the **Engines** page of Preferences shows each engine, and **Manage…**
opens the list of its versions with Install and Remove.

## Camoufox

[Camoufox](https://github.com/daijro/camoufox) is a Firefox build that can
report spoofed values to a page. A Camoufox profile uses this to claim a
Windows 11 machine; [The Camoufox identity](camoufox.md) describes what it
claims and how you change it.

kiwi-fox downloads Camoufox from the project's releases on GitHub.
**Known gap:** kiwi-fox does not check a signature or checksum for this
download.

After a download, kiwi-fox adjusts the build so that it behaves like stock
Firefox. It reverts these changes of Camoufox's and keeps a backup of every
file it edits:

| Tweak | What it restores |
|---|---|
| `search` | Search from the address bar. |
| `chrome` | Firefox's own tab bar, toolbar and window controls. |
| `window-rounding` | A window that can be maximised normally. |
| `policies` | DuckDuckGo as a search engine, and hardware acceleration. |
| `urlbar-tips` | The address bar's tips. |

It also sets DuckDuckGo as the default search and adds Firefox's GPU probe
helpers from Mozilla's servers, which the
[hardware rendering check](install.md#hardware-rendering) uses. These commands show or
change that state:

```bash
kiwi-fox engine tweaks              # which tweaks are applied
kiwi-fox engine tweak --all         # apply them (setup does this)
kiwi-fox engine restore             # put every backed-up original back
kiwi-fox engine repair              # re-enable search in the address bar only
kiwi-fox engine default-search ddg  # another default search; --list shows the ids
kiwi-fox engine helpers             # add the GPU probe helpers; --remove takes them out
```

## Firefox

The `firefox` engine is Mozilla's own build, for when you want an ordinary
Firefox through an isolated exit rather than a disguise. It sets no
fingerprint. A page sees this machine's real values, so nothing is faked and
nothing can contradict a claim.

- kiwi-fox downloads the en-US x86_64 build from `archive.mozilla.org` and
  checks it the way Mozilla documents: the signature over `SHA512SUMS` against
  Mozilla's release key, which kiwi-fox has pinned, then the SHA-512 of the
  download.
- Firefox's own updates are turned off. You update it with
  `kiwi-fox engine fetch --engine firefox`.
- The browser does not offer a page your host addresses as WebRTC candidates,
  so a page cannot read them around the proxy.
- It renders with its own fonts from the browser image (Liberation and Noto),
  so pages that ask for Arial or Times get a font with the same metrics.

```bash
kiwi-fox new plain --exit work --engine firefox
kiwi-fox run plain
```

The identity options of `new` (`--card`, `--form`, `--seed` and the others)
are refused for a Firefox profile. You can change its name, exit, appearance,
icon, tags and app-grid entry with `kiwi-fox set`.

## Tor Browser

The `torbrowser` engine is the unmodified Tor Browser bundle, connected
through an exit on kiwi-proxy's tor module. It keeps Tor Browser's own uniform
fingerprint, which is the same for every Tor Browser user.

```bash
kiwi install kiwi-plugin-tor
kiwi-fox engine fetch --engine torbrowser
kiwi-proxy add tor-de --module tor --country de
kiwi-fox new anon --engine torbrowser --exit tor-de
kiwi-fox run anon
```

- **It runs without a Tor of its own.** As in Whonix, the browser's bundled
  Tor is not started. The browser connects to the gateway, whose only route is
  the tor module.
- **One circuit per site.** Tor Browser keys a circuit (a path through the Tor
  network) to each first-party site with its SOCKS credentials. The gateway
  passes these credentials through to Tor, so sites stay on separate circuits.
- **New Identity and the circuit display work.** With kiwi-proxy 0.10 or
  newer, the browser reaches the exit's Tor control port through a filter in
  the gateway. With an older kiwi-proxy, it runs without a control port.
- **DNS is resolved at the exit**, so `.onion` addresses work.
- **It needs a Tor exit that passes SOCKS credentials through.** kiwi-proxy
  makes new Tor exits like that by default. A Tor Browser profile cannot run
  without a proxy or on another kind of exit. If you hold a Tor exit to a few
  countries or relays, `new` warns that this makes you stand out among Tor
  users.
- **The download is verified** with `gpgv` against the Tor Browser
  Developers' signing key, which kiwi-fox has pinned by fingerprint. Versions
  older than 15.0 are refused. kiwi-fox adds one empty marker file to the
  bundle, so that Tor Browser keeps its profile outside the read-only mount;
  it changes nothing else.
- **Pages always see light mode**, as in every Tor Browser. The window itself
  follows the profile's appearance.

## Versions

A Camoufox profile is tied to the Camoufox version it was created with,
because its fingerprint (for example its user agent) is made for that version.
A Firefox or Tor Browser profile follows the engine's default version, or the
newest installed one when no default is set, unless you pin it to a version.

```bash
kiwi-fox engine list --available            # every release, installed or not, and who uses it
kiwi-fox engine use shop 158.0.1            # move a Camoufox profile to another version
kiwi-fox engine use plain 147.0             # pin a Firefox or Tor Browser profile
kiwi-fox engine use plain newest            # let it follow the newest again
kiwi-fox engine default 158.0.1             # the version new Camoufox profiles get
kiwi-fox engine default newest --engine firefox
kiwi-fox engine remove 152.0.4              # remove a version no profile uses
```

- `engine use` moves a Camoufox profile only when its fingerprint fits the
  other version, and its user agent moves with it.
- A version that a profile uses cannot be removed; the error names the
  profiles.
- Pinning a Tor Browser profile to an older version than the newest installed
  warns you that it stands out and misses security fixes.

In the app, **Version…** in a profile's menu does the same as `engine use`.

## New releases

kiwi-fox looks for new releases of the engines you use at most once a day.
What it does then is a preference:

| `kiwi-fox prefs --engine-updates` | In the app | What happens |
|---|---|---|
| `tell` (the default) | Tell me, and I install it | It says that a release is out. |
| `auto` | Install it by itself | It installs the release. |
| `off` | Do nothing | Nothing. |

`kiwi-fox engine check` looks now. Installing a release never removes an older
version, and an installed release does not move a Camoufox profile to it.
