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
| `Math.*` precision | identical for every Firefox on earth — carries no information about this machine |
| AudioContext output | deterministic software DSP — likewise harmless |

The last two are worth stating because they invert the usual intuition: a value
identical for everyone cannot distinguish your identities from each other or from
anyone else.

## Varies per profile

Screen and avail geometry, DPR, core count, AudioContext sample rate, the audio and
font-spacing seeds, the font set including families that appear on real probe
lists, speech voices, media device counts, locale, timezone and `Accept-Language`.

**Graphics** vary only if you choose so. Every profile reports one GPU *series* —
Firefox never names a card — in both renderer values, with that series' limits,
extension list and shader precision. By default that is this machine's own series,
so two default profiles on one machine report the same GPU, exactly as two real
machines with the same card would. A different series per profile is a setting
(`kiwi-fox webgl`, or Graphics in the GUI).

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

## What each graphics mode reports

| Mode | A page sees | Use |
| --- | --- | --- |
| `host` (default) | the series this machine's GPU belongs to, in Windows wording | the least there is to defend: the claim matches the hardware class that draws the frame |
| `preset` | a series you pick from six (`kiwi-fox gpus`) | profiles that should not share a GPU string |
| `custom` | your vendor and renderer strings, with the limits of the series they belong to | a specific string you know you need; anything but a series string is one no real Firefox sends, and the validator says so |
| `off` | no WebGL context | rare on Windows — stands out |
| `raw` | this machine's real strings, limits and extensions | measuring the host (`selfcheck --host`) and testing; on Linux it reads as Mesa under a Windows user agent |

Verified against <https://neoprint.dev/demo/>: with font variation on the probed
list, two profiles report unique `id`, `stableId` and `weightedId`.
`crossBrowserId` matches, as expected.

## Residual tells

- Text rasterisation: FreeType differs subtly from DirectWrite even with the right
  font files.
- TCP/IP stack fingerprint belongs to the proxy server, usually Linux.
- Engine version lag versus stock Firefox; DRM and codec availability.
- Behaviour, timing, and which accounts you sign into. Compartmentalisation is a
  discipline; this tool only removes the technical shortcut.
- A page that sets a stencil mask and reads it straight back gets the default: the
  four stencil masks are pinned, because their value in a fresh context differs
  between ANGLE and Mesa and fingerprinting scripts dump them from a fresh context.
- `WEBGL_provoking_vertex` is listed because Windows has it; on a host whose Mesa
  lacks it, using it does nothing.
- Voice names for de-AT, de-CH, sv-SE, fi-FI, nb-NO, da-DK and nl-BE are from memory,
  not from a capture of a real machine.

## Open

- Whether the virtual-machine and tampering flags on fingerprint.com are gone now
  that the WebGL limits, extensions and masked renderer no longer say "Mesa". Not
  yet re-run.
- The new-tab button sits in the nav-bar because of the engine's built-in default
  placement, below the data layer the tweaks can reach.
