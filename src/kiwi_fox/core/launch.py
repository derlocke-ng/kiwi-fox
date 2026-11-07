"""Profile -> gateway + browser -> lifecycle.

The gateway container owns the network namespace; the browser joins it and has
no routing table of its own, so the kill switch is the absence of a route
rather than software that has to notice. Measured working rootless on this host
(novafox ANALYSIS.md §4).

The gateway is kiwi-proxy's: a profile's exit (store.sync_exit) is brought up
with `gateway.up`, and the browser joins `Gateway.name`. What stays here is the
browser half, and the rules a browser imposes on its exit.
"""

from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass, field
from pathlib import Path

from kiwi_proxy import endpoint, exits, gateway, podman, providers

from . import geometry, paths, store
from .engines import get_engine
from .engines.camoufox import fontconfig_xml
from .fingerprint import validate, validate_against
from .fingerprint.validator import Issue, errors
from .models import ExitInfo, Fingerprint, Profile

BROWSER_IMAGE = "kiwi-fox/browser:latest"
# Errors the network half can raise; launch turns every one into a LaunchError.
_NETWORK_ERRORS = (
    gateway.GatewayError,
    providers.ProviderError,
    endpoint.EndpointError,
    podman.PodmanError,
)


class LaunchError(RuntimeError):
    pass


@dataclass
class LaunchResult:
    profile: Profile
    gateway: str | None  # None: no proxy, the browser on this machine's connection
    browser: str
    exit_info: ExitInfo | None = None
    warnings: list[Issue] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# --------------------------------------------------------------------- prep
def runtime_dir(profile_id: str) -> Path:
    d = paths.runtime_dir() / profile_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_fontconfig(profile: Profile, fp: Fingerprint) -> Path:
    path = paths.profile_dir(profile.id) / "fonts.conf"
    path.write_text(fontconfig_xml(fp))
    return path


def browser_data_dir(profile: Profile) -> Path:
    return paths.profile_dir(profile.id) / "browser-data"


def write_user_js(
    profile: Profile,
    fp: Fingerprint,
    data_dir: Path | None = None,
    extra: dict[str, object] | None = None,
) -> Path:
    """Prefs reach the browser through user.js, not through the environment.

    `data_dir` and `extra` exist for the probe, which runs the same prefs in a
    throwaway directory.
    """
    from .engines.gecko import user_js

    engine = get_engine(profile.engine)
    path = (data_dir or browser_data_dir(profile)) / "user.js"
    path.parent.mkdir(parents=True, exist_ok=True)
    prefs = {**engine.prefs(fp, profile), **(extra or {})}  # type: ignore[attr-defined]
    path.write_text(user_js(prefs))
    return path


def write_user_chrome(profile: Profile, fp: Fingerprint) -> Path:
    """Restore a usable Firefox chrome over Camoufox's minimalistic one.

    Only needed while the engine still ships its minimalisticfox chrome.css. Once
    `kiwi-fox engine tweak chrome` has neutralised that, stock Firefox styling is
    already correct and pinning our own geometry on top would just be a different
    deviation.
    """
    from .engines.camoufox import USER_CHROME_CSS
    from .engines.fetch import chrome_css_is_minimal, target_dir

    path = paths.profile_dir(profile.id) / "browser-data" / "chrome" / "userChrome.css"
    path.parent.mkdir(parents=True, exist_ok=True)
    if chrome_css_is_minimal(target_dir(fp.engine_version)):
        path.write_text(USER_CHROME_CSS)
    else:
        path.write_text("/* engine chrome.css already neutralised; nothing to override */\n")
    return path


