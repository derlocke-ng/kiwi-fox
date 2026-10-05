"""Camoufox, launched headfully and directly — no Playwright, no juggler.

Config reaches the browser only through chunked `CAMOU_CONFIG_*` environment
variables, read by the C++ patches at startup; prefs go through the profile's
user.js, because there is no environment variable for them.
Every key used here comes from `settings/properties.json` at the pinned tag,
never from memory:
  https://github.com/daijro/camoufox/blob/v152.0.4-beta.30/settings/properties.json
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from .. import desktop, gpu, paths
from ..fingerprint import webgl
from ..fingerprint import windows11 as w11
from ..models import ContainerSpec, Fingerprint, Profile

# The launcher splits config across numbered vars; 32767 is the per-variable
# limit on everything that is not Windows.
CHUNK = 32767

ENGINE_MOUNT = "/opt/camoufox"
ADDONS_DIR = "/opt/kf-addons"
PROFILE_MOUNT = "/profile"
FONTCONFIG_MOUNT = "/etc/kf-fonts.conf"

# Gateway loopback services (same netns as the browser).
FORWARDER_HOST = "127.0.0.1"
FORWARDER_PORT = 1080
RESOLVER_HOST = "127.0.0.2"


def accelerated(profile: Profile) -> bool:
    """Hardware rendering is wanted *and* this host can deliver it — by
    measurement where there is one, by plan otherwise (see core/gpu.py)."""
    return profile.gpu_accel and gpu.accelerated()


def is_dark(profile: Profile) -> bool | None:
    """Dark chrome and dark pages? None leaves Firefox to its own default."""
    if profile.appearance == "host":
        return desktop.prefers_dark()
    return profile.appearance == "dark"


def engine_keys(engine_dir: Path) -> set[str] | None:
    """The config keys this engine build knows, from the schema it ships.

    Upstream adds and drops keys between releases — 156 dropped battery:*,
    canvas:seed and fonts:spacing_seed among others — so the same fingerprint is
    emitted differently for different engines. None when the build ships no
    schema (152 and earlier), where everything emitted here is known to exist.
    """
    schema = engine_dir / "properties.json"
    try:
        return {entry["property"] for entry in json.loads(schema.read_text())}
    except (OSError, ValueError, KeyError, TypeError):
        return None


class Camoufox:
    name = "camoufox"

    # ---------------------------------------------------------------- prefs
    def prefs(self, fp: Fingerprint, profile: Profile) -> dict[str, object]:
        remote_dns = profile.dns.mode == "remote"
        accel = accelerated(profile)
        dark = is_dark(profile)
        return {
            # Proxy: everything through the gateway's forwarder, never direct.
            "network.proxy.type": 1,
            "network.proxy.socks": FORWARDER_HOST,
            "network.proxy.socks_port": FORWARDER_PORT,
            "network.proxy.socks_version": 5,
            "network.proxy.socks_remote_dns": remote_dns,
            # Defaults to true, which permits a direct fallback. Never.
            "network.proxy.failover_direct": False,
            "network.proxy.allow_bypass": False,
            # Firefox must not run its own DoH and bypass the gateway resolver.
            "network.trr.mode": 5,
            # No speculative traffic outside a user action.
            "network.dns.disablePrefetch": True,
            "network.prefetch-next": False,
            "network.predictor.enabled": False,
            "network.http.speculative-parallel-limit": 0,
            "browser.send_pings": False,
            "network.captive-portal-service.enabled": False,
            # Claimed-Windows coherence: WebGPU on Linux is already absent; pin it
            # so a future release cannot turn it on and contradict WebGL.
            "dom.webgpu.enabled": False,
            # Camoufox spoofs in C++. These would add their own tells.
            "privacy.resistFingerprinting": False,
            "privacy.fingerprintingProtection": False,
            # Dates and numbers follow the operating system's region, as they do
            # for a Firefox whose own language matches it. This engine's UI is
            # always English, so without this a Dutch profile formatted like the
            # US. Off for "english": an English Firefox abroad really does that.
            "intl.regional_prefs.use_os_locales": profile.language == "local",
            # Which interface language to run. The region's own, when its language
            # pack is in the profile (launch.install_langpack); Firefox falls back
            # to English by itself when it is not.
            "intl.locale.requested": w11.firefox_build(fp.locale)
            if profile.language == "local"
            else "en-US",
            # Rendering. With the render node passed through we want real
            # hardware GL: software-rendering performance against a claimed
            # discrete GPU is one of our documented residual tells, so
            # acceleration removes a tell. Without a render node the separate
            # GPU process crash-loops, so fall back to in-process software
            # WebRender. Neither is web-observable: the WebGL strings come from
            # the engine config either way.
            "gfx.webrender.all": True,
            "gfx.webrender.software": not accel,
            "layers.gpu-process.enabled": accel,
            "media.gpu-process-decoder": accel,
            # Comfort only — none of these are observable by a site.
            "browser.startup.page": 3,
            "browser.sessionstore.resume_from_crash": True,
            # Our userChrome.css undoes Camoufox's minimalistic chrome. The cfg
            # already defaults this on; set it explicitly so it cannot drift.
            "toolkit.legacyUserProfileCustomizations.stylesheets": True,
            # Overlay scrollbars, which take no layout width: what Firefox uses on
            # Windows 11 by default (WindowsUIUtils::ComputeOverlayScrollbars). An
            # earlier pin to "17px like Windows" was right only for Windows 10 and
            # came out as 12, which is neither.
            "widget.non-native-theme.enabled": True,
            "widget.gtk.overlay-scrollbars.enabled": True,
            # camoufox.cfg sets "never"; "newtab" is the Firefox default.
            "browser.toolbars.bookmarks.visibility": "newtab",
            # The engine ships a customised toolbar layout — its dirtyAreaCache
            # marks TabsToolbar as modified — which leaves the new-tab "+" in the
            # nav-bar next to the extensions button instead of beside the tabs.
            # Pin Firefox's stock placement. Trade-off: toolbar customisation does
            # not persist across launches, which for a reproducible identity is
            # arguably correct anyway.
            "browser.uiCustomization.state": '{"placements":{"widget-overflow-fixed-list":[],"unified-extensions-area":[],"nav-bar":["back-button","forward-button","stop-reload-button","customizableui-special-spring1","urlbar-container","customizableui-special-spring2","downloads-button","fxa-toolbar-menu-button","unified-extensions-button"],"toolbar-menubar":["menubar-items"],"TabsToolbar":["firefox-view-button","tabbrowser-tabs","new-tab-button","alltabs-button"],"vertical-tabs":[],"PersonalToolbar":["personal-bookmarks"]},"currentVersion":24,"newElementCount":2}',
            # Camoufox strips the bundled search engines, so the address bar does
            # not search. A search WebExtension supplies one; these let it load
            # and let typed terms become searches.
            "keyword.enabled": True,
            "browser.search.suggest.enabled": False,
            "browser.urlbar.suggest.searches": False,
            "extensions.autoDisableScopes": 0,
            "extensions.enabledScopes": 15,
            "xpinstall.signatures.required": False,
            # Try for real hardware GL. The release zip omits glxtest, so Firefox
            # cannot probe the GPU and falls back to software unless pushed.
            "gfx.webrender.compositor": accel,
            "gfx.x11-egl.force-enabled": accel,
            # VA-API exists only on the Mesa paths; forcing it where the host's
            # NVIDIA driver is in use would point the decoder at nothing.
            "media.hardware-video-decoding.force-enabled": accel
            and gpu.plan().kind.startswith("mesa"),
            # Light or dark, for the chrome and for prefers-color-scheme alike —
            # one setting, as on a real machine. Left alone when unknown.
            **({} if dark is None else {"ui.systemUsesDarkTheme": int(dark)}),
            # WebGL must work unless the profile turns it off. Without glxtest
            # Firefox cannot probe the GPU, concludes nothing is usable and
            # disables WebGL entirely; force-enabled bypasses that verdict.
            # Deliberately NOT setting webgl.disabled when WebGL is on: False is
            # already the default, and the validator rejects the key outright
            # because touching it at all is how pfox made itself identifiable.
            **(
                {"webgl.disabled": True}
                if profile.webgl == "off"
                else {
                    "webgl.force-enabled": True,
                    # Every series offered has WebGL 2 on Windows.
                    "webgl.enable-webgl2": True,
                    "webgl.out-of-process": False,
                    # The renderer strings, through Firefox's own prefs as well
                    # as the engine config: see webgl.driver_string.
                    **webgl_prefs(fp, profile),
                }
            ),
        }

    # --------------------------------------------------------------- config
    def config(self, fp: Fingerprint, profile: Profile, exit_ip: str | None) -> dict[str, object]:
        s = fp.screen
        ua = profile.user_agent or fp.ua
        cfg: dict[str, object] = {
            "navigator.userAgent": ua,
            "navigator.platform": fp.platform,
            "navigator.oscpu": fp.oscpu,
            "navigator.hardwareConcurrency": fp.hardware_concurrency,
            # navigator.language(s) and the Accept-Language header are not set
            # here: the engine is handed the list (locale:all) and Firefox derives
            # all three itself, in its own format. navigator.maxTouchPoints is not
            # set either — no patch read it on 152.
            "navigator.buildID": fp.build_id,
            "headers.User-Agent": ua,
            "screen.width": s.width,
            "screen.height": s.height,
            "screen.availWidth": s.avail_width,
            "screen.availHeight": s.avail_height,
            "screen.availLeft": s.avail_left,
            "screen.availTop": s.avail_top,
            "screen.colorDepth": s.color_depth,
            "screen.pixelDepth": s.pixel_depth,
            # Deliberately NOT spoofing window.outer*/inner*/screenX/screenY.
            # Spoofing them while the real window is a different size makes
            # Firefox letterbox the content: the page renders at the claimed
            # inner size and the remainder is painted grey — the "huge grey
            # inverted L". Instead the real window is sized to the profile's
            # geometry (see seed_xulstore) so the true values are already both
            # correct and consistent with the spoofed screen.
            "window.devicePixelRatio": s.device_pixel_ratio,
            "timezone": fp.timezone,
            "locale:language": fp.locale.split("-")[0],
            "locale:region": fp.locale.split("-")[-1],
            # navigator.languages came back as a single entry until this was set:
            # the engine derives the list from locale:*, not from
            # navigator.languages, and a one-entry list is unusual in itself.
            "locale:all": ",".join(
                w11.browser_languages(fp.locale, fp.languages, profile.language)
            ),
            "fonts": fp.fonts,
            "fonts:spacing_seed": fp.font_spacing_seed,
            # Inert at the pinned tag (measured: two seeds and no seed give the
            # same canvas once Firefox's own randomisation is off). What a page
            # actually gets is stock Firefox's default protection, which perturbs
            # canvas readback differently every session — so canvas neither links
            # two sessions of one profile nor tells two profiles apart. Left in
            # for an engine build that honours it.
            "canvas:seed": fp.canvas_seed,
            "audio:seed": fp.audio.seed,
            "AudioContext:sampleRate": fp.audio.sample_rate,
            "AudioContext:maxChannelCount": fp.audio.max_channel_count,
            "AudioContext:outputLatency": fp.audio.output_latency,
            # One GPU series: both renderer strings, its limits, its extension
            # list and its shader precision, or nothing at all. See Profile.webgl.
            **webgl_config(fp, profile),
            "pdfViewerEnabled": True,
            **_media_devices(fp),
            **_voices(fp),
            # Camoufox draws a virtual cursor highlight by default — the orange
            # halo following the pointer. It exists to visualise automated mouse
            # movement, which we never use.
            "showcursor": False,
            "humanize": False,
            # No search-provider addon: `kiwi-fox engine tweak search` restores the
            # 154 packaged engines, so shipping our own would only add a profile
            # deviation for nothing. The image still carries it as a fallback.
        }
        if exit_ip:
            # Mullvad's SOCKS5 exits report IPv6 — measured — so the family has
            # to decide the key. Writing a v6 address into webrtc:ipv4 would be
            # an obvious contradiction.
            cfg[_webrtc_key(exit_ip)] = exit_ip
        # A desktop's real (battery-less) values are already correct: charging,
        # full, infinite. Only a laptop needs overriding, and JSON cannot carry
        # Infinity, so non-finite values are never emitted.
        if fp.form_factor == "laptop":
            cfg["battery:charging"] = fp.battery.charging
            cfg["battery:level"] = fp.battery.level
            for key, val in (
                ("battery:chargingTime", fp.battery.charging_time),
                ("battery:dischargingTime", fp.battery.discharging_time),
            ):
                if val is not None:  # None is Infinity, which JSON cannot carry
                    cfg[key] = val
        return cfg

    # ----------------------------------------------------------------- env
    def env(self, fp: Fingerprint, profile: Profile, exit_ip: str | None) -> dict[str, str]:
        env = {
            "TZ": fp.timezone,
            "LANG": f"{fp.locale.replace('-', '_')}.UTF-8",
            "MOZ_ENABLE_WAYLAND": "1",
            **({"MOZ_WEBRENDER": "1"} if accelerated(profile) else {}),
            # GTK draws the window frame, menus and dialogs; without this they
            # stay light around a dark browser.
            **({"GTK_THEME": "Adwaita:dark"} if is_dark(profile) else {}),
            "FONTCONFIG_FILE": FONTCONFIG_MOUNT,
            "KF_PROFILE_DIR": PROFILE_MOUNT,
            "KF_ENGINE_DIR": ENGINE_MOUNT,
            "KF_WINDOW_SIZE": f"{fp.window.inner_width}x{fp.window.inner_height}",
        }
        # Only CAMOU_CONFIG_* exists. There is no CAMOU_PREFS env var — verified
        # against the engine binary, which contains no such string — so prefs go
        # into the profile's user.js instead. Getting this wrong meant Firefox
        # ran with no proxy at all, tried to connect directly, and the firewall
        # correctly dropped it: every page timed out while DNS looked perfect.
        config = self.config(fp, profile, exit_ip)
        known = engine_keys(paths.engines_dir() / f"camoufox-{fp.engine_version}")
        if known is not None:
            config = {key: value for key, value in config.items() if key in known}
        env.update(chunk_env("CAMOU_CONFIG", config))
        return env

    # ---------------------------------------------------------------- spec
    def build_spec(
        self, profile: Profile, fp: Fingerprint, *, gateway: str, exit_ip: str | None
    ) -> ContainerSpec:
        pdir = paths.profile_dir(profile.id)
        engine = paths.engines_dir() / f"camoufox-{fp.engine_version}"
        plan = gpu.plan() if accelerated(profile) else None
        env = self.env(fp, profile, exit_ip)
        if plan:
            env.update(plan.env)
        return ContainerSpec(
            name=paths.browser_name(profile.id),
            image="kiwi-fox/browser:latest",
            network=f"container:{gateway}",
            env=env,
            volumes=[
                # ",z" is shared relabelling: one engine copy serves every
                # profile. ",Z" would relabel it private to one container and
                # break the others.
                (str(engine), ENGINE_MOUNT, "ro,z"),
                (str(pdir / "browser-data"), PROFILE_MOUNT, "rw,z"),
                (str(pdir / "downloads"), "/downloads", "rw,z"),
                (str(pdir / "fonts.conf"), FONTCONFIG_MOUNT, "ro,z"),
            ],
            devices=list(plan.devices) if plan else [],
            cap_drop=["all"],
            # SYS_CHROOT is granted *to strengthen* isolation, not weaken it:
            # Firefox's content sandbox chroots each content process, and without
            # the capability its Chroot Helper segfaults in libmozsandbox.so and
            # every tab dies. Measured: with it, 4 content processes and an RDD
            # process run with zero segfaults; without it, 8 crashes and one
            # surviving tab. Disabling the content sandbox instead would "work"
            # but would throw away the browser's main defence against a hostile
            # page, which is a far worse trade than one narrow capability.
            cap_add=["SYS_CHROOT"],
            # The Wayland socket cannot be relabelled: ",z" would change the
            # label of the host compositor's own socket. Disabling SELinux
            # confinement for this one container is the standard trade desktop
            # container tooling makes; the real boundary here is the netns with
            # no route, zero capabilities and no-new-privileges.
            security_opt=["no-new-privileges", "label=disable"],
            userns="keep-id",
            labels={"app": "kiwi-fox", "kiwi-fox.profile": profile.id},
        )


# Camoufox ships a minimalisticfox chrome.css that is tuned for watching an
# automated browser, not for using one: it hides tab close buttons, the bookmark
# star, the extensions button, the bookmarks toolbar and the window controls,
# shrinks tabs to 25px, and sets pointer-events:none on .tab-content. We put it
# back. camoufox.cfg already enables
# toolkit.legacyUserProfileCustomizations.stylesheets, so a per-profile
# chrome/userChrome.css is loaded.
USER_CHROME_CSS = """/* generated by kiwi-fox — restores a usable Firefox UI */

