# The Camoufox identity

A Camoufox profile shows every page the same ordinary Windows 11 machine,
with its own screen, graphics card, fonts, region and language. Together these
values are the profile's **fingerprint**: what a page can read from the
browser to recognise it again. This page says what a new profile reports, how
you change it, and how you check it. It applies to Camoufox profiles only;
Firefox and Tor Browser profiles spoof nothing (see
[Browser engines](engines.md)).

## What a new profile reports

A new profile is the most common machine there is, because detectors flag the
values that are rare:

- **Screen:** 1920×1080. With a Camoufox version older than 156, the profile
  gets 2560×1440 instead, because the window of those versions does not fit
  the smaller screen.
- **Fonts:** the fonts that every Windows 11 installation has, and no others.
  `new --extra-fonts` adds a random set of optional fonts as well.
- **Graphics card:** this machine's own card, worded the way Firefox on
  Windows words it. See [Graphics](#graphics).
- **Region:** the country where the exit comes out. `new` measures a plain
  exit itself and takes the last measurement of an exit on a provider module.
  The region sets the locale, the languages, the voices for speech
  and the timezone; the exit's measured timezone wins when there is one.
  `--country` sets the region yourself, `--no-probe` skips the measurement,
  and without both the region is Germany (`DE`).
- **Machine:** a desktop or a laptop, a number of CPU cores and an audio
  sample rate, drawn at random but fitting the graphics card and the screen.
  `--form desktop` or `--form laptop` decides the kind.

The random draw comes from a seed that the profile keeps, so the identity is
the same every time. `new --seed SEED` makes an identity from a given seed
again. Two profiles never share a seed: `new` and `check` refuse that.

The browser also behaves like Firefox on Windows where a page can measure it:
it computes `Math` functions the way Windows does, uses the Windows keyboard
tables and scrollbars, and has no IPv6. After you allow a page to use the
camera or microphone, the devices have Windows names. These settings come from
Camoufox 158 and are ignored by older versions.

## Change a profile

Everything a profile reports can be changed after it was created, in the app
under **Edit…**, or with `kiwi-fox set`:

```bash
kiwi-fox set shop --screen 2560x1440 --cores 12
kiwi-fox set shop --country SE --timezone Europe/Stockholm
kiwi-fox set shop --font-add "Yu Gothic" --font-remove "Open Sans"
kiwi-fox set shop --appearance dark
kiwi-fox set shop --user-agent "Mozilla/5.0 …"
kiwi-fox set shop --default-user-agent
```

| Option | What it changes |
|---|---|
| `--screen WxH` | The claimed screen. A desktop can be 1920x1080 or 2560x1440; a laptop also 1536x864 or 1366x768. |
| `--form desktop\|laptop` | The kind of machine. |
| `--cores N` | The number of logical CPU cores. |
| `--country CC` | The region, one of AT, AU, BE, CA, CH, CZ, DE, DK, ES, FI, FR, GB, IE, IT, NL, NO, PL, SE, US. It sets locale, languages, voices and timezone. |
| `--timezone NAME` | Only the timezone, as an IANA name such as `Europe/Berlin`. |
| `--audio-rate 44100\|48000` | The audio sample rate. |
| `--camera yes\|no` | Whether the machine has a camera. |
| `--font-add FAMILY`, `--font-remove FAMILY` | Optional fonts. `kiwi-fox fonts shop` lists the fonts a profile may or may not have. |
| `--language local\|english` | The browser's language; see [Language](#language). |
| `--location ask\|exit` | What a page gets when it asks for the location; see [Location](#location). |
| `--appearance host\|light\|dark` | Light or dark, for the browser and for what pages are told. `host` follows your desktop. |
| `--user-agent TEXT` | Replaces the user agent. `check` warns when it contradicts the rest. `--default-user-agent` goes back to the engine's own. |

All changes are checked together, and nothing is saved unless the result is
coherent, which means that all values still fit together. One thing cannot be
set because it does not exist for a page: the Windows version. Firefox sends
the same user agent on Windows 10 and 11.

A change applies at the next start of the browser. `kiwi-fox set` also takes
the options that every profile has (name, exit, icon, tags, app-grid entry);
[Using kiwi-fox](usage.md#change-a-profile) lists them.

## Graphics

Firefox does not tell a page which graphics card you have. It reports the
*group* the card is in, with the same text for every card in the group. For
example, an RTX 4060 on real Windows reads `ANGLE (NVIDIA, NVIDIA GeForce GTX
980 Direct3D11 vs_5_0 ps_5_0), or similar`, and so do a GTX 1650 and an RTX
4090. That text is what a profile reports, and you choose the card it is
derived from:

```bash
kiwi-fox gpus                              # every card, grouped by what Firefox shows for it
kiwi-fox new shop --exit work --card "RTX 3060"
kiwi-fox webgl shop --card "UHD 620"       # change it later
kiwi-fox webgl shop --exact                # also name the exact model
kiwi-fox webgl shop --mode off             # no WebGL at all
```

| Mode | A page sees |
|---|---|
| `host` (the default) | This machine's card, worded the way Firefox on Windows words it. |
| `preset` | The card you chose with `--card`, worded the same way. |
| `custom` | Your own text, given with `--vendor` and `--renderer`. |
| `off` | No WebGL at all. This is rare on Windows. |
| `raw` | Nothing rewritten: Linux wording and limits under a Windows browser. Only for measuring and testing. |

`--exact` puts the card's own model name into the one field that can carry
it, the debug renderer (`UNMASKED_RENDERER_WEBGL`). Stock Firefox does that
only when a hidden setting is changed, so it is the rarer choice. The main
renderer field keeps the group's text either way.

Whatever a profile claims, the frames are drawn by the GPU of this machine.
For that reason the browser must draw on a real GPU; see
[Hardware rendering](install.md#hardware-rendering).

## Language

A profile is the Firefox of its region. A Dutch profile is a Dutch Firefox,
with Dutch menus, Dutch form messages, `nl, en-US, en` as its languages and
Dutch date formats. The list of languages and the `Accept-Language` header are
the ones that build of Firefox has. kiwi-fox downloads the language pack from
Mozilla on this machine before the profile's first start and keeps a copy.

```bash
kiwi-fox set shop --language english   # an English Firefox used in that region
kiwi-fox set shop --language local     # back to the region's own
```

## Location

When a page asks for the location, the profile does one of two things:

- `ask` (the default): Firefox asks you, as it does everywhere. If you allow
  it, the page gets no position, because the browser has no location service
  to ask.
- `exit`: every page that asks gets the position where the exit was measured,
  without a question. This needs kiwi-proxy 0.20 or newer and an exit that has
  been measured. Few real browsers give every page their location, so this
  setting is rare.

## Window size

With Camoufox 156 or newer, the window opens at the size Firefox itself picks
on the claimed screen (90% of it, at most 1280×1040), and it comes back at the
size you leave it at. It never opens larger than the claimed screen. You can
resize it freely, but a *maximised* window is as big as your real monitor
allows, which can be more than the claimed screen has. Older versions open at
1280×1040.

## Check a profile

| Command | What it does |
|---|---|
| `kiwi-fox show shop` | Everything the profile reports, and where it goes out. |
| `kiwi-fox check` | Checks every profile, or one, for values that contradict each other, and compares its seeds with your other profiles. It ends with exit code 1 on an error. |
| `kiwi-fox selfcheck shop` | Starts the profile in a separate window for a moment, measures what a page can read, and lists everything that contradicts the Windows claim. `--json` prints the raw measurement. It needs a profile with an exit. |
| `kiwi-fox selfcheck shop --host` | Measures this machine with nothing spoofed, so that `host` mode knows the exact GPU group. It uses the profile only for its network. |
| `kiwi-fox compare shop work` | Measures two profiles and shows every signal side by side, with what differs and what is the same. |

[Detection notes](detection-notes.md) has what these measurements and outside
services such as fingerprint.com found.