def install_langpack(profile: Profile, fp: Fingerprint, data_dir: Path | None = None) -> str | None:
    """Put the region's language pack into the browser's data directory, or take
    it out again for an English profile. Returns a note when the pack could not
    be fetched — the launch goes on, with English built-in texts.
    """
    from .engines import fetch
    from .fingerprint import windows11 as w11

    extensions = (data_dir or browser_data_dir(profile)) / "extensions"
    build = w11.firefox_build(fp.locale) if profile.language == "local" else "en-US"
    wanted = None if build == "en-US" else f"langpack-{build}@firefox.mozilla.org.xpi"
    if extensions.exists():
        for stale in extensions.glob("langpack-*@firefox.mozilla.org.xpi"):
            if stale.name != wanted:
                stale.unlink()
    if wanted is None:
        return None
    try:
        source = fetch.langpack(fp.engine_version, build)
    except fetch.RepairError as exc:
        return f"no {build} language pack, built-in page texts stay English ({exc})"
    target = extensions / wanted
    if not target.exists() or target.stat().st_size != source.stat().st_size:
        extensions.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    return None


def clear_stale_lock(profile: Profile) -> bool:
    """Remove a leftover profile lock from a hard-killed Firefox.

    Nothing else can be using it: the browser container is gone by the time this
    runs, and one container per profile is enforced above.
    """
    removed = False
    data = paths.profile_dir(profile.id) / "browser-data"
    for name in (".parentlock", "lock"):
        path = data / name
        if path.exists() or path.is_symlink():
            path.unlink(missing_ok=True)
            removed = True
    return removed


def reset_toolbar_layout(profile: Profile) -> bool:
    """Drop a mangled toolbar layout so Firefox rebuilds the default one.

    While the engine's chrome.css hid the close buttons, bookmark star and
    extensions button, Firefox's CustomizableUI treated them as unplaceable and
    relocated them — leaving `new-tab-button` sitting in the nav-bar next to the
    extensions button instead of beside the tabs. The layout persists in
    `browser.uiCustomization.state`, so neutralising the CSS is not enough on an
    existing profile; the stale placement has to go.
    """
    prefs = paths.profile_dir(profile.id) / "browser-data" / "prefs.js"
    if not prefs.exists():
        return False
    lines = prefs.read_text(errors="replace").splitlines(keepends=True)
    kept, dropped = [], False
    for line in lines:
        if "browser.uiCustomization.state" in line:
            # Only reset when the new-tab button has drifted out of the tab strip.
            tabs_section = line.split("TabsToolbar", 1)[-1].split("]", 1)[0]
            if "new-tab-button" not in tabs_section:
                dropped = True
                continue
        kept.append(line)
    if dropped:
        prefs.write_text("".join(kept))
    return dropped


# -------------------------------------------------------------------- specs
# kiwi-fox's own labels on a gateway it brings up, beside kiwi-proxy's. They say
# who asked first: the gateway is the exit's, shared by every profile and tool on
# it, so no profile id is on it. kiwi-pentesting discovers gateways by
# kiwi-proxy.role=gateway; app=kiwi-fox is its fallback.
GATEWAY_LABELS = {"app": "kiwi-fox", "kiwi-fox.role": "gateway"}


def gateway_labels() -> dict[str, str]:
    return dict(GATEWAY_LABELS)


def browser_spec(
    profile: Profile,
    fp: Fingerprint | None,
    gateway: str | None,
    exit_ip: str | None,
    resolv_conf: str | None = None,
):
    """`gateway` is the exit's gateway container, or None for a profile with no
    proxy. `resolv_conf` is the gateway's (Gateway.resolv_conf): the browser has
    its own mount namespace, so in resolver mode it mounts the file that points at
    the resolver inside the namespace. None in remote DNS mode, and with no proxy."""
    spec = get_engine(profile.engine).build_spec(profile, fp, gateway=gateway, exit_ip=exit_ip)
    if resolv_conf:
        spec.volumes.append((resolv_conf, "/etc/resolv.conf", "ro,z"))
    wayland = _wayland_mount()
    if wayland:
        src, dst = wayland
        runtime = str(Path(dst).parent)
        # Camoufox runs a Wayland proxy that binds its own socket inside
        # XDG_RUNTIME_DIR, so that directory has to be writable. Mounting only
        # the host socket leaves it read-only and the proxy dies with
        # "StartProxyServer(): bind() error: Permission denied".
        spec.tmpfs.append(runtime)
        spec.volumes.append((src, dst, "rw"))
        spec.env["XDG_RUNTIME_DIR"] = runtime
        spec.env["WAYLAND_DISPLAY"] = Path(dst).name
    return spec


