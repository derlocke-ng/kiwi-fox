# Decisions

Why things are the way they are. Each entry is a decision that cost something to
reach, so that it is not silently undone later.

## Engine

**The engine is a profile field, not a fingerprint field.** A profile runs one of
`camoufox`, `firefox` or `torbrowser`, chosen at creation and fixed thereafter
(browser-data is one Firefox profile directory, so switching would downgrade it or
carry one identity's state into another). Only `camoufox` is a spoofing engine and
only it has a `fingerprint.json`; `firefox` shows this machine's own values and
`torbrowser` its own uniform crowd, so for them a frozen Windows identity would be
fiction. Engine selection used to live on the fingerprint, which a profile without
one cannot carry; it now lives on `Profile.engine`, and `store.create` refuses a
camoufox profile with no fingerprint or a non-spoofing profile with one. The
Gecko-generic pieces — the proxy/DNS/leak prefs, the `user.js` renderer, the
container skeleton — live in `engines/gecko.py`; Camoufox layers its Windows
spoofing on top, and the validator checks the leak prefs for every engine but the
Windows-coherence prefs for Camoufox alone.

**Stock Firefox is Mozilla's own build, verified and un-spoofed.** The firefox
engine exists for when uniqueness is not what is wanted: it shows this machine's
real values — a coherent, ordinary Firefox — rather than a disguise, so it sets
no fingerprint and no `CAMOU_CONFIG`. Only what the container and the proxy
require is applied through `user.js`: the proxy and leak prevention shared with
every engine, WebRTC candidates confined (`ice.no_host`) so a page cannot read
the host address around the proxy, hardware rendering, and the appearance. The
tarball is fetched from archive.mozilla.org and verified the way Mozilla
documents — the detached signature over `SHA512SUMS` against the pinned release
key `14F2 6682 … D98F 0353`, then the tarball's SHA-512 — because the engine is
mounted read-only and pinned, so a silent swap would otherwise go unnoticed.
Updates are turned off through the bundle's `distribution/policies.json`, written
host-side at fetch time. Firefox renders with its own font set under a dedicated
`FONTCONFIG_FILE`, kept off Camoufox's path so Camoufox's per-profile fonts are
unchanged.

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

The proxy engine — the gateway that owns the namespace, the credential forwarder,
the resolver, the provider modules — is
[kiwi-proxy](https://github.com/derlocke-ng/kiwi-proxy) since 0.3.0, and so are the
decisions behind it: its `docs/decisions.md` (the gateway, credentials as podman
secrets, SOCKS5-only providers, the providers bridge, injection versus
passthrough) and `docs/consumers.md` (what a consumer can rely on). What is left
here is how kiwi-fox uses it.

**A profile references a proxy; the proxy is kiwi-proxy's.** An exit in kiwi-proxy
is a proxy the user defined once — a SOCKS5 they were given, or a provider module
— with its DNS mode, blocklists and credentials; `profile.exit` is its id. Several
profiles may use one, and so may kiwi-pentesting's tools and applications on the
host: they share its gateway, one namespace with one exit IP and one set of Tor
circuits. That was chosen (0.4.0) over a gateway per profile: fewer containers,
one place a proxy is defined, and identities that must not share an exit simply
take different proxies. kiwi-fox never writes an exit's settings — `kiwi-proxy
set` and kiwi-proxy's editor do (the GUI opens that editor) — and reads them at
launch, so an edit on either side meets. kiwi-fox makes no exits at all (0.6.0;
0.4 and 0.5 had shortcuts that did): the proxy side will grow, and it grows in
kiwi-proxy. An endpoint given to `kiwi-fox new` is answered with the `kiwi-proxy
add` to run, and the GUI's picker opens the Kiwi Proxy app. Exits that 0.3
registered under a profile's id (`owner="kiwi-fox"`) still go with their last
profile; an exit the user made stays.

**Profiles from before 0.4 keep their exit id.** 0.3 registered one exit per
profile under the profile's own id; `store.load` turns that into the reference
the first time it sees such a profile (creating the exit if 0.3 never did), so
the gateway is still `kf-gw-<id[:12]>` and the Tor token `kf-<id[:16]>` — the
name kiwi-pentesting looks for, the same circuit. The password moves from
kiwi-fox's keyring into kiwi-proxy's store, where every exit's lives. A gateway
kiwi-fox brings up carries `app=kiwi-fox` and `kiwi-fox.role=gateway` and no
profile id: it is the proxy's, not a profile's.

**No proxy is a choice, said explicitly.** `--no-proxy` (the GUI's first entry)
runs the browser on this machine's own connection with no proxy configured at all
(`network.proxy.type=0`, checked like the proxied prefs are), in a network
namespace of its own, with no gateway and nothing sealed. It is never the CLI's
default, so a typo cannot unproxy a profile, and the GUI prefers an existing
proxy. Tor Browser cannot run that way. `selfcheck` needs a proxy too: the probe
page is served from the gateway.

**Closing the window releases the gateway; nothing kiwi-fox does removes it.**
Other profiles, a pentest tool or a `kiwi-proxy up` may be inside the namespace,
and removing the gateway would cut them off; it goes with the last member, or with
`kiwi-proxy down`. Deleting a profile releases too.

**The fingerprint is checked against the host-side pre-flight only.** For a remote
exit kiwi-proxy measures it from the host before anything starts, exactly as
before; with no proxy the machine's own connection is measured the same way. A
provider exit (Tor) cannot be reached from the host, and measuring it through the
gateway would add a round trip to every launch and change what `--strict`
refuses, so the launch does not ask for it.

**Tor Browser needs a tor proxy that passes SOCKS auth through.** Tor Browser puts
a per-site username/password on every request to key a circuit per site and
offers no other SOCKS method. kiwi-proxy 0.3 makes exits on the tor module
`passthrough` by default — a member without SOCKS credentials still gets the
exit's token — so a Camoufox profile and a Tor Browser profile can share one.
kiwi-fox refuses a Tor Browser profile on any other exit, or none, at creation
and at launch, before any pre-flight is sent, and names the `kiwi-proxy set
--socks-auth passthrough` that fixes an exit switched back. Its own prefs force
remote DNS whatever the exit's resolver does, so `.onion` resolves at Tor, and the
forwarder still refuses the exit's blocklist names. That is a browser rule, so it
lives here; kiwi-proxy adds its own (passthrough needs a token to put in front).

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
