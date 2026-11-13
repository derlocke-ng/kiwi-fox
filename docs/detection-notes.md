# Detection notes

What an adversary can still see, measured rather than assumed. Record the machine
any figure came from: the test VM's virtual GPU and timing are not a real host's.

## First: is the browser drawing on a GPU?

If not, nothing below matters much. A browser drawing in software produces
llvmpipe's frames, which is what virtual machines and headless servers produce, and
sites read frames. `kiwi-fox doctor` measures it — with the helper Firefox itself
runs at startup, in a throwaway container, with no window — and prints either the
GPU it got or `SOFTWARE`.

A render node existing does not mean it is used. On a hybrid laptop whose panel
hangs off the NVIDIA card, the desktop tells every client to use that GPU; a
container with only Mesa and the integrated GPU's node cannot open it and falls
back to software *silently*. Measured there: integrated node alone, llvmpipe; both
nodes plus `DRI_PRIME`, the integrated GPU; the host's NVIDIA driver through CDI,
the NVIDIA GPU. A profile launched the first way was flagged as a virtual machine
by fingerprint.com with WebGL on *and* with WebGL off.

## Shared across every profile on one machine

These come from the real hardware and cannot be varied per profile. They are the
reason `crossBrowserId` matches between profiles, and that is accepted, documented
and surfaced in the UI.

| Signal | Why |
| --- | --- |
| WebGL rendered-pixel output (`readPixels`) | the real GPU and Mesa draw it; identical whichever GPU series is reported (measured) |
| Hardware performance / timing | the real CPU |
| AudioContext output | deterministic software DSP: identical for everyone, so it cannot tell your profiles apart |