def _wayland_mount() -> tuple[str, str] | None:
    rt = os.environ.get("XDG_RUNTIME_DIR")
    disp = os.environ.get("WAYLAND_DISPLAY")
    if not rt or not disp:
        return None
    src = Path(rt) / disp
    if not src.exists():
        return None
    # Same path inside, so the socket stays where the toolkit expects it.
    return str(src), f"/run/user/{os.getuid()}/{disp}"


# ------------------------------------------------------------------ network
def _network_error(exc: Exception, profile: Profile) -> LaunchError:
    msg = str(exc)
    module = None
    with contextlib.suppress(Exception):
        ex = store.exit_of(profile)
        module = ex.endpoint.module if ex else None
    old = paths.data_dir() / "modules" / (module or "")
    if isinstance(exc, providers.ProviderError) and module and old.is_dir():
        # Since 0.3.0 provider modules install into kiwi-proxy. One from before
        # still sits in kiwi-fox's old directory, where nothing looks any more.
        msg += (
            f"\n  ({old} is a kiwi-fox 0.2 copy of it; update kiwi-plugin-{module}, "
            "which now installs into kiwi-proxy)"
        )
    return LaunchError(msg)


def check_tor_browser_exit(profile: Profile) -> None:
    """Tor Browser exits only through the tor provider: its per-site circuits are
    the SOCKS credentials the forwarder passes through, and .onion resolves only
    at a Tor exit. A plain or account endpoint would quietly lose both, so it is
    refused — a browser rule, beside kiwi-proxy's own (passthrough needs a token)."""
    ex = exit_of(profile)
    try:
        store.check_tor_exit(ex)
    except store.StoreError as exc:
        raise LaunchError(str(exc)) from exc
    assert ex is not None
    try:
        auth = providers.manifest_of(ex.endpoint.module).auth
    except providers.ProviderError as exc:
        raise _network_error(exc, profile) from exc
    if auth != "isolation":
        raise LaunchError("the tor provider must use isolation auth for Tor Browser")


def exit_of(profile: Profile):
    """The kiwi-proxy exit the profile uses, or None for no proxy."""
    try:
        return store.exit_of(profile)
    except store.StoreError as exc:
        raise LaunchError(str(exc)) from exc


def measure_direct(timeout: float = 10) -> ExitInfo:
    """What the world sees from this machine's own connection — the exit of a
    profile with no proxy."""
    import urllib.request

    with urllib.request.urlopen(endpoint.DEFAULT_GEO_URL, timeout=timeout) as resp:  # noqa: S310
        text = resp.read().decode("utf-8", "replace")
    return endpoint.parse_geo(text)


def plan(profile: Profile) -> gateway.EndpointPlan:
    """Decide the upstream and, for a remote exit, measure it from the host, so
    the region is known before the window opens. A managed provider is brought
    up here; its exit sits on the providers bridge, out of the host's reach. With
    no proxy the machine's own connection is measured instead."""
    ex = exit_of(profile)
    if ex is None:
        notes = ["no proxy: this machine's own connection"]
        try:
            info = measure_direct()
        except Exception as exc:  # noqa: BLE001 - never block a launch on this
            info = None
            notes.append(f"could not measure this machine's exit: {exc}")
        return gateway.EndpointPlan("", 0, "pasta", info, notes)
    try:
        return gateway.plan(ex)
    except _NETWORK_ERRORS as exc:
        raise _network_error(exc, profile) from exc


def up(profile: Profile, *, measure: bool = False) -> gateway.Gateway:
    """Bring the exit's gateway up, or join the one already running: another
    profile on the same exit, a pentest tool, a `kiwi-proxy up` of it all share
    the namespace. The exit's password is kiwi-proxy's to look up.

    `measure` also measures the exit through the gateway. Off by default: the
    pre-flight already measured a remote exit, and for a provider exit (Tor) the
    round trip would delay every window."""
    ex = exit_of(profile)
    if ex is None:
        raise LaunchError(f"{profile.name} has no proxy; there is no gateway to bring up")
    try:
        return gateway.up(ex, labels=gateway_labels(), measure=measure)
    except _NETWORK_ERRORS as exc:
        raise _network_error(exc, profile) from exc


