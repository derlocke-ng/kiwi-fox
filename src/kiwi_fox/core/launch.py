"""Profile -> gateway + container + browser -> lifecycle.

The gateway container owns the network namespace; the browser joins it and has
no routing table of its own, so the kill switch is the absence of a route
rather than software that has to notice. Measured working rootless on this host
(novafox ANALYSIS.md §4).

The gateway is kiwi-proxy's: a profile's exit (store.sync_exit) is brought up
with `gateway.up`, and the browser joins `Gateway.name`. What stays here is the
browser half, and the rules a browser imposes on its exit.

A profile's container and its browser are two things (the window's two buttons):
the container's process 1 is the launcher (containers/browser/entrypoint.sh,
mounted over the image's copy), which starts the browser, quits it on a signal,
and ends with it unless told to keep running. A watcher outside the container
(:func:`watch`, a transient user unit) snapshots the profile when its browser
closes and lets go of the exit when the container ends — whoever started it: the
window, the command line or the app grid.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from kiwi_proxy import endpoint, exits, gateway, podman, providers

from . import desktop, geometry, paths, settings, store
from .engines import get_engine
from .engines.camoufox import fontconfig_xml
from .fingerprint import validate, validate_against
from .fingerprint.validator import Issue, errors
from .models import ExitInfo, Fingerprint, Profile

BROWSER_IMAGE = "kiwi-fox/browser:latest"
# The launcher, from the app over the image's copy, and the folder it shares.
LAUNCHER_MOUNT = "/usr/local/bin/kf-browser"
CONTROL_MOUNT = "/run/kf-control"
# How long a browser asked to start in a running container has to say so.
OPEN_TIMEOUT = 15.0
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


def control_dir(profile_id: str) -> Path:
    """The folder the container's launcher shares with this side: the browser's
    state ("open PID" / "closed CODE"), "keep", the pages to open with."""
    d = runtime_dir(profile_id) / "control"
    d.mkdir(parents=True, exist_ok=True)
    return d


def launcher_script() -> Path:
    """The launcher the container runs as process 1. crun refuses a file without
    the executable bit, and a copy can lose it (git keeps this one 644, the image
    build sets it): then an executable copy in the runtime folder is used."""
    from .setup import containers_dir

    script = containers_dir() / "browser" / "entrypoint.sh"
    if os.access(script, os.X_OK):
        return script
    copy = paths.runtime_dir() / "kf-browser"
    copy.parent.mkdir(parents=True, exist_ok=True)
    data = script.read_bytes()
    if not copy.exists() or copy.read_bytes() != data:
        tmp = copy.with_suffix(".new")
        tmp.write_bytes(data)
        tmp.chmod(0o755)
        tmp.replace(copy)
    return copy


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
    # The window's app id, so the desktop shows the profile's (or Kiwi Fox's)
    # name and icon instead of "camoufox" and a blank.
    spec.args = [*desktop.window_args(profile), *spec.args]
    # Back to an older version than the profile last ran (a pin, a move): Firefox
    # refuses the profile unless told the downgrade is meant.
    from . import engine_versions

    version = engine_versions.version_of(profile)
    if version and engine_versions.downgrading(profile, version):
        spec.args.append("--allow-downgrade")
    if resolv_conf:
        spec.volumes.append((resolv_conf, "/etc/resolv.conf", "ro,z"))
    # The launcher that supervises the browser, and the folder it reports in.
    spec.volumes.append((str(launcher_script()), LAUNCHER_MOUNT, "ro"))
    spec.volumes.append((str(control_dir(profile.id)), CONTROL_MOUNT, "rw"))
    spec.env["KF_CONTROL"] = CONTROL_MOUNT
    spec.labels["kiwi-fox.supervised"] = "1"
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


def launch(
    profile: Profile,
    *,
    strict: bool = False,
    start_url: str | None = None,
    browser: bool = True,
) -> LaunchResult:
    """Start the profile's container and, with `browser`, its browser. When the
    container already runs (kept after its browser quit, or started on its own),
    only the browser is started in it."""
    if not podman.available():
        raise LaunchError("podman not found")
    name = paths.browser_name(profile.id)
    if container_running(profile):
        if not browser:
            raise LaunchError(f"{profile.name}'s container is already running")
        if running(profile):
            raise LaunchError(f"{profile.name} is already open")
        if not supervised(profile):
            raise LaunchError(
                f"{profile.name}'s container was started by an older Kiwi Fox; stop it first"
            )
        open_browser(profile, start_url)
        ensure_watcher(profile)
        return LaunchResult(profile, gateway_of(profile), name, profile.last_exit, [], [])
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
        if info is None:
            # A provider exit (Tor, Mysterium) sits on the bridge, out of the
            # host's reach: the pre-flight could not measure it. Ask through the
            # gateway now — it is kiwi-proxy's gateway measuring its own exit.
            try:
                info = gateway.measure_exit(gw.name)
            except _NETWORK_ERRORS as exc:
                notes.append(f"could not measure the exit: {exc}")
        if info is not None and (ex := exit_of(profile)):
            exits.record_exit(ex, info)  # the exit's record is what both apps show

    clear_stale_lock(profile)
    br = browser_spec(profile, fp, gateway_name, info.ip if info else None, resolv)
    br.env["KF_START_BROWSER"] = "1" if browser else "0"
    control = control_dir(profile.id)
    for stale in ("browser", "url"):
        (control / stale).unlink(missing_ok=True)
    if start_url:
        (control / "url").write_text(start_url + "\n")
    set_keep(profile, settings.load().keep_container or not browser)
    if "WAYLAND_DISPLAY" not in br.env:
        notes.append("no Wayland socket found; the browser window cannot open")
    try:
        podman.start(br)
    except podman.PodmanError as exc:
        release(profile, ignore=(br.name,))
        raise LaunchError(f"browser failed to start: {exc}") from exc
    if note := ensure_watcher(profile):
        notes.append(note)

    if info:
        profile.last_exit = info
    store.touch(profile)
    if browser:
        from . import snapshots as profile_snapshots  # late: it imports this module

        profile_snapshots.started(profile)  # this copy changes now; "in use here"
    return LaunchResult(profile, gateway_name, br.name, info, warnings, notes)


# ------------------------------------------------------- container and browser
def gateway_of(profile: Profile) -> str | None:
    return paths.gateway_name(profile.exit) if profile.exit else None


def container_running(profile: Profile) -> bool:
    return podman.is_running(paths.browser_name(profile.id))


def supervised(profile: Profile) -> bool:
    """The container runs this version's launcher (an older one ran the browser
    as process 1 and ended with it)."""
    return (runtime_dir(profile.id) / "control" / "browser").exists()


def browser_state(profile: Profile) -> tuple[str, str]:
    """("open", PID) | ("closed", CODE) | ("", "") when the launcher has not said."""
    try:
        state, _, rest = (
            (runtime_dir(profile.id) / "control" / "browser").read_text().strip().partition(" ")
        )
    except OSError:
        return "", ""
    return state, rest


def set_keep(profile: Profile, keep: bool) -> None:
    """Whether the container outlives its browser (the launcher looks when the
    browser ends)."""
    flag = control_dir(profile.id) / "keep"
    if keep:
        flag.touch()
    else:
        flag.unlink(missing_ok=True)


def apply_keep_setting() -> None:
    """The preference changed: every running container follows it from now on,
    except one started without a browser, which waits for one."""
    keep = settings.load().keep_container
    for p in store.list_profiles():
        if (runtime_dir(p.id) / "control").is_dir():
            started_empty = browser_state(p)[1] == "-" and not running(p)
            set_keep(p, keep or started_empty)


def open_browser(profile: Profile, start_url: str | None = None) -> None:
    """Start the browser in the running container and wait until it says so."""
    control = control_dir(profile.id)
    if start_url:
        (control / "url").write_text(start_url + "\n")
    set_keep(profile, settings.load().keep_container)
    _signal(profile, "USR1")
    deadline = time.monotonic() + OPEN_TIMEOUT
    while time.monotonic() < deadline:
        if browser_state(profile)[0] == "open":
            from . import snapshots as profile_snapshots

            store.touch(profile)
            profile_snapshots.started(profile)
            return
        if not container_running(profile):
            break
        time.sleep(0.2)
    raise LaunchError(f"{profile.name}: the browser did not start in its container")


def _signal(profile: Profile, sig: str) -> None:
    proc = podman._run(["kill", "--signal", sig, paths.browser_name(profile.id)], check=False)
    if proc.returncode != 0:
        raise LaunchError(
            f"{profile.name}: {proc.stderr.strip() or 'the container did not take the signal'}"
        )


def quit_browser(profile: Profile) -> None:
    """Close the browser. Its container stops after it unless the preference
    keeps it (the watcher then lets go of the exit)."""
    if not container_running(profile):
        return
    if supervised(profile):
        _signal(profile, "USR2")
    else:
        stop(profile)


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


def heal_exits() -> list[str]:
    """kiwi-proxy's own recovery, asked for from kiwi-fox's refresh while windows
    are open: a tunnel node that failed closed (a Mysterium session ended) is
    started again behind its gateway, so the browser on it gets its route back
    without anyone opening Kiwi Proxy. Never raises; the refresh must go on."""
    try:
        if not podman.available():
            return []
        return gateway.heal()
    except Exception:  # noqa: BLE001 - a refresh tick, not a command
        return []


def running(profile: Profile) -> bool:
    """The browser is open: the profile's data is in use. (A container kept
    running without a browser does not count.)"""
    if not container_running(profile):
        return False
    state, _ = browser_state(profile)
    # a container of an older Kiwi Fox ran the browser as process 1
    return state != "closed" if state else True


def wait_and_teardown(profile: Profile) -> int:
    """Block until the browser exits, then tear the namespace down.

    Without this the gateway outlives the browser, holding a netns and a secret
    for an identity nobody is using.
    """
    code = podman.wait(paths.browser_name(profile.id))
    stop(profile)
    return code


# ------------------------------------------------------------------ watcher
WATCH_POLL = 1.0


def container_id(profile: Profile) -> str | None:
    proc = podman._run(
        ["container", "inspect", "--format", "{{.Id}}", paths.browser_name(profile.id)], check=False
    )
    return (proc.stdout.strip() or None) if proc.returncode == 0 else None


def watcher_unit(profile_id: str, cid: str) -> str:
    return f"kiwi-fox-watch-{profile_id[:12]}-{cid[:8]}"


# What a watcher needs to see the same stores as whoever started it.
_WATCH_ENV = (
    "PATH",
    "PYTHONPATH",
    "XDG_DATA_HOME",
    "XDG_CONFIG_HOME",
    "XDG_CACHE_HOME",
    "XDG_RUNTIME_DIR",
    "KIWI_PROXY_SECRETS",
    "DBUS_SESSION_BUS_ADDRESS",
)


def ensure_watcher(profile: Profile) -> str | None:
    """Start the watcher for the profile's current container, unless one runs.
    A transient user unit (systemd-run) when there is a user manager, so it
    outlives the window and the terminal; a detached process otherwise. A line
    to show when neither worked."""
    cid = container_id(profile)
    if cid is None:
        return None
    if (control_dir(profile.id) / f"watch-{cid[:12]}").exists():
        return None  # one is watching this container
    cmd = [sys.executable, "-m", "kiwi_fox", "watch", profile.id]
    if shutil.which("systemd-run"):
        env = [f"--setenv={k}={os.environ[k]}" for k in _WATCH_ENV if k in os.environ]
        proc = subprocess.run(  # noqa: S603
            [
                "systemd-run",
                "--user",
                "--quiet",
                "--collect",
                f"--unit={watcher_unit(profile.id, cid)}",
                f"--description=Kiwi Fox: {profile.name}, snapshot and let go of its exit",
                *env,
                *cmd,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0 or "already" in proc.stderr:
            return None
    try:
        with open(runtime_dir(profile.id) / "watch.log", "ab") as log:
            subprocess.Popen(  # noqa: S603
                cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True
            )
    except OSError as exc:
        return f"nothing watches {profile.name}'s container ({exc}); stop it from here"
    return None


def watch(profile: Profile) -> int:
    """Stay with the profile's container until it ends: snapshot when its browser
    closes, and when the container ends remove it and let go of the exit. Only
    this container: a newer one with the same name gets its own watcher."""
    from . import snapshots as profile_snapshots  # late: it imports this module

    name = paths.browser_name(profile.id)
    cid = container_id(profile)
    if cid is None:
        return 0
    marker = control_dir(profile.id) / f"watch-{cid[:12]}"
    try:
        fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return 0  # another watcher has it
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    waiter = subprocess.Popen(  # noqa: S603
        ["podman", "wait", cid], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    try:
        was_open = running(profile)
        while waiter.poll() is None:
            time.sleep(WATCH_POLL)
            now_open = browser_state(profile)[0] == "open"
            if was_open and not now_open:
                with contextlib.suppress(Exception):
                    profile_snapshots.after_stop(profile)
            was_open = now_open
        # The container ended. Remove it (by id: a new one may carry the name by
        # now) and let go of the exit unless something else is inside it.
        podman._run(["rm", "--force", cid], check=False)
        current = container_id(profile)
        if current is None or current == cid:
            release(profile, ignore=(name,))
        with contextlib.suppress(Exception):
            profile_snapshots.after_stop(profile)
    finally:
        marker.unlink(missing_ok=True)
        if waiter.poll() is None:
            waiter.kill()
    return 0


def repair() -> list[str]:
    """Before anything starts (the preference "Repair on start"): remove this
    app's containers a crash or a reset left, clear the locks of profiles whose
    browser is not running, and give every running container a watcher. What
    was done, for a note."""
    if not podman.available():
        return []
    done = []
    try:
        from kiwi_proxy import storage
    except ImportError:  # kiwi-proxy older than 0.8.2
        storage = None
    if storage is not None:
        gone = storage.remove_leftovers("kiwi-fox")
        if gone:
            done.append(f"removed {len(gone)} container(s) an unclean stop left")
    for p in store.list_profiles():
        if container_running(p):
            if supervised(p):
                ensure_watcher(p)
            continue
        if clear_stale_lock(p):
            done.append(f"cleared {p.name}'s stale lock")
        # its exit, held for a container that is gone (kept while anything else
        # is inside it)
        with contextlib.suppress(*_NETWORK_ERRORS):
            release(p, ignore=(paths.browser_name(p.id),))
    return done


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
