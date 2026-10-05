# CLAUDE.md — Kiwi-Fox

## What this is

A Linux desktop app (GTK4) that launches isolated browser profiles in rootless Podman containers. Each profile is one persistent identity: its own storage, its own proxy exit, its own blocking DNS resolver, and its own frozen fingerprint that presents as Windows 11.

The browser is Camoufox (patched Firefox), pinned to an exact upstream release and launched **headfully and directly** — no Playwright, no juggler, no automation channel. Camoufox already ships a complete Firefox UI.

Each running profile gets a **gateway container that owns a network namespace** whose only exit is that profile's proxy; the browser joins that namespace and has no routing table of its own. More apps for the same identity can join the same namespace later.

Proxies come from **standalone provider modules** (Mysterium, 9proxy, Tor, plain SOCKS5). Each runs on its own, independently of kiwi-fox, and is installed as its own kiwi-updater app.

Audience: people who manage several accounts they own or are authorised to run (e.g. agency social media managers) and do not want those accounts cross-linked by browser fingerprint or IP.

## Scope

- Interactive, hands-on browsing only. No automation, bots, scripted engagement, bulk account creation or CAPTCHA solving. If a task drifts there, flag it instead of implementing it.
- Target OS for spoofing: **Windows 11 only.** Newer Windows releases later. macOS and Linux targets are out of scope — do not add them back without being asked.
- No proprietary fonts or binaries committed to the repo or baked into published images.
- We do not promise "undetectable". The goal is a coherent, stable, plausible identity per profile. Known residual tells are documented, not hidden.

### Benchmark

<https://neoprint.dev/demo/> ([source](https://github.com/neoprintjs/neoprint)) is the reference adversary. It is open source — read it instead of guessing. 22 collectors, four IDs:

| ID | Built from | Our goal |
| --- | --- | --- |
| `id` | all collectors | must differ per profile |
| `stableId` | math, webgl, fonts, intl | must differ per profile — **verified differing** once the font variation moved onto the probed list |
| `weightedId` | entropy-weighted | must differ per profile |
| `crossBrowserId` | hardware-only signals, normalised across engines | **differs in practice.** Its inputs are not purely hardware — DPR, fonts, locale/timezone and audio sample rate all feed it, and we vary all four. An earlier draft asserted it *must* match; measurement settled it. |

It also runs a spoof-heuristics layer, an anti-detect-browser layer (Multilogin, GoLogin, Dolphin Anty, …), a 30+ heuristic bot layer, and **noise detection** — it explicitly looks for randomised values, "try with Brave to see noise detection in action". Those layers must report nothing. Their checks are folded into the validator rules below.

**Corollary: never add noise.** Per-profile canvas/WebGL randomisation makes us *more* identifiable against this adversary, not less. Differentiate profiles with values that are stable and real, never jittered. *(Refined 2026-10-05: stock Firefox itself randomises canvas readback per session by default, so a noisy canvas is the norm for Firefox, not a tell. What survives of the rule: add none of our own.)*

## Mental model (read before touching fingerprint or network code)

A website never sees the container or the distro. It sees five layers:

1. **Network** — exit IP and its reputation/ASN, DNS, WebRTC candidates, TLS/HTTP2 fingerprint (from the browser build), TCP/IP stack fingerprint (from whichever host terminates TCP; behind a proxy that is the proxy server, not us).
2. **HTTP** — User-Agent, Accept-Language.
3. **Spoofable JS surface** — navigator, screen, fonts, declared WebGL vendor/renderer and parameters, speech voices, media devices, timezone/Intl, CSS media queries, scrollbar metrics. Camoufox handles these in C++.
4. **Surface the engine cannot spoof** — what the graphics stack actually produces and how fast: canvas/DOMRect/SVG text metrics, WebGL rendered pixels, shader precision, WebGPU limits, hardware perf timings, the real monitor.
5. **State and behaviour** — cookies, storage, login history, usage patterns, behavioural biometrics (typing rhythm, mouse curvature, scroll). We only control isolation here; a real human driving the browser is an advantage over automation, not a liability.

Consequences that drive the design:

- **Spoofing lives inside the browser engine (C++), never in injected JS or extensions.** JS shims are detectable through `toString`, prototype chains, workers and iframes — and neoprint checks exactly that.
- **Coherent and stable beats random.** Every value must agree with every other value and stay identical across launches of the same profile. A fingerprint that changes per launch looks like a new device at every login.
- **Profiles differ where real Windows machines differ** — above all in installed fonts — not in implausible ways.
- **Never enable `privacy.resistFingerprinting`.** It is recognisable as such and does not present as the target OS. Do not enable `privacy.fingerprintingProtection` either: Camoufox already spoofs these surfaces in C++, and FPP brings its own tells (see "Prior art").
- **Never set rare prefs** like `webgl.disabled`, `dom.webaudio.enabled=false`, `media.navigator.enabled=false`, `browser.display.use_document_fonts=0`. Each is detectable *by its absence* and shrinks us to a memorable population. This is the documented failure of the old pfox design.
- **One base image.** Not because distro variation is unobservable — it measurably is observable (see "Prior art") — but because Camoufox owns the font set, UA, locale and codec surface, and varying the distro underneath would break coherence with the Windows 11 target and detach the UA from the pinned engine version.
- **Layer 4 is the ceiling.** Do not design around pretending otherwise.

### What actually links profiles, measured

The classification that matters is not "shared vs unique" but **"does this signal identify *this host*, and does it repeat across *our* profiles"**. A value identical for every Firefox user on earth cannot link anything. Measured on this host (Bluefin / Fedora Silverblue 44, podman 5.8.4, rootless, Wayland) — see `novafox/ANALYSIS.md`:

| Signal | Status | Why |
| --- | --- | --- |
| `Math.*` precision | **harmless** | Byte-identical across glibc 2.42, glibc 2.41 and musl. SpiderMonkey ships its own fdlibm, so the host libc never reaches `Math.*`. Carries no information about this machine. |
| AudioContext output | **harmless** | Byte-identical everywhere (`audio.sum 35.749972093850374`). Gecko's DSP is pure software and deterministic. |
| Canvas / DOMRect / SVG text metrics | **dangerous, and movable — but only via fonts a fingerprinter probes** | Driven by the font set and rasteriser. Varying the font set moves it, but see "Vary what is measured": varying families nobody probes for changes nothing observable. |
| WebGL rendered-pixel hash | **dangerous, not movable** | `e9c3ab41…` with llvmpipe *and* with a real Radeon passed through — passing `/dev/dri` changed nothing, and Firefox sanitises the renderer string anyway. softpipe makes WebGL unavailable, which is worse. So do not pass `/dev/dri` (attack surface, zero benefit) and do not expect to vary this. |
| Hardware perf / timing | **dangerous, not movable** | The real CPU. `privacy.reduceTimerPrecision` blunts it; `cpuset` is not delegated to rootless users on this host. |
| Screen / colorDepth / DPR | **dangerous, spoofable — verified working** | Measured 2026-10-03 on the test VM, headful on a live Wayland compositor: with no config the real monitor leaked (`screen` and CSS `device-width` both 2499x1333); with `screen.*` set, both reported 1536x864 and `availHeight` 816. CSS media queries follow the spoof, not the compositor. The real monitor leaks **only when a key is absent**. |
| Codec set, Intl/ICU locale list, Firefox build | **shared by design** | One base image, one pinned engine. Consistent with the Windows 11 claim; not varied. |

So: the realistic goal is that `id`, `stableId` and `weightedId` differ per profile, driven mainly by fonts, screen, WebGL strings and locale — while the WebGL render hash and perf timings stay shared and partly link profiles through `crossBrowserId`. **Say this plainly in the UI and in `docs/detection-notes.md`.** Do not attempt to fix it with noise, and do not attempt to fix it by varying the software rasteriser: that was measured not to move the render hash.

## Engine strategy

Camoufox is the only engine in scope. All engines sit behind one interface (`core/engines/base.py`): `build_spec(profile) -> ContainerSpec`.

Findings from reading upstream (2026-10-03). Written down so they are not re-litigated:

- **It has a real UI.** No UI-removal patch exists in [`patches/`](https://github.com/daijro/camoufox/tree/main/patches). [`settings/chrome.css`](https://github.com/daijro/camoufox/blob/main/settings/chrome.css) documents that the old minimalistic theme (25px tab strip, 30px nav bar) was deliberately **reverted** to stock Firefox chrome dimensions, because `outerHeight - innerHeight` is itself a fingerprint signal. `settings/camoufox.cfg` sets `userChrome.tab.*` and theme prefs. Tab strip, nav bar, extensions, stock geometry — nothing to "give back".
- **Playwright is only the automation channel.** Config reaches the browser through chunked env vars `CAMOU_CONFIG_1..N` (JSON) and `CAMOU_PREFS_1..N`, read at startup by the C++ patches via the autoconfig mechanism, before the profile initialises. We set those ourselves and exec the binary — no juggler port, no automation surface for neoprint's bot layer to find.
- GitHub's marked-latest release is **v152.0.4-beta.30 (Firefox 152.0.4)**; the Firefox 156.0.1 builds exist but are flagged pre-release. Pin deliberately, and know which you pinned — the `/releases/latest` API returns 152, not 156. Upstream is actively doing "stock-Firefox parity for native identities: input, fonts, locale, WebGL, WebRTC, media, timing, launcher".
- Packaging notes from unpacking v152.0.4-beta.30: the Linux x86_64 zip is **663 MB** and bundles its own `fonts/` and `fontconfig/` trees. `glxtest` and `vaapitest` are **absent from the zip**, which produces a non-fatal `GFX1-` "failed to spawn child process" warning on every start; a stub is unnecessary but harmless. `-profile` needs a path that is **absolute and already exists**, or Firefox shows "profile cannot be loaded, missing or inaccessible" and never starts.
- Spoofing patches of interest: `navigator-`, `screen-`, `webgl-`, `webrtc-ip-`, `timezone-`, `locale-`, `font-list-`, `anti-font-fingerprinting`, `audio-context-`, `speech-voices-`, `media-device-`, `media-codec-`, `touchscreen-`, `geolocation-spoofing`, plus `fingerprint-injection` and `config`.
- **No WebGPU patch exists**, and `camoufox.cfg` does not set `dom.webgpu.*`. See the WebGPU decision below.
- `camoufox.cfg` already sets `network.proxy.socks_remote_dns=true`, WebRTC obfuscation/proxy-only prefs, no updates, no telemetry. We override what our DNS design needs; read the pinned version's cfg rather than assuming.
- Upstream states it "may not be suitable for stable production use". Pin an exact release and never float.
- The authoritative list of config keys is `settings/properties.json` at the pinned tag. Read it; do not write keys from memory.

Deferred, explicitly not scoped:

| Option | Why deferred |
| --- | --- |
| Our own Firefox build with Camoufox's patches, minus playwright/juggler | Most control and smallest surface, but it means owning a multi-hour build, CI, and a rebase every Firefox release. Revisit only if upstream stalls or a patch we need never lands. |
| fingerprint-chromium (second engine) | More work, and it *increases* cross-linking exposure — two engines on one host is exactly what `crossBrowserId` is built to catch. |
| Stock Firefox + prefs/extensions | Rejected. Cannot change the rendering surface coherently. |

Rules:

- **`CAMOU_CONFIG` keys do not cross-populate. Coherence is entirely ours to build.** Measured: setting `navigator.platform` to `Win32` left the User-Agent reporting `Mozilla/5.0 (X11; Linux x86_64; rv:152.0)`. The Python launcher's `os` option is what normally expands into a coherent bundle (UA, `oscpu`, platform, fonts, voices, …) — and we are replacing that launcher, so nothing expands anything for us. Every key we rely on must be written explicitly and checked against every other key. This is the validator's entire reason for existing.
- Do not write engine flags or config keys from memory. Read the upstream source/docs for the pinned version and link them in a comment where the key is used.
- The UA version must equal the real engine version. Never claim Chrome on Gecko or vice versa.
- Set `network.proxy.failover_direct=false`. It defaults to **true**, which permits Firefox to fall back to a direct connection when the proxy misbehaves.
- Firefox ignores `--window-size` on Wayland. Seed window geometry into the profile's `xulstore.json` instead — and with screen spoofing in play, the window size effectively *is* the reported screen.
- Prior art worth reading: Camoufox's Python launcher (for the env-var chunking and fontconfig generation), fpgen/BrowserForge (fingerprint distributions), `novafox/ANALYSIS.md` (measurements on this exact host), Donut Browser (profile management).

### Headful on Wayland

It behaves like an ordinary Firefox window, and this is measured rather than hoped: novafox already runs containerised Firefox over Wayland socket passthrough on this host with "ordinary host windows — normal alt-tab, normal dock icon, normal screenshots". Camoufox keeps stock Firefox chrome at stock dimensions, so the same holds. Caveats, all of them known:

- **Firefox ignores `--window-size` on Wayland.** Seed geometry into the profile's `xulstore.json`. With screen spoofing active the window size effectively *is* the reported screen, so this is a fingerprint input, not a cosmetic preference.
- **Screen spoofing over Wayland is verified** (test VM, 2026-10-03, headful on a live compositor). `screen-spoofing.patch` installs a priority chain — per-context override, then `MaskConfig` `screen.*`, then the real display as final fallback — and it patches `nsScreen::GetRect`/`GetAvailRect`/`PixelDepth`, `nsDeviceContext::GetDeviceSurfaceDimensions` and `nsMediaFeatures::GetDeviceSize`, so CSS media queries are covered as well as the JS `screen` object. Measured: no config → real monitor (2499x1333 in both `screen` and CSS `device-width`); `screen.*` set → 1536x864 in both. **The real monitor leaks only where a key is missing**, so the generator must emit a complete screen block, and the validator must reject a partial one.
- **The window is not sized to the spoof for free.** Measured `outerHeight` 1092 against a spoofed `availHeight` of 816, with ~107px of chrome (outer 1332x1092, inner 1280x984). Size the real window to the profile's spoofed `avail*` and keep `window.*` config keys consistent with it.
- Wayland restricts what a client can observe far better than X11; the X11 fallback is a weaker boundary and should stay a fallback.
- Camoufox's own prefs are tuned for automation, not for daily comfort: session restore and bfcache off, newtab disabled, `about:blank` homepage, bookmarks toolbar hidden. Re-enable what you want through `CAMOU_PREFS_*` — but only prefs that change *comfort*, never one that moves an observable surface. Anything in the second category goes through the validator first.

### Engine tweaks: reverting Camoufox's JS and CSS patches

Camoufox's patches split in two, and the distinction is what makes this safe:

- **C++ patches compiled into `libxul.so`** — navigator, screen, WebGL, fonts, timezone, locale, audio, WebRTC. This is the entire value of the engine and the reason we chose it. Untouchable without a rebuild, and we want every one of them.
- **JS, CSS and prefs patches living in `omni.ja` (a zip), `chrome.css` and `camoufox.cfg`** — debloat and UI changes tuned for *watching* an automated browser rather than using one. These are data on disk, so they can be reverted selectively on the host at fetch time, with a `.orig` backup for each, and no compiler involved.

`kiwi-fox engine tweaks` lists them with their state; `engine tweak <name>|--all` applies; `engine restore` puts every original back. Each tweak carries its own fingerprint assessment in code, and **no tweak may touch a spoofing surface** — verified by re-probing a live profile after applying all of them (UA, platform, screen, DPR, cores, timezone, locale, audio rate, font set and both WebGL contexts all unchanged).

**The enterprise policy outranks everything.** `distribution/policies.json` is an
enterprise policy file, so it beats any pref a profile can set, and it was the
real cause of two separate symptoms that looked unrelated:

```json
"SearchEngines": { "PreventInstalls": true,
                   "Remove": ["Google","DuckDuckGo","Bing", …],
                   "Default": "None",
                   "Add": [{"Name":"None","URLTemplate":"http://127.0.0.1"}] },
"HardwareAcceleration": false
```

It removes DuckDuckGo *by name* and installs a dummy "None" engine as the
default — which is why repairing `omni.ja` restored the engine list but the
address bar still would not search — and it disables hardware acceleration
outright. Hours were spent on `glxtest` before finding this: the GPU was never
going to engage while a policy said no. Check policy files before chasing
behaviour that looks like a missing capability.

Current set:

| tweak | what it undoes | fingerprint cost |
| --- | --- | --- |
| `search` | the v1-shaped config stub that stops the search service starting at all | none — the search service is chrome, and the engine list a site sees is unchanged |
| `chrome` | the bundled minimalisticfox `chrome.css` | none, arguably better: `outerHeight - innerHeight` returns to stock proportions, and `window.*` is spoofed from config regardless |
| `window-rounding` | forced resistFingerprinting window-size rounding in `browser-init.js` | none — we set screen and window from config, so rounding adds nothing and fights the maximised geometry in `xulstore.json` |
| `policies` | the enterprise policy removing DuckDuckGo, pinning a dummy "None" default engine, and forcing `HardwareAcceleration: false` | none, and it removes a tell — software-rendering performance contradicts a claimed discrete GPU |
| `urlbar-tips` | disabled urlbar intervention tips | none, cosmetic chrome behaviour |

**Choosing the default engine.** Firefox 152 takes it from the packaged search
config's `defaultEngines.globalDefault`, not from `browser.search.defaultenginename`,
which is no longer read. `kiwi-fox engine default-search [id]` edits that record
(and clears `specificDefaults`, which would otherwise let the locale override the
choice); `--list` shows the 150-odd available identifiers. Not a fingerprint
surface — the default engine is only observable once the user searches.

**GPU probe helpers.** Camoufox's zip omits `glxtest`/`vaapitest`, and the distro
is the wrong place to get them: Fedora 43 ships Firefox 156, which merged them
into a single `gfxtest`, while Camoufox 152 *and* 156 both still spawn the old
names. `kiwi-fox engine helpers` takes them from **Mozilla's own release tarball**
for the engine's base version, which is version-matched by definition. Verified:
with the policy relaxed and the helpers in place, `/dev/dri/renderD128` is held
open and `libdrm_amdgpu`, `libEGL_mesa` and `libgallium` are mapped.

**Hardware rendering has a fingerprint cost, and it is a genuine trade.** With
software rendering, plain `getParameter(RENDERER)` reports `llvmpipe, or similar`
— unmistakably Linux software rendering. With hardware, it reports Firefox's
sanitised bucket for the *real* GPU (`Radeon R9 200 Series, or similar` on this
host), which looks like an ordinary GPU but names the host's actual family, so it
is shared across every profile and contradicts the spoofed unmasked string. Both
states are incoherent; hardware is the better of the two because it removes the
performance tell and looks like a real machine. The real fix is spoofing the
masked `VENDOR`/`RENDERER` through `webGl:parameters`, whose key format is still
undocumented — three plausible encodings were tried without a conclusive result,
so it stays open rather than guessed at. *(Superseded 2026-10-05 — see "WebGL, devices and voices, re-read from source".)*

Two traps worth remembering. **Match with regexes, not string literals:** the injected `if (true ||` sits on its own line in some files and inline in others, and a literal match silently reports "already stock" when only whitespace differs. And **detect state with a positive marker**: the first version of the `chrome` tweak decided whether it had run by searching for the upstream theme's name, which its own replacement comment contained, so a fixed file reported as unfixed.

A repaired engine only helps profiles whose search state is built afterwards. An existing profile that already failed to initialise search keeps the broken state and is best recreated.

### WebGPU decision

Real Windows Firefox has WebGPU enabled by default since **Firefox 141**, and our base is 156 — so the browser we claim to be has it. Firefox on **Linux** does not enable it by default, so in our container `navigator.gpu` is already absent without us doing anything.

**Decision: keep it off, and pin `dom.webgpu.enabled=false`** so a future release cannot silently turn it on. Confirmed empirically on the test VM: `typeof navigator.gpu` was `undefined` in both the baseline and the spoofed run, so there is nothing to switch off today — the pin exists to stop a future Firefox from changing that under us.

- Cost: "Windows 11 Firefox 156 without WebGPU" is a narrower bucket than with. It is a *real, non-empty* population though — blocklisted drivers, enterprise policy, VMs/RDP, old GPUs — unlike `webgl.disabled`. neoprint uses WebGPU limits only when available, so absence lowers entropy rather than tripping anything.
- The alternative is worse: a live WebGPU reports the container's real Mesa/llvmpipe adapter while WebGL claims ANGLE/Direct3D, which is precisely neoprint's "GPU vendor mismatch (WebGL vs WebGPU)" heuristic — the single most likely way we get flagged as spoofed.
- **Decided: ship without WebGPU, and write a patch ourselves only if a real site forces it.** Patching is the same class as `webgl-spoofing.patch` and is feasible — adapter info and limits are reported values — but it needs coherent limits for the claimed GPU family while compute output stays llvmpipe, and it means owning a Firefox build. If we get there, prefer landing it upstream: WebGPU parity sits squarely inside Camoufox's current parity work, and then we inherit it maintained instead of carrying a fork.

## Target OS notes — Windows 11

- Firefox reports `Windows NT 10.0; Win64; x64` on both Windows 10 and 11. That is correct. Never invent `Windows NT 11.0`.
- On Gecko there is no client-hints surface, so Windows 11 vs 10 is not separately observable from the UA. Do not try to encode it there.
- **Fonts are the per-profile identity lever, but only the probed ones count.** Real Windows machines genuinely differ above the mandatory core, and the font set moves canvas, DOMRect and SVG metrics. The catch, learned the hard way: a fingerprinter probes a fixed list, so variation has to land on *that* list. The CJK and complex-script block varies plausibly and is measured by nobody. Three layers, therefore: the mandatory Windows core in every profile; a seeded CJK/supplemental subset for plausibility; and a seeded subset of open-licensed families that appear on real probe lists and genuinely vary on Windows (Open Sans, Lato, Source Sans 3) for actual differentiation. Never expose Liberation, DejaVu, Noto or Roboto — those are catalogued as Linux fonts.
- Fonts (Segoe UI, Segoe UI Variable, Segoe UI Emoji, Calibri, Cambria, Consolas, …) are proprietary. Check first what the pinned engine already ships and handles through its fontconfig generation. Anything extra is imported by the user from a Windows install they hold a licence for: `kiwi-fox fonts import <path-to-Windows/Fonts>`. Font *count* is itself a neoprint signal — the set must be complete and plausible, not a handful of files.
- WebGL reports one GPU *series*, worded the way Firefox words it — `ANGLE (AMD, Radeon R9 200 Series Direct3D11 vs_5_0 ps_5_0), or similar` — in the masked and the unmasked value alike, with that series' limits, extensions and shader precision. Firefox never names a card, so neither do we. See `core/fingerprint/webgl.py`.
- Screen `avail*` must account for the taskbar. Scrollbar style, speech voices and system colours must match Windows. DPR is 1.0, 1.25 or 1.5 — not 2.
- Keep the per-OS template layer so a newer Windows is data, not code.

### Residual tells we cannot remove (surface in UI help, keep `docs/detection-notes.md` current)

- WebGL rendered-pixel hash and hardware perf timings: shared by all profiles on this host, and produced by Mesa rather than by the claimed machine's Direct3D.
- Text rasterisation: FreeType differs subtly from DirectWrite even with the right font files.
- TCP/IP stack fingerprint belongs to the proxy server, usually Linux.
- Software rendering performance versus the claimed GPU.
- Engine version lag versus stock Firefox; DRM/codec availability.
- Behaviour, timing, and which accounts you sign into. Compartmentalisation is a discipline; this tool only removes the technical shortcut.

## Verified on hardware

Measured, not assumed. Dev machine = Bluefin-dx, podman 5.8.7, rootless, Wayland, SELinux **enforcing**. Dates are when the measurement was taken; re-measure after an engine or podman bump.

**Container topology (2026-10-03, dev machine)**

- A `--userns=keep-id` container **can** join a non-keep-id container's netns with `--network container:`. This was the single biggest unknown in the design; it holds.
- The kill switch enforces. With the gateway's nftables loaded, a joined `--cap-drop=all --userns=keep-id` container reached the one permitted destination and nothing else. Confirmed again on a live profile: direct TCP to 1.1.1.1:443, 8.8.8.8:53 and 9.9.9.9:443 all blocked, UDP DNS timed out, the proxy endpoint reachable, drop counter climbing.
- The browser container holds **zero** effective capabilities and reports `NetworkMode=container:<gateway>` — no namespace of its own. Both asserted in `tests/leak`.

**DNS (2026-10-03, through Tor at `10.8.0.1:9050`)**

- dnscrypt-proxy loaded all 244,237 oisd entries and reached Google over **DoH through the SOCKS5**: `[google] OK (DoH) - rtt: 490ms`. The whole TCP-only-DoH-through-a-UDP-less-proxy design works as specified.
- `big.oisd.nl/domainswild2` blocks correctly: listed names return `REFUSED`, and **subdomains of a listed name are refused too**, which is the bare-name rule that makes this the right format. Legitimate names resolve normally.
- Trap when testing: oisd deliberately omits some apexes ("Block. Don't break."), so `doubleclick.net` resolves while `accounts.doubleclick.net` is blocked. Test with a name that is actually in the file.

**Engine (2026-10-03)**

- Camoufox's default UA reads `... Gecko/20100101 Camoufox/152.0.4-beta.30`. **Overriding `navigator.userAgent` and `headers.User-Agent` is mandatory**, not cosmetic.
- **Pass the render node and use hardware GL.** `/dev/dri/renderD128` is mode 666, so it needs no group juggling, and `card1` is display/KMS which belongs to the compositor. An earlier draft of this file refused to pass `/dev/dri` on the strength of a novafox measurement — but that measurement says the renderer string stayed `llvmpipe` *and Firefox kept software rendering anyway*, i.e. it shows "`/dev/dri` alone did not enable acceleration", not "acceleration does not help". Software-rendering performance against a claimed discrete GPU is one of our own listed residual tells, so real acceleration **removes** a tell. Without a render node the separate GPU process crash-loops, so `gpu_accel=False` falls back to in-process software WebRender.
- Camoufox draws a **virtual cursor highlight by default** — an orange halo tracking the pointer, meant for visualising automated mouse movement. Set `showcursor` and `humanize` to false.
- The release zip is ~632 MiB, bundles 144 Windows font files and a Tor-Browser-derived `fontconfig/windows/fonts.conf`, and **omits `glxtest`/`vaapitest`** (non-fatal `GFX1-` warning). Mounted read-only from the host, never baked into an image.
- `-profile` needs a path that is absolute **and already exists**.

**Host integration (2026-10-03)**

- SELinux enforcing denies the container every host mount under `$HOME`: all bind mounts need `,z`. The engine directory takes `,z` (shared across containers) and never `,Z`.
- The **Wayland socket cannot be relabelled** — `,z` would change the label of the compositor's own socket. The browser container therefore runs with `label=disable`. Documented trade: the real boundary is the netns with no route, zero capabilities and `no-new-privileges`.
- Credentials go in as a **podman secret**: not container env (`podman inspect` shows env), and not a bind-mounted 0600 file (the gateway runs as container-root, a subuid, and cannot read a file owned by the host user).
- The gateway needs `NET_ADMIN` for the ruleset **and `NET_BIND_SERVICE`** — after `--cap-drop all`, even container-root cannot bind port 53.
- Mullvad's SOCKS5 exits report an **IPv6** address, so the exit IP's family has to decide between `webrtc:ipv4` and `webrtc:ipv6`.

**Why tabs crashed, and the two fixes (2026-10-03)**

Two unrelated bugs, each of which alone made the browser unusable. Both cost real time to find because each masked the other.

1. **GTK aborts the whole browser when an icon fails to load.** Fedora routes every gdk-pixbuf image load — PNG included, not just SVG — through **glycin**, which sandboxes each loader with `bwrap --unshare-all`. bwrap cannot run in a rootless container: it mounts a fresh devpts for `--dev` and the kernel denies that in our user namespace, with or without `SYS_ADMIN`. GTK then fails to load even its own `image-missing` fallback and `ensure_surface_for_gicon` asserts, calling `abort()` the moment a tab wants an icon. Switching to a raster icon theme does **not** help, because PNG goes through glycin too. The fix is `gdk-pixbuf2-modules-extra` plus a `bwrap` shim in the image that skips bwrap's own options and execs the loader directly; inherited fds (`--dbus-fd`) survive the exec, which is what the loader actually needs.
2. **Firefox's content sandbox needs `CAP_SYS_CHROOT`.** It chroots each content process, and without the capability the Chroot Helper segfaults in `libmozsandbox.so`, taking Web Content and the RDD process with it. The kernel log names it exactly: `Web Content[...]: segfault ... in libmozsandbox.so`. **Grant `SYS_CHROOT`** — it is granted *to strengthen* isolation, not weaken it. Measured: with it, 3-4 content processes and an RDD process, zero segfaults; without it, 8 crashes and one surviving tab. `MOZ_DISABLE_CONTENT_SANDBOX=1` also produces working tabs but throws away the browser's main defence against a hostile page, which is a far worse trade than one narrow capability.

3. **Then everything timed out, which looked like DNS and was not.** The forwarder decoded SOCKS5 domain targets with Python's `idna` codec, which raises `UnicodeError` when handed an `errors` argument. Every CONNECT addressed by *name* therefore killed the handler and closed the connection, while IP-addressed ones kept working — and the only thing addressing by IP was dnscrypt-proxy reaching its resolver from a stamp. So DNS resolved perfectly while no page would load. Domain names in SOCKS5 are already punycoded ASCII: forward the target as raw bytes, in the same address form the client used, and decode only for logging. Covered by `tests/unit/test_forwarder.py`, which exercises IPv4, IPv6 and domain targets against a fake upstream.

4. **And then nothing loaded at all, because `CAMOU_PREFS` does not exist.** An early draft set prefs through chunked `CAMOU_PREFS_1..N` env vars, taken from a summary of the Python launcher and never checked. `strings` on the engine's `libxul.so` contains `CAMOU_CONFIG_` and `CAMOU_CONFIG` and **no prefs variable at all**, so not one pref was ever applied: Firefox ran with no proxy configured, attempted direct connections, and the gateway firewall correctly dropped them. Every page timed out while DNS resolved perfectly, because resolution is container-level and never needed the proxy. **Prefs go into the profile's `user.js`**, which Firefox re-reads on every startup and which overrides `prefs.js`. Verify a config mechanism against the binary, not against prose about the binary.

Diagnostic note: `coredumpctl` and `journalctl -k` on the host capture container crashes and name the faulting module. That is how both were found; container logs alone pointed at graphics, which was a red herring.

**WebGL, rendering and the UI (2026-10-03, probed in a live profile)**

- **WebGL was entirely unavailable and that is a serious tell, not a cosmetic one.** The release zip omits `glxtest`, so Firefox cannot probe the GPU, concludes nothing is usable and disables WebGL — and a browser with no WebGL is *louder* than software rendering, one of the documented reasons pfox failed. `webgl.force-enabled=true` restores it. Do **not** also set `webgl.disabled`: it is already false by default and the validator rejects the key outright, which it correctly did when this was first attempted.
- **Still software, not hardware.** Nothing holds `/dev/dri/renderD128` open and no hardware driver is mapped, because the same missing `glxtest` means Firefox never attempts a hardware path. Passing the device and forcing WebRender prefs is not sufficient. The remaining option is to supply a real `glxtest` — Fedora's `firefox` package ships one at `/usr/lib64/firefox/glxtest`, copyable in a multi-stage build — with the caveat that it is built for a different Firefox version.
- **Spoofed values verified landing:** UA as stock Firefox on Windows, `platform` Win32, screen 1536x864 with avail 1536x816, DPR 1.25, 4 cores, Europe/Zurich, de-CH, AudioContext 48000. Font isolation is exact: only the profile's Windows families are detectable, with no DejaVu, Liberation, Noto or Cantarell leaking.
- **Open incoherence:** `WEBGL_debug_renderer_info` returns the spoofed ANGLE/D3D11 strings, but plain `getParameter(VENDOR)`/`getParameter(RENDERER)` return `Mozilla` and **`llvmpipe, or similar`**. The unmasked and masked values therefore disagree, and `llvmpipe` names the real stack. `webGl:parameters` is the config key that should fix it, but its expected key format is undocumented — verify against upstream before use, and add a leak-test assertion that no WebGL string contains `llvmpipe`. *(Closed 2026-10-05.)*
- **The chrome needed undoing.** Camoufox ships a live minimalisticfox `chrome.css` (the file even contains a stray `*/`) that hides tab close buttons, the bookmark star, the extensions button, the bookmarks toolbar and the window controls, shrinks tabs to 25px and sets `pointer-events: none` on `.tab-content`. An earlier note in this file claimed that theme had been reverted upstream — it has not. We write a per-profile `chrome/userChrome.css` that restores all of it; `toolkit.legacyUserProfileCustomizations.stylesheets` is already true in `camoufox.cfg`.
- **Address-bar search cannot be fixed by configuration.** The `addons` config key does work (`DEBUG: Installed 1 addon(s)`, and a search-provider WebExtension registers), but `no-search-engines.patch` leaves the search service unable to start at all: `SearchService #init failure — JSON error: missing field 'recordType'` from `RustSearch`. With the service dead no engine can be selected, which is why aliasmode-firefox had to patch rather than configure. The non-patching option is to repair the stripped `search-config-v2` dump inside the engine's `omni.ja` (a zip) as a post-fetch step.

**The masked and unmasked WebGL strings must agree (2026-10-03, verified)**

*Superseded 2026-10-05. The requirement stands; the mechanism below — matching the
claim to the host's bucket — is gone, and "the virtual-machine flag cleared on every
profile" did not hold: later runs were flagged again.*

fingerprint.com flagged profiles as virtual machines, and the cause was a
contradiction this file had already documented without acting on it. Camoufox spoofs
only `WEBGL_debug_renderer_info`'s unmasked strings; plain `getParameter(RENDERER)`
keeps reporting Firefox's coarse bucket for the *real* GPU. So a profile claimed a
modern discrete card while the masked value said `Radeon R9 200 Series, or similar`
— a pairing no real machine produces. Their virtual-machine signal is an ML score
(`virtual_machine_ml_score`, flagged above 0.6) over exactly that kind of
combination, and it reads the debug extension explicitly.

The profiles claiming a *discrete modern* GPU were flagged; the one claiming
integrated was not.

Fix: every `GpuPreset` now carries the masked bucket it must sit beside,
`kiwi-fox selfcheck` measures and caches the host's real bucket, and the generator
only claims cards that agree with it. **Verified: the virtual-machine flag cleared on
every profile**, leaving only VPN detection, which fires on any datacenter exit and
is not something a browser-side design can address.

Two consequences worth stating. Bucket matching **collapses GPU variety** — on this
host only two presets agree, so all profiles share a GPU string and the validator
warns about it. That entropy moved to cores, fonts, audio, locale and exit IP. It is
a deliberate trade: the incoherent version had more variety and got flagged. And the
GPU must be chosen *before* the form factor, or an explicit `--gpu-family` is
silently ignored when no preset of that family ships in the form already picked.

**Timezone comes from the exit, not the country.** An AU exit in Perth was given
`Australia/Sydney`, two hours out from its own IP. A country can span several zones,
so the measured exit timezone wins over the region default.

**Plausible is not the same as common (2026-10-03, fingerprint.com)**

Profiles differing only in screen geometry got different suspect scores, the higher
ones carrying **"Virtual machine detected"**. Flagged: `1280x800 @1.5`,
`2048x1152 @1.25`, `1600x900 @1.0`. Clean: `1920x1080 @1.0`. Every flagged value is
*arithmetically* a real panel at a real Windows scale factor, so the heuristic is not
checking the maths — it is checking whether the reported resolution is one real
machines commonly report. `SCREENS` now holds only dominant-share combinations.

**Do not add a resolution because the arithmetic works. Add it because real machines
report it.** The same error as the font episode in a different costume: a value can be
internally valid and still wrong because it is rare.

What did *not* fire in those runs: tampering detection was clean on every profile, so
the spoofing itself holds. VPN detection fires on any datacenter exit and this design
cannot avoid it.

**Audit the sources, not the appearance (2026-10-03)**

`kiwi-fox selfcheck <profile>` probes a live profile from inside its own namespace —
the page is served from the gateway on loopback, which the firewall permits — and
`kiwi-fox compare <a> <b>` diffs two, classifying every signal by **where the value
comes from**: `spoofed` (we set it), `derived` (follows from something we set),
`host` (the real machine), `engine` (the build). A signal we never set is not spoofed
just because it looks plausible; that distinction is the point of the tool.

Its first run found three faults that reading the code had not:

- **`navigator.languages` held a single entry** despite a four-entry list in the
  fingerprint: the engine derives it from `locale:*` and ignores
  `navigator.languages` entirely. Fixed via `locale:all`. A one-item list is itself
  unusual.
- **`css.scrollbar` was 0** — GTK overlay scrollbars, where Windows reports ~17px.
  A 0px scrollbar is a Linux giveaway. Now pinned.
- **`window.inner` was 955px tall against a spoofed `availHeight` of 752**, and
  identical across profiles. Inner cannot exceed avail on a real machine, so it is a
  logical impossibility a checker can test directly. **Still open:** the real window
  is not sized to the profile and the `xulstore` seed does not hold.

**Vary what is measured, not what looks varied (2026-10-03, confirmed against the live demo)**

Two profiles with visibly different machines — different GPU strings, screens, core
counts, canvas and audio seeds, and font sets of 53 vs 48 families — produced an
**identical `stableId`**. `stableId` is built from math, webgl, fonts and intl, and
every one of those four had collapsed:

- **fonts.** neoprint probes a **fixed list of 48 families**. Every Windows entry on
  it — Arial, Calibri, Cambria, Consolas, Segoe UI, Tahoma, Georgia, Times New
  Roman, Verdana, Courier New — is mandatory on Windows and therefore present in
  every profile, and everything we varied (the CJK and complex-script block) does
  not appear on their list at all. The font difference was real and completely
  invisible. **We were varying the fonts nobody probes while holding constant the
  ones everybody probes.**
- **webgl.** `webgl-spoofing.patch` intercepts only `UNMASKED_VENDOR_WEBGL` and
  `UNMASKED_RENDERER_WEBGL`. Plain `getParameter(VENDOR)`/`getParameter(RENDERER)`
  are untouched, so two profiles claiming NVIDIA and Intel both reported the host's
  real `Radeon R9 200 Series, or similar`. The spoof never reached the value being
  hashed.
  *(The observation was right, the conclusion drawn from it was not: the plain
  parameters are spoofable — see 2026-10-05.)*
- **math.** Identical for every Firefox on earth, by design.
- **intl.** Both exits were in CH, so both profiles legitimately resolved to de-CH.

The fix was to move the variation onto the probed list: Open Sans, Lato and Source
Sans 3, installed into per-family directories in the image, with each profile's
fontconfig exposing only its own subset. They are open-licensed, nothing is
committed here, and they genuinely vary on real Windows machines through Office,
Adobe and user installs. Liberation, DejaVu, Noto and Roboto are deliberately
excluded — neoprint categorises those as Linux fonts, so they would betray a
Windows claim. **Confirmed: both profiles then reported unique IDs.**

The same finding forced a second change. Because the masked renderer leaks the real
GPU family, claiming a different vendor contradicts itself inside a single WebGL
context — a spoof-detection risk worse than a shared identifier. The claimed family
now defaults to the host's real one, read from `/sys/class/drm/card*/device/vendor`
(`--gpu-family` overrides).

Two inputs remain permanently shared and cannot be fixed from configuration: webgl
(Camoufox cannot mask the plain parameters) and math. `crossBrowserId` therefore
still matches across profiles, exactly as documented. *(Superseded 2026-10-05 — see "WebGL, devices and voices, re-read from source".)*

The transferable rule: **before varying a signal, find out what the adversary
actually measures.** Read their collector, not your own assumption about it. A
difference that does not touch the probed set is not a difference.

**Fingerprint (2026-10-03)**

- `canvas:seed`, `audio:seed`, `fonts:spacing_seed` and `AudioContext:sampleRate` are real config keys, so canvas and audio *are* per-profile movable. A **stable per-profile** offset is not what noise detection catches: Brave is flagged for re-randomising per session/domain, while a value constant for a profile across every launch is simply a different machine. *(Measured 2026-10-05: `canvas:seed` is inert at this tag; `audio:seed` and `fonts:spacing_seed` are read by patches.)*
- There is no `deviceMemory` key, matching Firefox not implementing it, so neoprint's memory-versus-cores heuristic cannot fire on Gecko.
- JSON cannot carry `Infinity`, and pydantic silently serialises `float("inf")` to `null`, which then fails to load. Infinite battery times are represented as `None` and simply not emitted.

**WebGL, devices and voices, re-read from source and re-measured (2026-10-05, test VM, engine 152.0.4-beta.30)**

Four earlier entries in this file are wrong, all for the same reason: a conclusion
drawn from one probe instead of from the engine's source. They are marked where they
stand. What is actually true:

- **Firefox never reports a card, only a series.** `dom/canvas/SanitizeRenderer.cpp`
  collapses every renderer into a handful of representative devices ("GeForce RTX
  3090" becomes "GeForce GTX 980" — that file's own example), and plain
  `getParameter(RENDERER)` returns the *same* sanitised string as
  `WEBGL_debug_renderer_info`; `VENDOR` is always `Mozilla`. On Windows that leaves
  eleven devices in total — three AMD, three NVIDIA, four Intel and Microsoft's
  software renderer. The card list this project shipped — Chrome-style strings
  with PCI ids and driver versions — named things no Firefox can say.
  `core/fingerprint/webgl.py` now carries six series with their real-world share, and
  a port of the sanitiser, so a card name, an old stored string and a Linux probe
  result all resolve to the series Firefox would report.
- **The masked renderer can be spoofed.** `webGl:parameters` is keyed by the decimal
  GL enum as a string (`"7937"` is RENDERER) — `MaskConfig::GLParam` — and is
  consulted first for every `getParameter`. Measured: all four strings come back as
  configured.
- **Do not apply upstream's whole record.** Its parameter table is a dump of a fresh
  context, state included, and the engine returns table values unconditionally: with
  the full record a 64x64 canvas reported a 300x150 viewport. Only the 43 capability
  limits are emitted, plus four stencil masks whose *initial* value differs between
  ANGLE and Mesa (the one accepted cost: a page that sets a stencil mask and reads it
  straight back gets the default). Context attributes are not emitted at all. The
  unmasked strings stay out of the table, because the table answers before Firefox
  checks that the debug extension was enabled. Verified per mode: 20/20 and 49/49
  parameters, both extension lists and every shader precision format read back as
  emitted, while viewport, blend, bindings, anisotropy and compressed formats stay
  live.
- **What the old default leaked** (measured, same engine): the masked renderer in
  Linux wording with no ANGLE wrapper, `MAX_VIEWPORT_DIMS` 16384 instead of 32767, a
  line width range of `[1, 255]` instead of `[1, 1]`, 160 combined texture units
  instead of 32, a stencil mask of 255 instead of 0x7FFFFFFF, three extensions ANGLE
  lacks and one it has missing. Each says "not Windows" on its own. This, rather than
  GPU *family*, is the likelier source of the virtual-machine and tampering flags,
  which were never isolated to a cause — **unverified until a reworked profile is run
  against fingerprint.com again.**
- **The frame the GPU draws is still the host's.** `readPixels` of a rendered scene
  hashed identically across every series, custom strings and raw. That is the
  residual, and no setting moves it.
- **Tab crashes: `mediaDevices:micros = 0` with a webcam.** The engine's
  `FilterExposedDevices` inserts microphones at index 0 and cameras at index 1; with
  no microphone the camera insert is past the end of an empty array and the content
  process dies with signal 11 on `enumerateDevices()`. Reproduced twice out of twice;
  1/1, 1/0 and 0/0 are fine. The generator drew that combination for a quarter of
  desktop profiles. It now always draws a microphone, and the engine config repairs
  stored profiles at launch.
- **Voices** take objects, not names: `{lang, name, voiceUri, isDefault,
  isLocalService}`, with the URI built the way `SapiService.cpp` builds it
  (`urn:moz-tts:sapi:<name>?<lang>`). Emitted now; the list was empty before, which no
  Windows install is. Names for twelve locales come from upstream's capture of real
  machines; de-AT, de-CH, sv-SE, fi-FI, nb-NO, da-DK and nl-BE are from memory and
  **unverified**.
- **Keys that do nothing at this tag**, each measured by setting an absurd value:
  `canvas:seed`, `navigator.maxTouchPoints`, `navigator.languages`,
  `navigator.buildID`, `pdfViewerEnabled`. No patch in the repository reads them. So
  no profile ever reported touch points, and canvas was never "stable per profile":
  what a page gets is stock Firefox's own default protection
  (`privacy.baselineFingerprintingProtection`, on for every user), which perturbs
  canvas readback with a per-session key. Same profile, two launches: two hashes.
  With that pref off: one hash, identical for every seed. Leave the pref at its
  default — it is what a real Firefox 152 does, and it is also where `availHeight =
  height - 48` on Windows comes from, whatever the real taskbar is.
- **The probe must not touch what it measures.** It used to stop the running browser
  and open the real profile directory, which left its own page in the session
  history: the "Unable to connect 127.0.0.1:8899" tab at every launch. It now runs a
  throwaway browser in a throwaway directory beside the user's session, and
  `selfcheck` ends with an audit of what a page could catch.
- **Render node.** `renderD128` is not necessarily the GPU Mesa can drive: on a
  hybrid laptop the other node belongs to the proprietary NVIDIA driver. The node is
  chosen by driver now (`core/gpu.py`).

The rule this adds to the two above: **read the engine before believing a probe.**
"The masked renderer cannot be spoofed" was one failed guess at a key format,
promoted to a design constraint that then shaped the card list, the generator and
the GUI.

## Architecture

```
GTK app (host)
  │
  ├─ provider modules (standalone, long-lived, their own kiwi apps)
  │    myst module ── myst node (one exit at a time) → dante SOCKS5 + dnsmasq
  │    9proxy module ── 9proxyd, N local ports, one residential IP each
  │    tor module ── EU-only exits, per-profile circuit isolation
  │    (plain SOCKS5 endpoints need no module: Mullvad 10.64.0.1:1080 etc.)
  │
  └─ podman, rootless ── per running profile:
       ├─ gateway container  OWNS the network namespace
       │     nftables: output policy drop; established accept; lo accept;
       │               exactly one destination allowed — the leased endpoint
       │     forwarder:  127.0.0.1:1080 → leased endpoint (adds credentials)
       │                 second listener: TCP tunnel for the resolver's DoT
       │     dnsmasq:    127.0.0.2:53, oisd + custom lists, upstream via above
       └─ browser container  --network container:<gateway>
             no netns, no routing table, no capabilities, no-new-privileges,
             profile volume (rw), fonts volume (ro), display socket
```

Why this shape:

- **The kill switch is the absence of a route, not software that has to notice.** The browser has no network namespace, no routing table and no interfaces of its own, so it cannot route around the gateway. If the proxy dies the profile simply loses connectivity. This pattern is **measured working on this host** (`novafox/ANALYSIS.md` §4): inside an enforced namespace, SOCKS5 to the proxy reached the Tor exit while direct connections, raw TCP to 1.1.1.1:53, UDP DNS and ICMP were all blocked. The same identity in cooperative mode reached the internet directly and leaked the host address — that gap is the whole argument.
- **Extra apps per profile are free.** Another app container for the same identity just joins the same namespace with `--network container:<gateway>`.
- **Why a forwarder:** Firefox prefs cannot authenticate against SOCKS5, and 9proxy's local ports should have basic auth on. Credentials stay out of the browser's reach, it is one stable firewall target, and it is the per-profile isolation knob — a random per-profile user/pass against a Tor SOCKS port triggers `IsolateSOCKSAuth` so profiles do not share circuits.
- `dnsmasq` listens on **127.0.0.2**, not 127.0.0.1: pasta/pod DNS occupies 127.0.0.1. The browser's resolver is set to 127.0.0.2.
- Rules key on **destination**, not sending uid — a uid-matched exemption silently stops working if a relay drops privileges differently than expected.
- Non-proxy-aware apps joining the namespace need a transparent redirector (redsocks). Measured caveat: redsocks cannot always recover the original destination via `SO_ORIGINAL_DST` for locally generated redirected packets, and when that lookup fails the traffic is **dropped rather than silently tunnelled** — the safe direction. The default-drop filter, not redsocks, is the security boundary.
- The leased endpoint is resolved to a literal address on the host during pre-flight: resolution must happen before DNS is cut off, and nftables needs an address.
- Display: Wayland socket passthrough by default (`--userns=keep-id`, mount `$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY`), X11 as fallback with a weaker boundary. Handle SELinux labelling on Fedora-family hosts. The real window must open no larger than the profile's spoofed `availWidth/availHeight`.
- Do **not** pass `/dev/dri`. Measured: it changes no fingerprint signal and adds attack surface.
- Audio (PipeWire socket) is optional and off by default.
- Container `TZ` and locale env are set from the profile in addition to `CAMOU_CONFIG_*`.
- Every podman resource carries the label `app=kiwi-fox` so orphans can be cleaned up.
- Never: `--privileged`, host networking, running the browser as real root.

## Proxy provider modules

A module is a **standalone, independently runnable** service that exposes one or more proxy endpoints. It is its own git repo with its own `kiwi.manifest`, installed through kiwi-updater, and works with or without kiwi-fox. Kiwi-fox **discovers** installed modules, uses them when running, and may offer to start or stop one — never requires it to be managed by us.

Module descriptor (the contract; keep it stable across repos):

- identity: name, version
- endpoints: address, port, auth requirement, **slots** (how many profiles can lease distinct exits concurrently)
- control surface: how kiwi-fox selects an exit (HTTP API, `podman exec` CLI, or none)
- account surface: what sign-in the module needs, if any (see "Module accounts")

**Every module exposes SOCKS5. There is exactly one endpoint kind.** Tor, Mullvad and myst's dante already speak it, and 9proxy will. If a provider speaks something else internally — an HTTP port, a wireguard interface — **adapting is the module's job**, not kiwi-fox's. The module presents SOCKS5 and nothing else. This is what keeps the gateway, the forwarder, the firewall rule and the DNS design single-shaped instead of branching per provider.

**Endpoint reachability.** Modules live outside the profile's namespace. A loopback-bound module port is not reachable from a gateway container at all, and host interface addresses (`10.8.0.1`, `10.64.0.1`) depend on host routing. Modules must therefore publish on a **stable host-side address** that the descriptor states explicitly, so the gateway can allow exactly that `IP:port`. Prove this under rootless Podman in M2 before building on it.

### Inventory

| Provider | Exits | Auth | Notes |
| --- | --- | --- | --- |
| Mysterium (myst module) | **1 at a time** | none on dante | Primary. Single-slot — see below. Wireguard is internal to the module. |
| 9proxy (9proxy module) | N (configurable port count) | user:pass | Primary. Residential. |
| Mullvad | many | none | `10.64.0.1:1080` random EU; specific exits by in-tunnel IP. **IP only for now, no hostnames.** Requires the host tunnel up — if it drops the profile loses egress, which is correct, but the UI must say *why*. |
| Tor (tor module) | many circuits | per-profile user/pass | Optional, low priority. Restrict to good EU exits (`ExitNodes` + `StrictNodes 1`); per-profile credentials for `IsolateSOCKSAuth`. Note Tor exits are widely blocked by the sites this is used for. |

The VPN itself belongs on the host or a LAN router/gateway. **No double-hop inside kiwi-fox** — do not reimplement mystop's gluetun route/ip-rule fixups here.

### myst module

A new module, built properly from scratch in its own repo (`kiwi-fox-myst`). `mystop` is **reference only** — read its configuration, do not modify it or depend on it.

Shape: myst node (headless `myst daemon`, TequilAPI published) → `myst0` wireguard interface → dante SOCKS5 on 1080 → dnsmasq ad-blocking bound to `@myst0`. No KasmVNC, no Electron desktop, no gluetun, no double-hop: TequilAPI is the control surface, so the GUI that mystop needed is replaced by kiwi-fox's own module panel. Runs standalone — `podman run` it and it is a working ad-blocking SOCKS5 exit with no kiwi-fox present.

Verified TequilAPI surface (from `tequilapi/endpoints/connection.go`): `GET /connection`, `PUT /connection`, `DELETE /connection`, `GET /connection/statistics`, `GET /connection/traffic`. `PUT /connection` takes `consumer_id`, optional `provider_id`, `service_type`, filters (`country_code`, `providers`, `ip_type`, `include_monitoring_failed`), `connect_options` (`disable_kill_switch`, `dns`) and `hermes_id`. There is **no exit-IP or geo endpoint**; the right approach is the one mystop demonstrates — query a geo endpoint forced through `myst0` — which is the same thing kiwi-fox's pre-flight already does.

- **Single-slot.** The connection manager returns `ErrAlreadyExists`: one active connection per node. The module advertises `slots: 1`; kiwi-fox shows it occupied while a profile holds it and refuses to launch a second myst-backed profile concurrently. A multi-node pool is a later option and must not require a contract change — keep `slots` in the descriptor from the start.
- **Verified-provider cache.** Provider-reported country/city is self-reported and stale, and the real exit IP is only knowable after connecting. So: ask TequilAPI for candidates filtered by `country_code` → connect → verify the actual IP and geo with kiwi-fox's pre-flight → cache `provider_id → {ip, subnet, country, city, asn, quality, verified_at}` locally → prefer verified providers, and pin a profile to a verified `provider_id` so its exit is stable across launches. The cache is what makes myst usable for a stable identity at all; without it every connect is a new machine location.
- **Reimplement mystop's two-phase DNS**: boot with direct DNS so the node can reach discovery, then switch to kill-switch mode (`server=<dns>@myst0`) once the tunnel is up, with Mysterium's own domains always bypassing so the node can reconnect after a drop. Its config is a known-good starting point. That logic belongs to the module, not to kiwi-fox.
- **Control API is mTLS, with client-certificate auth.** It moves crypto-wallet operations and connection state, where being *correct* matters more than being minimal, so the control plane is authenticated and integrity-protected rather than merely hard to reach.
  - The node's own TequilAPI is **plain HTTP with Basic auth** (defaults `myst`/`mystberry`) bound to 127.0.0.1, and has no TLS of its own. So the module terminates TLS itself: a small reverse proxy in the module container listens on the published port, requires a client certificate, and forwards to `127.0.0.1:4050`.
  - **Certificates are generated automatically on first run** — a module-local CA, a server cert whose SAN covers the published address, and a client cert for kiwi-fox. The module keeps CA and server key at 0600 in its own data directory; the client bundle is handed to kiwi-fox (its config dir, or imported through the GUI). kiwi-fox **pins the module's CA** and verifies the server cert against it. Nothing here should ever require the user to run `openssl` by hand.
  - Keep TequilAPI's Basic auth enabled *behind* the TLS layer, credentials in libsecret. Defence in depth, and it costs nothing.
  - Long-lived certs (years, not days) so nothing breaks silently, plus an explicit renew command. **Never fall back to plaintext on a TLS failure** — surface the error and refuse. A silent downgrade is worse than a visible outage.
  - Still bind the published port to the host loopback. mTLS is the authentication; unreachability is defence in depth, not a substitute.
  - The same scheme covers the 9proxy module's control API, so kiwi-fox has exactly one client implementation, one auth model and one failure path.
- **Consumer identity.** A headless node still needs a registered consumer identity with a balance before it can connect. Solved by importing the existing wallet — see "Module accounts".

### 9proxy module

A new module, built properly from scratch in its own repo (`kiwi-fox-9proxy`). `9proxy-pod` is **reference only** — read its Dockerfile for the RPM install, do not modify it. Its current shape cannot be used anyway: `privileged: true`, systemd as PID 1, and sshd with a hardcoded password.

Runs standalone, same as the myst module: start it, sign in, and it is a working pool of residential SOCKS5 endpoints with no kiwi-fox present.

Two planes, and they are unrelated — worth stating because they are easy to conflate:

- **Data plane** = the SOCKS5 endpoints the gateway connects to. 9proxy already forwards residential IPs to local ports; a protocol front-end is needed *only* if those ports turn out not to speak SOCKS5.
- **Control plane** = how kiwi-fox picks a country, assigns an IP to a port and reads status. This is needed regardless, exactly like myst's, and it is the module's own small HTTP API over mTLS — the same scheme as the myst module, so kiwi-fox has one control client and one GUI pattern rather than HTTP for one module and `podman exec` for another. The module wraps the `9proxy` CLI (or `9proxy api`, if that turns out to be a real local API) behind it, and exposes: list available IPs with country/city/ISP, assign IP → port, list port assignments, lease/release a port, and the settings below.

- Unprivileged, no systemd, no sshd. `9proxyd` as the entrypoint; the control API is the only way in.
- Verified CLI surface: `9proxy proxy -c <country> -p <port>` assigns by country to one port; `9proxy proxy -p <port>` assigns a random one; `9proxy proxy -n -p <port>` reuses a proxy active in the last 24h; `9proxy proxy -n -u` lists current forwards with ports and status; `9proxy proxy -u` is an interactive filter UI (country/state/city/ZIP/ISP); `9proxy setting -s <start port>` and `-l <count>` configure the port range; `9proxy auth -u/-p/-l`. **Watch the overloaded `-n`:** `setting -n` disables auto-refresh, `proxy -n` means reuse-recent.
- **Turn auto-refresh off** (`9proxy setting -n`) for ports kiwi-fox leases. A rotating exit IP destroys the profile's stable identity. Surface an IP change loudly instead of absorbing it.
- **Turn local-port auth on** (`9proxy setting --basic_auth --proxy_username … --proxy_password …`) so nothing else on the host can borrow the residential IPs. The forwarder holds the credential; it never reaches the browser.
- Port leases are sticky per profile and recorded in the profile, so relaunching reuses the same port — and `proxy -n -p <port>` to reuse the same IP where possible.
- **SOCKS5 on the local ports**, to match every other provider. Confirm 9proxy actually offers SOCKS5 there on first contact; if those ports turn out to be HTTP-only, the module puts a thin SOCKS5 front-end in front of them. kiwi-fox never learns about it.

## Module accounts

Modules need credentials — a Mysterium identity, a 9proxy login — so kiwi-fox has an account surface per module: API, settings pane, and CLI. Secrets go to libsecret; keystore files live in the module's own data directory with mode 0600. **Never** in JSON, logs, container env visible to the browser, the repo, or a profile directory.

**Mysterium — import an existing wallet.** Verified TequilAPI identity routes: `GET /identities`, `POST /identities` (create), `PUT /identities/current`, `GET /identities/:id`, `GET /identities/:id/status`, `PUT /identities/:id/unlock`, `GET /identities/:id/registration`, `PUT /identities/:id/balance/refresh`, `POST /identities/export` (backup), and `POST /identities-import` — note the hyphen, it is not under `/identities/`. The import payload is `Data` (the exported/keystore blob), `CurrentPassphrase`, `NewPassphrase`, `SetDefault`.

- **Keystore file import is first-class:** GTK file chooser → read the file → POST as `Data` with the passphrase → optionally set default. This is the path for an existing wallet, and it is what makes the new myst module usable without touching the old folders: the user copies their own keystore in through a file dialog.
- **Pasting a raw private key is not directly supported** — the API wants an exported/keystore blob, not bare key material. Accepting a pasted key means building a V3 keystore locally from key + passphrase first, which needs a crypto dependency. Ask before adding one; offer keystore-file import first and treat raw-key paste as a follow-up.
- Offer **export/backup** in the same pane, and show registration status and balance from the status/registration/balance endpoints — a node that cannot connect is usually an unregistered or unfunded identity, and the UI should say so rather than reporting a vague failure.
- Importing or exporting a wallet is a privileged action on something that holds real funds. Confirm explicitly, never log the blob or either passphrase, and never auto-copy a keystore between directories.

**9proxy.** `9proxy auth -u <user> -p <pass>` to sign in, `auth -l` to sign out. Credentials to libsecret, signed-in state shown in the module panel.

**Plain SOCKS5 endpoints** (Mullvad, a local Tor) have no account surface. The descriptor says so and the UI shows nothing.

## DNS and adblocking

One blocking resolver per profile, in that profile's gateway container: **dnscrypt-proxy**, not dnsmasq.

Why not dnsmasq, even though mystop's config works: **dnsmasq cannot do DoT or DoH at all.** It only speaks plain DNS upstream, and plain UDP cannot traverse SOCKS5. An earlier draft of this file had dnsmasq "speaking DoT to a pinned authentication name" — that was wrong, and there is no auth name to pin because there is no TLS in dnsmasq. dnscrypt-proxy does the whole job in one Go binary:

```toml
proxy = 'socks5://127.0.0.1:1080'   # the gateway's forwarder
force_tcp = true                     # SOCKS5 carries no UDP
```

- `proxy` + `force_tcp` is the documented configuration for running over Tor, which is exactly our constraint. Blocklists (`blocked_names`, wildcard patterns like `ads.*` and `*.example.com`), `blocked_query_response = 'refused'`, and its own cache — one component instead of three. Despite the name it speaks DoH, DoT, ODoH and DNSCrypt; **we use DoH and never the DNSCrypt protocol.**

### Which transport, and does it look normal

Separate the two audiences, because they see completely different things:

- **The website sees the transport not at all.** It only ever learns *which recursive resolver* asked its authoritative server, plus any ECS. Our transport choice is invisible to it.
- **The exit operator sees the transport** — and with residential proxies that is someone's home device. This is the only place "looks normal" applies.

So, ranked for the exit's view:

| Transport | On the wire | Verdict |
| --- | --- | --- |
| **DoH to a major provider** | TCP 443, TLS to `dns.google` — indistinguishable from ordinary HTTPS, and stock Firefox and Chrome both do this | **Default.** Blends by construction. |
| DoT | TCP 853 — a dedicated port that stands out a little, nothing else wrong with it | Fallback if DoH misbehaves. |
| DNSCrypt | Unusual ports, small provider set, prefers UDP (which SOCKS5 cannot carry) | No. |
| Plain DNS | Cannot traverse SOCKS5 as UDP; over TCP it is cleartext to the exit | No. |

**Google Public DNS over DoH is the default, and your instinct about it is right for a non-obvious reason:** Google propagates EDNS Client Subnet, Cloudflare strips it. Since our queries already exit through the profile's proxy, Google sees the exit IP and propagates that exit's subnet to authoritative servers — so CDN geo-routing lands where the exit is, matching what the site sees. Cloudflare stripping ECS would geo-route us to wherever Cloudflare's resolver sits instead. The tradeoff is that Google sees this profile's queries tied to its exit IP; per-profile exits mean it still cannot link profiles to each other, and the resolver stays a per-profile setting.

Set `network.trr.mode=5` so Firefox never runs its own DoH and bypasses our resolver. Not site-observable either way.

**The alternative worth knowing about:** `socks_remote_dns=true` — Camoufox's own default — hands the hostname to the proxy and lets the *exit* resolve it. That is the most native option there is, since the exit then uses whatever resolver its network uses, exactly like a real user on that connection, and no DNS leaves us at all. The reason it is not the default here is that it makes DNS-level adblocking impossible: there is nothing of ours in the path. Keep it as a per-profile setting for anyone who wants maximum nativeness and is content with in-browser blocking only.
- **DNS exits through the same SOCKS5 exit as the traffic**, so resolution is geo-consistent with the exit IP. This is what makes 9proxy's per-port residential IPs work properly: a German resolver answering for a Vietnamese exit would geo-route CDNs wrong, which is the inconsistency EDNS Client Subnet was supposed to patch over. Routing DNS through the exit removes the problem instead of papering over it.
- Browser points at the resolver and **`network.proxy.socks_remote_dns=false`** for that profile, since resolution now happens in the namespace. Bind the resolver on **127.0.0.2**, not 127.0.0.1 — pasta/pod DNS occupies 127.0.0.1.
- **The firewall is the guarantee, not the config.** dnscrypt-proxy has a history of bugs where not every query honoured `proxy`. Under the gateway's default-drop ruleset a query that tries to go direct is dropped, not leaked — fail closed. Never rely on the resolver's own config for containment, and assert this in the leak tests.
- **List: `https://big.oisd.nl/domainswild2`** — verified 2026-10-03 as the right one. It is 244,250 bare domain entries (4.9 MB) and its documented semantics ("`example.com` blocks `example.com` and `subdomain.example.com` but not `thiseexample.com`") are exactly dnscrypt-proxy's bare-name rule, so it feeds `blocked_names` unmodified, no conversion step. (`domainswild` is the `*.example.com` spelling of the same list and also works; `dnsmasq2` is what mystop uses and is for dnsmasq, not us.) Plus user-supplied custom lists. Fetched on the host and mounted read-only; refresh is a host-side user timer, never the browser's.
- **Per-profile resolver and per-profile lists** are now both natural, since the resolver is per profile rather than per module. Store the upstream choice in the profile.
- **No EDNS Client Subnet.** The resolver and the browser share one exit, so the upstream already sees the right location. Do not add it back without a measurement showing a divergence.
- The myst module keeps its own internal dnsmasq bound `@myst0` for the node's own resolution and its own kill switch. That is internal to the module and not kiwi-fox's business.

## Launch flow

1. Load profile; fetch proxy secret from the keyring.
2. Resolve the module: is it installed, is it running (offer to start), does it have a free slot, lease an endpoint (9proxy port / myst connection / plain SOCKS5 address).
3. Pre-flight on the host: resolve the endpoint to a literal address, connect through it, fetch exit IP and geo (country, city, timezone) from a configurable endpoint. Record the result into the verified-provider cache.
4. Compare with the profile. Mismatched timezone/locale, or an exit country changed since last run → **warn visibly and continue.** Do not block; the user decides. (Hard gating on geo is a later refinement, once we know how noisy these providers are in practice.)
5. Start the gateway container → nftables up → forwarder up and listening → dnsmasq up → health probe through the forwarder → DNS probe through the resolver. The gate must not open before the relay is accepting connections, or there is a window where traffic is redirected into a dead port.
6. Start the browser container joined to the gateway's namespace. If the gateway dies, the browser loses connectivity by construction; tear it down anyway. On browser exit, tear down the gateway and release the lease.
7. A profile with no proxy must be an explicit setting, shown prominently. Never fall back to a direct connection; `network.proxy.failover_direct=false`.

Proxy input accepts `socks5://user:pass@host:port`, `http://`, `https://`, and the vendor paste format `host:port:user:pass`. Warn when two profiles share the same exit.

## Data model

Stored under `~/.local/share/kiwi-fox/`:

- `profiles/<uuid>/profile.json` — name, engine + pinned version, module + leased endpoint (port / provider_id), locale, timezone, screen preset, notes, created/last-used, last observed exit IP + geo.
- `profiles/<uuid>/dns.json` — upstream resolver, transport, blocklist selection.
- `profiles/<uuid>/fingerprint.json` — the frozen Camoufox config, including the profile's font set.
- `profiles/<uuid>/browser-data/`, `downloads/`.
- `providers.json` (or sqlite) — the verified-provider cache, shared across profiles.
- `modules/` — discovered module descriptors.

Proxy passwords and module credentials go to the Secret Service via libsecret. Never into JSON, logs or container env visible to the browser. Note the seed is reproducible: whoever reads a profile's seed can rebuild that identity's machine.

## Fingerprint rules

- Generated once at profile creation from a seed and stored. Never regenerated silently. Regeneration is an explicit user action with a warning. On engine upgrades only version-dependent fields change; hardware identity stays.
- "Duplicate profile" must create a new fingerprint and require a new exit.
- Draw values from real-world distributions (fpgen/BrowserForge), not hand-invented ones.
- `core/fingerprint/validator.py` is the most important module in the repo. It must reject incoherent profiles. Minimum checks, neoprint-derived ones marked:
  - UA OS ↔ `navigator.platform` ↔ `oscpu` ↔ font set ↔ WebGL series (both renderer values, limits, extensions) ↔ voices
  - UA version == pinned engine version
  - screen ≥ avail ≥ outer ≥ inner; DPR ∈ {1.0, 1.25, 1.5}
  - core count ↔ `deviceMemory` plausible together and for the GPU tier *(memory vs cores mismatch)*
  - `maxTouchPoints` is always 0: the pinned engine cannot report any without Playwright *(touch points vs screen size)*
  - never a camera without a microphone: that combination crashes the tab *(engine bug, see 2026-10-05)*
  - font set = Windows 11 mandatory core + a plausible optional set; count plausible *(unusual font count)*
  - WebGPU absent, and `dom.webgpu.enabled=false` pinned *(GPU vendor mismatch WebGL vs WebGPU)*
  - timezone ↔ locale / Accept-Language ↔ exit geo
  - WebRTC disabled or exposing only the proxy IP; no host or LAN candidates
  - no randomisation prefs enabled anywhere *(noise detection)*
  - two profiles must not share a font set, screen or WebGL string
- The browser must see only its profile's Windows 11 font set through fontconfig. The base image ships no stray fonts (no DejaVu, Noto, Liberation visible to the browser).

## Prior art in this workspace

**All four are read-only reference. Do not modify them, do not depend on them at runtime, and do not refactor them as part of kiwi-fox work.** They are local, unpublished projects; where they live on the workstation is in the gitignored `docs/testbed.local.md`. Read them, take what is proven, and reimplement it in a kiwi-fox repo.

- **`novafox`** — the previous iteration of this idea: shell + podman, per-identity images, personas, a gateway kill switch, a fingerprint probe and linkage report. `ANALYSIS.md` is the most valuable document we have: every number in it was measured on this host. Read it before changing anything about fingerprint or network design. Kiwi-Fox departs from it in three deliberate ways: Camoufox instead of stock Firefox with prefs (so spoofing is in C++ and the target is Windows 11, not a Linux distro); no FPP/RFP and no canvas noise (neoprint detects noise, and FPP was measured to pin `hardwareConcurrency` to 8 on Firefox 153 regardless of the pref); one base image with per-profile font sets instead of per-distro persona images.
- **`pfox`** (historical, documented in `novafox/ANALYSIS.md`) — the failure to not repeat: many profiles in one container share the machine, and a pile of rare privacy prefs made it *more* identifiable, with an advisory proxy that could fail open.
- **`mystop`** — reference for the myst module. Source of the dnsmasq/oisd configuration, the `@iface` DNS kill switch, the 127.0.0.2 trick, the dante config and the two-phase DNS startup. Skip its KasmVNC desktop, gluetun and double-hop entirely. Note it also contains wallet/keystore JSON and a node UI password in the working tree — worth moving out before that repo goes anywhere public.
- **`9proxy-pod`** — reference for the 9proxy module: the RPM install and the port range are the useful parts; the privileged systemd + sshd shell is not.

## kiwi-updater integration

Kiwi-Fox ships as a kiwi app ([kiwi-updater](https://github.com/derlocke-ng/kiwi-updater)). Note that tool is working but due a rework of its own; integrate against its documented convention, not its internals.

- `kiwi.manifest` at the repo root: `NAME=kiwi-fox`, `COMPONENTS=cli gui service`, **`SCOPES=user`** (rootless podman needs no root — a plain user install must be fully functional), `INSTALLER=install.sh`, `LICENSE`, `HOMEPAGE`.
- `install.sh` handles `install|update|uninstall`, honours `KIWI_SCOPE`, `KIWI_PREFIX`, `KIWI_APP_DIR`, `KIWI_ACTION`, and skips desktop parts when `KIWI_GUI=0`. It also honours **`KIWI_PURGE=1`** (also passed as `uninstall --purge`): a plain uninstall must leave profiles, fingerprints and the provider cache alone so reinstalling resumes where the user left off; only `--purge` removes them, and that one deletes identities that cannot be regenerated — confirm loudly.
- **Never build container images during install.** It is slow and needs network at the wrong moment. Build on first launch, or via an explicit `kiwi-fox images` command.
- `service` covers the user timer that refreshes blocklists.
- Release by tagging (`git tag v0.1.0 && git push --tags`); kiwi follows the latest tag.
- Each provider module is its own kiwi app with its own manifest, listed alongside kiwi-fox in the catalog, installable à la carte.

## Tech stack

- Python 3.12+, PyGObject, GTK4 + libadwaita. Use system PyGObject (venv with system site packages).
- Podman through the CLI (`subprocess`, argument lists, `--format json`), wrapped in `core/podman.py`. No `shell=True`. No dependency on the Podman API socket.
- pydantic v2 for models, pytest, ruff (lint + format), pyright.
- Ask before adding any other dependency.

## Repo layout

```
src/kiwi_fox/
  app.py                 Adw.Application entry point
  ui/                    main window, profile editor, module panel, proxy test
  core/
    models.py            Profile, Module, Endpoint, DnsConfig, Fingerprint
    store.py             load/save, keyring
    modules/             descriptor loading, discovery, leasing
      base.py            the module contract
      myst.py            TequilAPI client + verified-provider cache
      ninep.py           9proxy CLI driver (podman exec)
      socks5.py          plain endpoint, no control surface
      tor.py             optional
    proxy.py             parsing, pre-flight, exit IP + geo
    dns.py               dnsmasq config generation, blocklists
    podman.py            thin CLI wrapper
    gpu.py               the host's render node and GPU vendor
    launch.py            profile -> gateway + browser spec -> lifecycle
    probe.py, probe.html measure a profile in a throwaway browser; audit the result
    fingerprint/         generator, validator, windows11 template, font sets,
                         webgl.py (GPU series) with its data/, and sanitizer.py
                         (a port of Firefox's renderer sanitiser, MPL-2.0)
    engines/             base.py, camoufox.py
containers/              gateway (nftables + forwarder + dnsmasq), browser
tools/                   import-webgl-data.py: refresh the vendored GPU records
tests/unit/              validator, proxy parsing, spec generation (golden files)
tests/leak/              in-namespace assertions against a live profile
docs/                    detection-notes.md, decisions.md, module-contract.md
```

## GUI

- Main window: profile list with name, module + exit country/city, running state. Actions: launch/stop, new, edit, duplicate, delete.
- Module panel: installed modules, running state, free slots, start/stop, and for myst a provider picker backed by the verified-provider cache (country/city filter, verified-at, quality).
- Editor: name, engine, module + endpoint, DNS section (upstream, blocklists), locale/timezone auto-filled from the exit, screen preset, font set, notes.
- "Self-check" opens the local probe page inside the profile.
- The UI must state plainly that profiles are **not** protected against hardware-level cross-browser IDs, and must not overclaim.
- Never block the main loop. Podman, HTTP and network calls run in worker threads and report back with `GLib.idle_add`.
- Follow the GNOME HIG and use Adw widgets. Build widgets in Python until the UI stabilises.

## Commands

Create these in M0 and keep this section accurate:

```
make run        # python -m kiwi_fox
make images     # podman build for containers/*
make test       # pytest tests/unit
make leak       # integration leak tests (needs podman + built images)
make lint       # ruff check + ruff format --check + pyright
```

Graphics, since the 2026-10-05 rework:

```
kiwi-fox gpus                              # the GPU series a profile can report, with real-world share
kiwi-fox new NAME ENDPOINT                 # default: this machine's series (--webgl host)
kiwi-fox new NAME ENDPOINT --series 'RTX 3060'   # any card name; Firefox reports its series
kiwi-fox webgl NAME [--mode host|preset|custom|off|raw] [--series …] [--vendor … --renderer …]
kiwi-fox selfcheck NAME                    # measure in a throwaway browser, then audit
kiwi-fox selfcheck NAME --host             # measure this machine, so `host` knows the exact series
```

## Testing

- Unit tests for the validator, proxy/endpoint parsing, dnsmasq config generation and container spec generation.
- Leak tests: a local probe page collects navigator, screen, fonts, canvas, WebGL, WebRTC and timezone into JSON; assert equality with the profile's fingerprint.
- Kill-switch tests, mirroring what novafox already measured: from inside the namespace, SOCKS5 through the forwarder must work while direct TCP, raw TCP to a public resolver, UDP DNS and ICMP are all blocked. With the forwarder stopped, nothing resolves and nothing connects. **No DNS query may reach the host resolver or leave as UDP** — assert on the host side, not only inside the namespace.
- DNS tests: the blocklist blocks; upstream travels through the tunnel/proxy; dnsmasq picks up a refreshed list after restart.
- Run neoprint locally (open source, client-side) in the leak suite: assert `id`/`stableId`/`weightedId` differ between two profiles, record which `crossBrowserId` components match, and assert the spoof-heuristic, anti-detect, bot and **noise-detection** layers all report nothing.
- Module tests: lease/release, slot exhaustion (launching two myst profiles must refuse cleanly), 9proxy port stickiness, auto-refresh confirmed off.
- Manual checks against CreepJS and BrowserLeaks with our own profiles; record findings in `docs/detection-notes.md`.
- When unsure whether a spoof is coherent, add a leak test instead of guessing.

## Test host

A Bluefin-dx **VM** — same OS, same podman, same rootless/SELinux behaviour as the dev machine — is available for anything that should not be tried locally. It has a graphical session, so the whole stack is testable there: containers, nftables, DNS, Wayland passthrough, the browser UI and the fingerprint probe. It is the right place to validate M2.

Its address and login are in `docs/testbed.local.md`, which is gitignored — they do
not belong in a published file.

**It is shared.** Another agent session may be working on it at the same time. So:

- Prefix every podman resource with `kf-` and carry the label `app=kiwi-fox`. Only ever act on resources carrying that label.
- Never run `podman system prune`, `podman stop -a`, `podman rm -a`, or anything else that touches resources you did not create.
- Do not assume a host port is free. Allocate, record, and release.
- nftables rulesets are per network namespace, so a gateway container flushing *its own* ruleset is safe. Never flush on the host itself.
- Check what is already running before starting, and clean up your own containers when finished.

A test rig is already set up there in `~/kf-test`: Camoufox v152.0.4-beta.30 unpacked under `cfox/`, a `probe.html` that reports screen/CSS-media/navigator values back to a local HTTP server, and a runner script. Reuse it rather than rebuilding one. A second rig, `~/kf-test/t5` (`drive.py`, `t.html`, `cases.json`), runs a list of engine configs each in its own throwaway profile, reads back every WebGL parameter, and beacons before and after `enumerateDevices()` so a dead tab is distinguishable from a slow one; it is what the 2026-10-05 measurements came from. Two traps it cost an hour to find: `-profile` needs an **absolute, already-existing** directory, and `pkill -f camoufox` matches your own ssh command line and kills the session before anything runs — use the bracket form `pkill -f "[c]amoufox"`. Note the processes are named `camoufox`, not `camoufox-bin`, so a `-bin` pattern silently leaves windows open on the VM's screen.

Caveat, and it matters for fingerprint work: **it is a VM**, so its virtual GPU, CPU topology and timing are not the dev machine's. *Relative* results hold there — whether two profiles differ, whether a spoof is coherent, whether the kill switch leaks. *Absolute* hardware baselines do not: canvas hashes, WebGL render hashes and hardware-perf numbers measured in the VM are not the numbers a real user gets, and `docs/detection-notes.md` must say which machine any recorded figure came from.

## Milestones

- **M0** Skeleton: pyproject, Makefile, empty Adw window, models, store, `kiwi.manifest` + `install.sh`.
- **M1** Spike: pinned Camoufox in rootless Podman on Wayland, launched headful via `CAMOU_CONFIG_*` with a persistent profile and a frozen config, no Playwright. Verify the screen spoof actually overrides the real monitor, and that window geometry via `xulstore.json` holds.
- **M2** Network + DNS, and the validation the design rests on (run it on the test host, see above): gateway container owning the namespace with nftables default-drop (port novafox's proven ruleset), module endpoint reachability from a rootless namespace, forwarder with credentials, dnsmasq with DoT-through-forwarder for socks5 modules and `@iface` for routed ones, kill-switch tests.
- **M3** Fingerprint generator + validator for Windows 11; font import; per-profile font sets.
- **M4** Modules: contract, discovery, leasing. Build `kiwi-fox-myst` and `kiwi-fox-9proxy` from scratch, each standalone-runnable first and kiwi-fox-driven second; myst via TequilAPI with the verified-provider cache.
- **M5** GUI complete: CRUD, module panel, endpoint test, launch/stop, status.
- **M6** Leak suite, local neoprint run, self-check action.
- **M7** Newer Windows targets; optional tor module. (Chromium engine and a myst node pool stay in the backlog until asked for.)

## Open decisions (resolve in `docs/decisions.md`, with reasons)

- **Does 9proxy actually serve SOCKS5 on its local ports?** We standardise on SOCKS5 regardless; this only decides whether the module needs a front-end. Test on first contact.
- **Memory footprint of 244k `blocked_names` per profile.** dnscrypt-proxy loads the full list without complaint; what is unmeasured is RSS multiplied by concurrent profiles.
- **Whether unbound or AdGuard dnsproxy would serve better than dnscrypt-proxy.** Current reading: unbound is out — no DoH client and no SOCKS5 outbound; dnsproxy has the protocols but its SOCKS5 outbound is undocumented. dnscrypt-proxy is the only one with all three (DoH + SOCKS5 + blocklists) documented. Revisit only if it disappoints.
(Resolved 2026-10-03: `screen-spoofing` does override the real Wayland monitor, CSS media queries included — see "Headful on Wayland".)

## Backlog (not scoped — do not start unasked)

- **Timer precision** — whether `privacy.reduceTimerPrecision` with jitter earns the small tell it creates, given it only blunts the hardware-perf signal and cannot remove it.
- **Raw private key import** for Mysterium (needs a local V3 keystore builder and a new dependency).
- **A myst node pool** for concurrent myst-backed profiles; the descriptor's `slots` field already allows it without a contract change.
- **A Chromium engine.** Note it increases cross-linking exposure rather than reducing it.
- **Per-profile blocklists beyond the default** — now cheap, since the resolver is per profile.

## Working agreements

- Propose a short plan before any change that touches more than one module.
- Small commits; run `make lint test` before declaring something done.
- Never log proxy credentials, module credentials or full fingerprints above debug level.
- Prefer reusing measured, working configuration from `novafox` and `mystop` over writing new variants of the same thing. When you depart from them, say why in `docs/decisions.md`.
- Update this file when commands, layout or architecture decisions change.