def release(profile: Profile, *, ignore: tuple[str, ...] = ()) -> bool:
    """Done with the exit's gateway: it goes unless something else is still inside
    it (other than `ignore`) — another profile's browser, a tool — or `kiwi-proxy
    up` holds it. Nothing to do for a profile with no proxy."""
    if not profile.exit:
        return False
    return gateway.release(profile.exit, ignore=ignore)


def resolv_conf(profile: Profile) -> str | None:
    """What a container joining the profile's gateway mounts at /etc/resolv.conf
    (None in remote DNS mode, and with no proxy), for a gateway this process did
    not bring up."""
    ex = exit_of(profile)
    if ex is None:
        return None
    path = gateway.write_resolv_conf(ex)
    return str(path) if path else None


def start_gateway(profile: Profile) -> tuple[str, ExitInfo | None]:
    """Bring up a profile's network namespace with no browser in it, for the
    probe. A gateway already up for the exit is joined, not replaced."""
    if not podman.available():
        raise LaunchError("podman not found")
    gw = up(profile)
    return gw.name, gw.info


def launch(profile: Profile, *, strict: bool = False, start_url: str | None = None) -> LaunchResult:
    if not podman.available():
        raise LaunchError("podman not found")
    engine = get_engine(profile.engine)
    # Only camoufox carries a fingerprint; the non-spoofing engines pass None
    # through every step below.
    fp = store.fingerprint_of(profile)
    if profile.engine == "torbrowser":
        # Before the pre-flight: a wrong exit is refused before anything is sent.
        check_tor_browser_exit(profile)

    pre = plan(profile)
    info, notes = pre.info, list(pre.notes)

    from . import gpu
    from .fingerprint.validator import check_network_prefs

    prefs = engine.prefs(fp, profile)  # type: ignore[attr-defined]
    try:
        engine_dir = engine.engine_dir(profile, fp)  # type: ignore[attr-defined]
    except RuntimeError as exc:  # none of that engine installed: say so, plainly
        raise LaunchError(str(exc)) from exc
    binary = engine.binary  # type: ignore[attr-defined]

    if profile.gpu_accel and gpu.measurement() is None and (engine_dir / binary).exists():
        # Once per host: the rendering prefs depend on whether a GPU is really
        # reachable, and guessing wrong either way costs — forced hardware with no
        # GPU crash-loops, software with one reads as a virtual machine. The probe
        # helper ships in the engine dir (camoufox's, or Firefox's own tarball).
        with contextlib.suppress(Exception):  # a failed measurement must not block a launch
            gpu.measure(engine_dir)

    issues: list[Issue] = []
    if profile.engine == "camoufox":
        assert fp is not None
        from .fingerprint.validator import check_webgl_mode, check_window_fits

        issues += validate(
            fp,
            engine_version=fp.engine_version,
            exit_country=info.country if info else None,
            prefs=prefs,
            allow_prefs={"webgl.disabled"} if profile.webgl == "off" else set(),
            direct=profile.exit is None,
        )
        issues += check_window_fits(fp)
        if profile.user_agent:
            from .fingerprint import edit

            issues += [
                Issue("warn", "ua.custom", f"custom user agent: {note}")
                for note in edit.check_user_agent(profile.user_agent, fp.engine_version)
            ]
        issues += check_webgl_mode(
            profile.webgl, profile.webgl_vendor, profile.webgl_renderer, profile.webgl_series
        )
        others = [
            fpo
            for p in store.list_profiles()
            if p.id != profile.id
            and p.engine == "camoufox"
            and (fpo := store.fingerprint_of(p)) is not None
        ]
        issues += validate_against(fp, others)
    else:
        # Non-spoofing engine: no fingerprint to check, but the leak prefs that
        # make the forwarder the only way out still have to be right (or, with
        # no proxy, no proxy configured at all).
        issues += check_network_prefs(prefs, direct=profile.exit is None)

    hard = errors(issues)
    if hard:
        raise LaunchError(
            "fingerprint is incoherent, refusing to launch:\n  " + "\n  ".join(str(i) for i in hard)
        )
    warnings = [i for i in issues if i.level == "warn"]
    if warnings and strict:
        raise LaunchError(
            "warnings present and --strict given:\n  " + "\n  ".join(str(i) for i in warnings)
        )

    if not (engine_dir / binary).exists():
        if profile.engine == "camoufox" and fp:
            hint = f"kiwi-fox engine fetch {fp.engine_version}"
        else:
            version = f" {profile.engine_version}" if profile.engine_version else ""
            hint = f"kiwi-fox engine fetch{version} --engine {profile.engine}"
        raise LaunchError(f"engine missing at {engine_dir}; run `{hint}`")

    write_user_js(profile, fp)
    if profile.engine == "camoufox":
        assert fp is not None
        write_fontconfig(profile, fp)
        write_user_chrome(profile, fp)
        if note := install_langpack(profile, fp):
            notes.append(note)
        reset_toolbar_layout(profile)
        geometry.prepare(profile, fp)

    gateway_name = resolv = None
    if profile.exit:
        gw = up(profile)
        gateway_name, resolv = gw.name, gw.resolv_conf
        notes += [n for n in gw.notes if n not in notes]

    clear_stale_lock(profile)
    br = browser_spec(profile, fp, gateway_name, info.ip if info else None, resolv)
    if start_url:
        br.args = [start_url]
    if "WAYLAND_DISPLAY" not in br.env:
        notes.append("no Wayland socket found; the browser window cannot open")
    try:
        podman.start(br)
    except podman.PodmanError as exc:
        release(profile, ignore=(br.name,))
        raise LaunchError(f"browser failed to start: {exc}") from exc

    if info:
        profile.last_exit = info
    store.touch(profile)
    return LaunchResult(profile, gateway_name, br.name, info, warnings, notes)


