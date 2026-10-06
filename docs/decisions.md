# Decisions

Why things are the way they are. Each entry is a decision that cost something to
reach, so that it is not silently undone later.

## Engine

**Pinned upstream Camoufox, launched headfully without Playwright.** Config reaches
the browser through chunked `CAMOU_CONFIG_*` environment variables read by the C++
patches at startup; Playwright is only an automation channel we do not want. An own
build was rejected for now: it means owning a multi-hour build and a rebase every
Firefox release.

**There is no `CAMOU_PREFS`.** Prefs go into the profile's `user.js`. An early draft
invented that variable from prose about the launcher and never checked the binary,
so no pref applied at all — Firefox ran with no proxy, tried to connect directly,
and the firewall correctly dropped it. Verify a mechanism against the binary.

**WebGL stays on.** A browser without WebGL is a louder tell than software
rendering and is one of the documented reasons the old pfox design was
identifiable. `webgl.force-enabled=true` is required because the release zip omits
`glxtest`. `webgl.disabled` is never set unless a profile explicitly opts in, and
then the validator warns.

**A profile reports a GPU series, not a card.** Firefox sanitises every renderer
into one of a handful of representative devices and returns that same string from
plain `getParameter(RENDERER)` and from the debug extension, so a card name with a
PCI id is something no Firefox can say. The series comes with its own limits,
extension list and shader precision, taken from real Windows machines; emitting the
strings alone left Mesa's limits standing under them.

**Only capability limits are pinned, never state.** Upstream's record is a dump of
a fresh context and the engine returns table values unconditionally, so applying it
whole makes the browser contradict what the page itself just set — a 64x64 canvas
reporting a 300x150 viewport. The one exception is four stencil masks whose initial
value differs by platform; see `fingerprint/webgl.py`.

**WebGPU stays off.** Camoufox has no WebGPU patch, so a live WebGPU reports the
container's real Mesa adapter while WebGL claims Direct3D — exactly the mismatch
neoprint checks for. Absent WebGPU is a far smaller deviation than a contradiction.

**The default series is the host's.** Not because another one would contradict
itself — the masked renderer is spoofed along with everything else — but because
the frame the GPU draws is the one thing no setting changes, so the claim may as
well match the hardware class behind it. Choosing another series is a setting, not
a risk the tool takes for you.

**Hardware rendering is measured, not inferred.** "The render node exists" was
taken to mean "the browser draws on the GPU", and on a hybrid NVIDIA laptop it drew
in software for every profile. The plan for reaching a GPU is made from sysfs —
which GPU the desktop runs on, which driver each node has, whether the host can
inject the NVIDIA driver — and then checked with the engine's own probe. The prefs
follow the measurement: forcing hardware with no GPU crash-loops, and software with
one reads as a virtual machine.

**The renderer string goes through Firefox's own prefs.** The engine's config table
is not a stable interface: 152 takes plain `RENDERER` from it and 156 deliberately
does not. `webgl.override-unmasked-renderer` is stock Firefox, takes the driver's
wording, and Firefox sanitises it itself for both values.

**Only keys the installed engine lists are sent.** The engine ships its schema;
upstream drops and adds keys between releases, and an engine that moved under us
must still launch the same profile.

**A profile can be edited.** A fingerprint is frozen so it does not drift by
accident, not so it cannot be changed on purpose. Every edit goes through one
module (`fingerprint/edit.py`) and the same validation as a launch.

**The probe runs beside the profile, never in it.** It measures a throwaway browser
with the profile's config in an empty directory. Measuring the real one meant
stopping the user's session and writing into its history.

## Network

**The gateway owns the network namespace; the browser joins it.** The kill switch is
then the absence of a route rather than software that has to notice. Measured
working rootless on this host.

**Credentials arrive as a podman secret.** Not container env (`podman inspect` shows
it) and not a bind-mounted 0600 file (the gateway runs as container-root, a subuid,
and cannot read a file owned by the host user).

**Every provider exposes SOCKS5 and nothing else.** Adapting is the module's job, so
the gateway, forwarder, firewall rule and DNS design stay single-shaped.