`Math.sin`, `cos`, `tan` and `pow` used to be in this table as "identical for
every Firefox". They are not: Linux's C library and the Windows one round the
last bit differently for about 1% of inputs, so one call can show that a
"Windows" browser runs on Linux. Since 0.12, on Camoufox 158, a profile computes
them as the Windows C library does (see [Camoufox 158](#camoufox-158)).

## Varies per profile

Core count, AudioContext sample rate, the audio seed, speech voices, media device
counts, locale, timezone and `Accept-Language`.

**Screen and fonts do not vary unless you choose so** (since 0.1.3). A new profile
claims 1920x1080 at 100% and has the Windows 11 core font set with nothing added.
Both used to be drawn per profile, on the idea that profiles should differ in what
is measured. In use that lost to a simpler rule: rare values get flagged, common
ones do not. See "What came back clean" below.

**Graphics** vary only if you choose so. A profile is given a *card* — this
machine's own by default, or one from `kiwi-fox gpus` — and reports what Firefox
on Windows reports for that card: the text of the group it is in, with that
group's limits, extension list and shader precision. Firefox itself reduces every
card to one of a handful of groups (`dom/canvas/SanitizeRenderer.cpp`), so two
profiles on one machine report the same GPU by default, exactly as two real
machines with the same card would, and so do two profiles given an RTX 3060 and an
RTX 4090.

## Neither: canvas

Canvas readback (`toDataURL`, `getImageData`) differs on every launch, for every
profile. That is stock Firefox, not us: its default fingerprinting protection
perturbs canvas output with a per-session key, and every Firefox 152 user has it.
The engine's own `canvas:seed` does nothing at the pinned tag (measured). So canvas
cannot link two profiles, and cannot recognise one profile across two sessions
either.

## What differs between engine versions

Upstream moved its "latest" release from 152 to 156 on 2026-10-03, so new installs
get 156. The same fingerprint is sent differently to each; only keys the installed
engine's own schema lists are sent at all.

| | 152.0.4 | 156.0.1 |
| --- | --- | --- |
| Plain `RENDERER` | taken from the engine's config table | answered by the real context — so it is set through Firefox's own `webgl.override-unmasked-*` prefs instead, which works on both |
| Stencil mask defaults | spoofable (ANGLE's `0x7FFFFFFF`) | the host's (`255`, Mesa) — **a residual Linux tell on 156** |
| Live WebGL state | pinned by upstream's full table unless filtered | left alone by the engine itself |
| Camera without a microphone | crashes the tab | fixed |
| `battery:*`, `canvas:seed`, `fonts:spacing_seed`, `voices:fakeCompletion` | accepted (the seed keys did nothing) | no longer in the schema |
| GPU probe helper | `glxtest` + `vaapitest`, not shipped | one `gfxtest`, shipped with the engine |
| `navigator.languages`, `Accept-Language` | set key by key | one `locale:all` list; Firefox derives both from it, with its own q-values (0.9, 0.8, …) |

## Camoufox 158

Camoufox 158 (November 2026) knows how a Windows identity still gives away a
Linux host, and fixes it, but only through its own launcher. kiwi-fox has its
own launcher, so since 0.12 it sets the same things itself. Each was measured
upstream against stock Firefox 158 on Windows 11. The first two were checked
again on the test VM, and for the third, that its settings are in effect:

- `Math.sin`, `cos`, `tan` and `pow` give the Windows results: 12 of 12 cases
  where the VM's own C library differs.
- Media devices have Windows names after a page is allowed to use them
  ("Microphone Array (Intel® Smart Sound Technology …)"), and none before, as in
  Firefox. A sound card's microphone and speakers share one `groupId`. The names
  come from Camoufox's catalogue, drawn once per profile; the number of devices
  is the profile's own.
- Middle click does not paste, a double click selects a word with its trailing
  space, and scrollbars are drawn as Windows 11 draws them.
- Windows' keyboard shortcuts apply in text fields (Ctrl+Up goes to the start
  of the line, AltGr reports Alt).
- The browser does not try IPv6.

Not needed: Camoufox's codec spoofing. The browser already says it can play
H.264, HEVC, AV1 and AAC (all "probably", measured on the VM), so the host's
codecs do not show.

## What each graphics setting reports

| Setting | A page sees | Use |
| --- | --- | --- |
| My graphics card (`host`, default) | this machine's card as Firefox on Windows words it: the text of its group | the least there is to defend: the claim matches the hardware class that draws the frame |
| Another graphics card (`preset`) | the same, for a card you pick (`kiwi-fox gpus`) | profiles that should not share a GPU string; only a card from another group changes anything a page sees |
| Custom text (`custom`) | your vendor and renderer strings, with the limits of the group they belong to | a specific string you know you need; the validator says when it is one no real Firefox sends |
| No WebGL (`off`) | no WebGL context | rare on Windows — stands out |
| Unchanged (`raw`) | this machine's real strings, limits and extensions | measuring the host (`selfcheck --host`) and testing; on Linux it reads as Mesa under a Windows user agent |

`host` and `raw` are opposites, not neighbours: `host` is the real card *translated*
to what Windows Firefox would say about it, `raw` is the real card untranslated.

**Why an RTX 4060 shows as "GTX 980".** That is Firefox, not kiwi-fox. Its
sanitiser maps every NVIDIA card from the GTX 900 series onward to
`ANGLE (NVIDIA, NVIDIA GeForce GTX 980 Direct3D11 vs_5_0 ps_5_0), or similar`,
and a real RTX 4060 on real Windows reads exactly that. "RTX 4060" in that field
would be a string no stock Firefox sends.

**Show the exact model** (`--exact`) is the one place the model can appear:
`UNMASKED_RENDERER_WEBGL`, which stock Firefox sanitises too unless
`webgl.sanitize-unmasked-renderer` was turned off in about:config. With it on, a
profile reports e.g. `ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0
ps_5_0, D3D11-31.0.15.3623)` there and the group text in plain `RENDERER`, the
combination such a Firefox produces (measured on 156). It is a real configuration
and a rare one, so it is off by default.

Verified against <https://neoprint.dev/demo/> at the time fonts were still drawn
per profile: with font variation on the probed list, two profiles report unique
`id`, `stableId` and `weightedId`; `crossBrowserId` matches, as expected. With
the core set only (the default now), expect profiles that also share screen and
GPU group to share more of those ids — that is the trade for not being flagged,
and `kiwi-fox new --extra-fonts` or the editor brings the variation back.

## The window

Reported window sizes are real: the engine does not spoof `outerWidth`,
`innerWidth` and friends. So the real window has to be one the claimed screen
could hold.

Until 0.1.2 it was not, and the cause was in the engine. Its `browser-init.js`
runs `window.resizeTo(1280, 1040)` on every start, whatever the profile saved;
the size kiwi-fox seeded into `xulstore.json` never held, and a window the user
resized came back at 1280x1040 the next time. Counting GTK's shadow that window
reports `outerHeight` 1092, and a profile claiming 1920x1080 has 1032 usable:
**a window taller than its own screen** on every launch, until resized by hand.

From 156 the engine takes `window.outerWidth` / `window.outerHeight` and resizes
the real window to them at startup (without pinning the content, which is what
`window.inner*` does and why those are never sent). kiwi-fox sends the size the
window was left at, else what Firefox's own first-window rule gives on the claimed
screen (90% of the usable area, at most 1280x1040), and in both cases no more than
the claimed screen holds once the 52 px of shadow are counted. Measured, real
browser, 156.0.1:

| Claimed screen | Asked | Page reads outer / inner |
| --- | --- | --- |
| 1920x1080 (1032 usable) | 1280x928 (default) | 1332x980 / 1280x843 |
| 1920x1080 | 1424x733 (as left) | 1476x785 / 1424x648 |
| 1920x1080 | left at 1900x1040, fitted to 1868x980 | 1868x980 / 1816x843 |
| 2560x1440 | 1280x1040 | 1332x1092 / 1280x955 |
| 1536x864 at 125% | 1280x734 | 1332x786 / 1280x649 |
| 1366x768 | 1229x648 | 1281x700 / 1229x563 |

Two saved states make that startup resize leave a window about 500x200, both
reproduced: no saved size on a small claimed screen (Firefox's first-run rule
maximises, the engine un-maximises and then asks for the size the window nominally
already has), and a window the user left maximised. So before each launch the saved
state is rewritten to "this size, not maximised".

Not solved: a window the user maximises *during* a session is as large as the real
monitor's work area. On a 1920x1080 panel under GNOME that is 1048 tall against a
claimed 1032.

## What came back clean

Reported from use against fingerprint.com on a hybrid NVIDIA laptop, engine 156,
October 2026 — observations, not controlled experiments:

- Profiles with **no optional fonts** drew fewer "tampering" and "virtual machine"
  flags than profiles with a drawn set of extras. Checked afterwards: with extras a
  page can measure exactly the claimed families, no more (one exception, below), so
  the set was coherent — it was just unusual.
- **1920x1080** worked best, as in every earlier test: each other resolution on the
  list has been flagged at least once.
- A window **resized smaller** by hand worked better than the one the browser
  opened with. That is the too-tall window above.
- **No WebGL** raises a spoofing flag by itself.
- The **GTX 900+ group and the AMD APU group** came back clean. "My graphics card"
  was reported as flagged as a virtual machine — but on that machine it produces
  the *identical* container, config and prefs as the GTX 980 preset (diffed, 0.1.1
  and 0.1.2), so the setting cannot be the cause; the profiles compared also
  differed in fonts and window. Not yet re-tested with only that setting changed.

Found on the way: a profile given "Lato" cannot be seen to have it. The files are
in the image and fontconfig lists them, but no page measurement detects the family.
Open.

## fingerprint.com and amiunique.org, November 2026

Measured on 2026-11-13 on the test VM: Camoufox 158.0.1, kiwi-fox 0.12, one
profile per variant, all on one WireGuard exit (a data-centre address in Paris).
Each profile opened fingerprint.com's playground and amiunique.org. Read the
numbers with three limits in mind. The VM has a virtual GPU, not a real one. The
playground says itself that it runs a reduced set of signals and an older
model. amiunique compares against everything it collected since 2014, so a new
Firefox version or a Windows 11 value looks rarer there than it is today.

### What fingerprint.com saw

For every variant, fingerprint.com reported no bot, no tampering, no
anti-detect browser, no virtual machine, no privacy settings and no rare device.
Its own scores stayed low: tampering 0.02 to 0.07, virtual machine 0.03 to 0.36.
The highest virtual-machine score came from a profile that names an NVIDIA card
while the VM draws with its virtual GPU. The rare-device bucket was p95–p99 for
every variant, so none of the settings below moves it.

The only flags were about the exit: "public VPN IP" and "data centre proxy",
which make a suspect score of 11. They come from the IP address. No browser
setting changes them; a residential exit does.

### Profiles on one exit can be linked

fingerprint.com gives every browser a *visitor ID*. Profiles that shared the
exit got the **same** visitor ID whenever they had the same number of CPU cores:
four profiles with 6 cores had one ID, two with 12 cores another, the one with
16 cores its own. A different language, graphics group or machine type did not
separate them. Canvas did not link them (each profile drew a different canvas).

If two profiles must not be linked, give each its own exit.

### What amiunique.org saw

Every variant was unique among 5.7 million fingerprints, as most real browsers
are: canvas and the font list alone have no match. The share of browsers with
the same value shows which settings make a profile rarer than it needs to be:

| Attribute | Value | Same value |
| --- | --- | --- |
| Content language | `fr,fr-FR,en-US,en` (a French exit, language "Local") | 0.16% |
| Content language | `en-US,en` (language "English") | 21.88% |
| Permissions | geolocation granted (location "The exit's location") | 0.03% |
| Permissions | geolocation "prompt" (location "Ask") | 9.71% |
| WebGL renderer | the AMD APU group (the VM's own card) | 0.32% |
| WebGL renderer | the Intel HD Graphics group | 0.87% |
| WebGL renderer | the GTX 980 group (an RTX 3060, for example) | 1.55% |
| CPU cores | 6 / 12 / 16 | 2.09% / 6.74% / 9.58% |
| Available screen height | 1032 (1080 minus Windows 11's taskbar) | 3.81% |

### What follows

- **Good:** the defaults since 0.12 (1920x1080, Windows 11 core fonts, the
  Windows behaviour of Camoufox 158). Nothing in the browser itself was flagged.
- **Good:** location "Ask", the default. A page sees "prompt", like most
  browsers. If you allow it, the page gets "position unavailable": the browser
  has no location service to ask (measured), so it cannot reveal where this
  machine is.
- **Rare:** location "The exit's location". It hands every site the exit's
  position without asking. That matches the IP, but almost no browser grants
  every site its location.
- **Rare, not flagged:** a language that fits the exit's country but is rare
  worldwide. "English" is common everywhere; "Local" is what a person in that
  country would use. Neither was flagged.
- **Common:** the GTX 980 group is what 45% of Windows Firefox users report, but
  on a machine that draws with another GPU it raised the virtual-machine score.
  On real hardware, see "What came back clean" above.
- **Not good:** profiles that share an exit can be linked (see above).

## Language

Measured on 156.0.1 against what stock Firefox does (sources:
`intl/locale/rust/locale_service_glue`, `netwerk/protocol/http`): the things that
used to disagree with each other and no longer do.

| | Before | Now |
| --- | --- | --- |
| `Accept-Language` | written by us: `de-DE,de;q=0.9,en-US;q=0.7,en;q=0.5` — no Firefox 156 sends those q-values | derived by Firefox from the language list: `de,en-US;q=0.9,en;q=0.8` |
| `navigator.languages` | Chrome's shape (`de-DE, de, en-US, en`) | the list the region's Firefox build ships with (`de, en-US, en`; `nl, en-US, en`; `sv-SE, sv, en-US, en`; `en-GB, en`) |
| `Intl` default locale | `en-US` under a German language list | the region's (`de-DE`), as on a Windows set to that region |
| Browser's own strings | English: a form's "Please fill out this field." under `de` | the region's language pack from Mozilla: "Bitte füllen Sie dieses Feld aus." |
| Scrollbar width | 12 px, classic | 0 — Windows 11 uses overlay scrollbars |

`--language english` is the other coherent option: an English Firefox used in that
region — `en-US, en`, English strings, US formats, the region's timezone.

## Residual tells

- Text rasterisation: FreeType differs subtly from DirectWrite even with the right
  font files.
- TCP/IP stack fingerprint belongs to the proxy server, usually Linux.
- Engine version lag versus stock Firefox; DRM and codec availability.
- Behaviour, timing, and which accounts you sign into. Compartmentalisation is a
  discipline; this tool only removes the technical shortcut.
- Stencil mask defaults. On 152 they are pinned to ANGLE's value (so a page that
  sets one and reads it straight back gets the default). On 156 the engine answers
  them from the real context: `255` with Mesa, `4294967295` with the NVIDIA driver,
  where ANGLE on Windows gives `2147483647`.
- Window chrome. `outerWidth − innerWidth` and `outerHeight − innerHeight` are
  52 × 137 for an unmaximised window, because GTK counts its client-side shadow
  as part of the window; Windows gives about 16 × 90. A maximised window has no
  shadow (0 × 85). And `screenX`/`screenY` are always 0: Wayland does not tell a
  client where its window is.
- The frame itself. `readPixels` output is this machine's GPU and driver whatever
  card the profile names.
- `WEBGL_provoking_vertex` is listed because Windows has it; on a host whose Mesa
  lacks it, using it does nothing.
- Voice names for de-AT, de-CH, sv-SE, fi-FI, nb-NO, da-DK and nl-BE are from memory,
  not from a capture of a real machine.

## Open

- fingerprint.com with the current defaults has been run on the test VM only
  (see [fingerprint.com and amiunique.org](#fingerprintcom-and-amiuniqueorg-november-2026)),
  not on real hardware.
- Whether "My graphics card" is really treated differently from the identical
  GTX 980 preset: flip that one setting on a profile that is otherwise clean.
- Stencil mask defaults on 156, and the window-chrome deltas, are the known
  remaining differences from a real Windows Firefox.
- The new-tab button sits in the nav-bar because of the engine's built-in default
  placement, below the data layer the tweaks can reach.