def stop(profile: Profile) -> None:
    """The window is closed: the browser goes, and the exit's gateway with it
    unless another user of the exit — another profile's browser, a pentest tool,
    `kiwi-proxy up` — remains."""
    if not podman.available():
        return
    browser = paths.browser_name(profile.id)
    podman.rm(browser)
    release(profile, ignore=(browser,))


def down(profile: Profile) -> None:
    """Deleting a profile: its browser goes. The exit is shared, so its gateway is
    only released, never pulled from under whoever else is inside; `kiwi-proxy
    down NAME` is the unconditional one."""
    stop(profile)


def running(profile: Profile) -> bool:
    return podman.is_running(paths.browser_name(profile.id))


def wait_and_teardown(profile: Profile) -> int:
    """Block until the browser exits, then tear the namespace down.

    Without this the gateway outlives the browser, holding a netns and a secret
    for an identity nobody is using.
    """
    code = podman.wait(paths.browser_name(profile.id))
    stop(profile)
    return code


def reap() -> list[str]:
    """Stop gateways whose browser is gone, then whatever kiwi-proxy finds unused
    or pointing at a drifted provider address. Safe to call at any time."""
    if not podman.available():
        return []
    cleaned = []
    for p in store.list_profiles():
        br = paths.browser_name(p.id)
        if podman.is_running(br):
            continue
        if not p.exit:
            podman.rm(br)  # a dead browser with no gateway to release
            continue
        if podman.is_running(paths.gateway_name(p.exit)):
            podman.rm(br)
            if release(p, ignore=(br,)):
                cleaned.append(p.name)
    # Whatever kiwi-proxy finds unused, named after its exit where there is one.
    names = {paths.gateway_name(ex.id): ex.name for ex in exits.list_exits()}
    cleaned += [names.get(name, name) for name in gateway.reap()]
    return cleaned