/* Camoufox hides these to keep the chrome minimal. Put them back. */
.tab-close-button,
#star-button-box,
#unified-extensions-button,
#tracking-protection-icon-container,
#urlbar-go-button,
#tab-notification-deck,
toolbar#nav-bar > .titlebar-buttonbox-container,
toolbar#nav-bar > .titlebar-spacer,
#PersonalToolbar {
  display: revert !important;
}

/* Tabs must be clickable where the close button lives. */
.tab-content {
  pointer-events: auto !important;
}

/* Stock-ish geometry instead of the 25px/30px minimalistic clamps. */
:root {
  --tab-min-height: 36px !important;
  --tab-max-height: 36px !important;
  --urlbar-height: 32px !important;
  --urlbar-toolbar-height: 40px !important;
  --urlbar-container-height: 40px !important;
}

.tabbrowser-tab,
.tab-background {
  max-height: 36px !important;
}

#navigator-toolbox :-moz-any(#nav-bar) {
  min-height: 40px !important;
  max-height: none !important;
}

#urlbar-container {
  --urlbar-container-height: 40px !important;
}

#urlbar {
  --urlbar-height: 32px !important;
  --urlbar-toolbar-height: 40px !important;
}

/* Let the tab strip behave as a tab strip, not a window-drag handle. */
#TabsToolbar {
  -moz-window-dragging: no-drag !important;
}

