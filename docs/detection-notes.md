# Detection notes

What an adversary can still see, measured rather than assumed. Record the machine
any figure came from: the test VM's virtual GPU and timing are not a real host's.

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