**A provider module is a plugin, discovered on disk, not code baked in here.** The
contract (`core/providers/`) lives in kiwi-fox because the exit side is becoming a
full SOCKS5/VPN tunnelling suite, but each provider — tor, vpn, 9proxy, mysterium —
ships in its own repository and installs under `modules_dir()`. kiwi-fox loads a
module's `provider.py` by file path, not by import name, so a module named `9proxy`
(not a legal Python identifier) still loads. See `docs/plugin-system.md`.

**A local provider meets the gateway on a bridge, never in its netns.** A provider
that runs its own container needs an unrestricted exit of its own, which the
gateway's default-drop would strand if they shared a namespace. So both attach to
one `kf-providers` bridge and the gateway permits exactly the provider's address on
it — the single-destination firewall rule is unchanged, only the address now points
at a container instead of a public proxy. The provider's bridge IP is re-resolved
every launch because a restart can change it, and a plain remote endpoint keeps
pasta and reaches its public address directly.

**No EDNS Client Subnet.** The resolver and the browser share one exit, so the
upstream already sees the right location.

## Fingerprint

**Vary what the adversary measures.** Two profiles with different font sets produced
an identical `stableId` because the variation was in CJK families that no probe list
contains, while every probed Windows family is mandatory and therefore shared.
Variation now also lands on open-licensed families that appear on real probe lists.

**…but be common before being different (0.1.3, supersedes the default above).**
Varying fonts and screen per profile made each profile rarer, and rare is what
tampering and virtual-machine detectors score. In use, profiles stripped by hand to
the Windows core fonts at 1920x1080 passed where the drawn ones did not. So a new
profile is the commonest machine — core fonts, 1080p, this machine's GPU group — and
variation is something you add on purpose (`--extra-fonts`, the editor). Two
profiles that share those values are two ordinary machines, so the validator no
longer warns about it; it still warns about a shared set of *optional* fonts,
which is rare enough to link.

**The window is real, so open a real window that fits.** Window sizes are not
spoofed. The engine resets every window to 1280x1040 at startup and, from 156,
resizes it to `window.outerWidth/outerHeight` if given. Those two keys are therefore
how the window is sized: to what the user left, else to Firefox's own first-window
rule on the claimed screen, never beyond what that screen holds. Writing the claimed
screen into `xulstore.json` (the earlier approach) did nothing except erase the
size the user had chosen.

**Stable per-profile offsets are not noise.** `canvas:seed` and `audio:seed` are
constant for a profile across every launch, which is a different machine rather than
randomisation. Per-call jitter is what noise detection catches.

**Never set rare prefs.** `webgl.disabled`, `dom.webaudio.enabled=false`,
`media.navigator.enabled=false`, `browser.display.use_document_fonts=0` are each
detectable by their absence and shrink the population to one.

**Offer cards, report groups.** People think in cards ("my 4060"), Firefox reports
groups ("GTX 980, or similar"). A list of six group names was correct and read as
broken: the user's card was not on it and something older was shown instead. So the
choice is a card, and every place that shows it also shows the text Firefox turns it
into and says that Firefox does the turning. Naming the exact model is possible in
one field and is a switch, off by default, because only a reconfigured Firefox does
it.

**A profile is a localized Firefox, not an English one with a foreign header.**
Stock Firefox derives `Accept-Language`, `navigator.languages`, the `Intl` locale and
its own strings from one build language; setting them one by one produced a
combination no build has. Now the region decides the build, Mozilla's language pack
makes the browser that build, and Firefox derives the rest. "English Firefox abroad"
is the second option because it is also a thing real people run.

## Host integration

**The browser container runs with `label=disable`.** The Wayland socket cannot be
relabelled without changing the compositor's own socket label. The real boundary is
the netns with no route, zero capabilities beyond `SYS_CHROOT`, and
`no-new-privileges`.

**`CAP_SYS_CHROOT` is granted to the browser.** Firefox's content sandbox chroots
each content process; without it the Chroot Helper segfaults and every tab dies.
Granting one narrow capability is a better trade than disabling the sandbox.

**Engine tweaks edit data, never code we compile.** `omni.ja` is a zip,
`chrome.css` and `policies.json` are plain files, and the C++ spoofing lives in
`libxul` where we do not touch it. Every tweak keeps a `.orig` backup and carries
its own fingerprint assessment.