.tabbrowser-tab {
  -moz-window-dragging: no-drag !important;
}
"""


def user_js(prefs: dict[str, object]) -> str:
    """Render prefs as a Firefox user.js.

    user.js is re-applied on every startup and overrides prefs.js, so it is the
    right place for settings that must never drift.
    """
    lines = [
        "// generated by kiwi-fox — do not edit; rewritten on every launch",
    ]
    for key in sorted(prefs):
        # json.dumps gives exactly the literals Firefox wants: true/false for
        # booleans, bare numbers, and properly escaped quoted strings.
        lines.append(f"user_pref({json.dumps(key)}, {json.dumps(prefs[key])});")
    return "\n".join(lines) + "\n"


def webgl_report(fp: Fingerprint, profile: Profile) -> webgl.Report | None:
    """What this profile tells pages about the graphics card; None: nothing."""
    return webgl.report(
        profile.webgl,
        stored_renderer=fp.webgl.renderer,
        series_key=profile.webgl_series,
        card=profile.webgl_card,
        exact=profile.webgl_exact,
        custom_vendor=profile.webgl_vendor,
        custom_renderer=profile.webgl_renderer,
    )


def webgl_series(fp: Fingerprint, profile: Profile) -> webgl.Series | None:
    told = webgl_report(fp, profile)
    return told.series if told else None


def webgl_config(fp: Fingerprint, profile: Profile) -> dict[str, object]:
    told = webgl_report(fp, profile)
    if told is None:
        return {}
    return webgl.engine_config(
        told.series, vendor=told.vendor, renderer=told.unmasked, masked=told.masked
    )


def webgl_prefs(fp: Fingerprint, profile: Profile) -> dict[str, object]:
    told = webgl_report(fp, profile)
    if told is None:
        return {}
    return webgl.firefox_prefs(told.series, vendor=told.vendor, renderer=told.unmasked)


def _media_devices(fp: Fingerprint) -> dict[str, object]:
    micros = fp.media_devices.get("micros", 0)
    webcams = fp.media_devices.get("webcams", 0)
    # The engine inserts cameras at index 1 of the device list, which is past the
    # end when no microphone was inserted first: the content process dies with
    # signal 11 the moment a page calls enumerateDevices(). Reproduced on the test
    # VM (micros=0, webcams=1: dead twice out of twice; every other combination
    # fine). Profiles generated before this was known may carry that combination,
    # so it is repaired here rather than trusted.
    if webcams and not micros:
        micros = 1
    return {
        "mediaDevices:enabled": True,
        "mediaDevices:micros": micros,
        "mediaDevices:webcams": webcams,
        "mediaDevices:speakers": fp.media_devices.get("speakers", 1),
    }


def _voices(fp: Fingerprint) -> dict[str, object]:
    """Speech voices in the shape MaskConfig::MVoices() requires.

    Without them the list is empty — the container has no speech backend — and a
    Windows machine with no voices at all does not exist. The URI is built the way
    SapiService.cpp builds it: "urn:moz-tts:sapi:<description>?<locale>".
    """
    names = [w11.VOICE_ALIASES.get(name, name) for name in fp.voices]
    langs = [w11.voice_language(name, fp.locale) for name in names]
    # Windows marks one system default: the voice of the display language.
    default = next((i for i, lang in enumerate(langs) if lang == fp.locale), 0)
    return {
        "voices": [
            {
                "lang": lang,
                "name": name,
                "voiceUri": f"urn:moz-tts:sapi:{name}?{lang}",
                "isDefault": i == default,
                "isLocalService": True,
            }
            for i, (name, lang) in enumerate(zip(names, langs, strict=True))
        ],
        # The host's own backend must never add to this list.
        "voices:blockIfNotDefined": True,
        # A fake voice cannot speak; without this speak() raises an error event,
        # which no real voice does.
        "voices:fakeCompletion": True,
    }


def _webrtc_key(ip: str) -> str:
    import ipaddress

    try:
        return "webrtc:ipv6" if ipaddress.ip_address(ip).version == 6 else "webrtc:ipv4"
    except ValueError:
        return "webrtc:ipv4"


def chunk_env(prefix: str, payload: dict[str, object]) -> dict[str, str]:
    """Serialise to JSON and split across `<prefix>_1..N`, as the launcher does."""
    blob = json.dumps(payload, separators=(",", ":"), allow_nan=False)
    return {
        f"{prefix}_{i + 1}": blob[i * CHUNK : (i + 1) * CHUNK]
        for i in range(max(1, math.ceil(len(blob) / CHUNK)))
    }


def fontconfig_xml(fp: Fingerprint, engine_dir: str = ENGINE_MOUNT) -> str:
    """Expose exactly this profile's font files and nothing else.

    Built on top of the engine's own Windows fonts.conf (Tor-Browser derived,
    which already makes the bundled fonts the only system fonts), then rejecting
    the bundled files this profile does not have.
    """
    from ..fingerprint import fonts as F

    keep = set(fp.font_files) | {F.EMOJI_FALLBACK}
    every = set(F.files_for(F.all_core_families() + F.all_optional_families()))
    reject = sorted(every - keep)
    lines = [
        '<?xml version="1.0"?>',
        '<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">',
        "<!-- generated by kiwi-fox; one font set per profile -->",
        "<fontconfig>",
        f'  <include ignore_missing="no">{engine_dir}/fontconfig/windows/fonts.conf</include>',
    ]
    # Only this profile's third-party directories are added, so the families a
    # fingerprinter probes for genuinely differ between profiles.
    for directory in F.third_party_dirs(fp.fonts):
        lines.append(f"  <dir>{directory}</dir>")
    lines += [
        "  <selectfont>",
        "    <rejectfont>",
    ]
    lines += [f"      <glob>{engine_dir}/fonts/windows/{f}</glob>" for f in reject]
    lines += ["    </rejectfont>", "  </selectfont>", "</fontconfig>", ""]
    return "\n".join(lines)
