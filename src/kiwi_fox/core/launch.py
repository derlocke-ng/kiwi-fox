"""Profile -> gateway + browser -> lifecycle.

The gateway container owns the network namespace; the browser joins it and has
no routing table of its own, so the kill switch is the absence of a route
rather than software that has to notice. Measured working rootless on this host
(novafox ANALYSIS.md §4).
"""

from __future__ import annotations

import contextlib
import datetime as dt
import os
from dataclasses import dataclass, field
from pathlib import Path

from . import dns, geometry, paths, podman, proxy, secrets, store
from .engines import get_engine
from .engines.camoufox import FORWARDER_PORT, fontconfig_xml
from .fingerprint import validate, validate_against
from .fingerprint.validator import Issue, errors
from .models import ContainerSpec, ExitInfo, Fingerprint, Profile, ProviderRecord

GATEWAY_IMAGE = "kiwi-fox/gateway:latest"
BROWSER_IMAGE = "kiwi-fox/browser:latest"


class LaunchError(RuntimeError):
    pass


@dataclass
class LaunchResult:
    profile: Profile
    gateway: str
    browser: str
    exit_info: ExitInfo | None = None
    warnings: list[Issue] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# --------------------------------------------------------------------- prep
def runtime_dir(profile_id: str) -> Path:
    d = paths.runtime_dir() / profile_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def creds_secret_name(profile_id: str) -> str:
    return f"{paths.PREFIX}-creds-{profile_id[:12]}"


def write_credentials(profile: Profile) -> str:
    """Credentials reach the gateway as a podman secret, never as container env
    (`podman inspect` shows env) and never as a bind-mounted 0600 file (the
    gateway runs as container-root, a subuid, so it could not read it)."""
    name = creds_secret_name(profile.id)
    password = secrets.lookup(profile.id) or ""
    podman.secret_set(name, f"{profile.endpoint.username or ''}\n{password}\n")
    return name


def write_fontconfig(profile: Profile, fp: Fingerprint) -> Path:
    path = paths.profile_dir(profile.id) / "fonts.conf"
    path.write_text(fontconfig_xml(fp))
    return path


def write_resolver_config(profile: Profile) -> Path | None:
    if profile.dns.mode != "resolver":
        return None
    blocklist = dns.merged_blocklist(profile.dns.blocklists)
    cfg = dns.toml_config(
        profile.dns.upstream,
        blocklist="/blocklist/blocked-names.txt",
        forwarder="127.0.0.1",
        forwarder_port=FORWARDER_PORT,
    )
    path = runtime_dir(profile.id) / "dnscrypt-proxy.toml"
    path.write_text(cfg)
    return blocklist and path


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
    from .engines.camoufox import user_js

    engine = get_engine(fp.engine)
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
def gateway_spec(profile: Profile, endpoint_ip: str) -> ContainerSpec:
    rt = runtime_dir(profile.id)
    secret = creds_secret_name(profile.id)
    target = f"/run/secrets/{secret}"
    volumes: list[tuple[str, str, str]] = []
    env = {
        "KF_ENDPOINT_IP": endpoint_ip,
        "KF_ENDPOINT_PORT": str(profile.endpoint.port),
        "KF_FORWARDER_PORT": str(FORWARDER_PORT),
        "KF_DNS_MODE": profile.dns.mode,
        "KF_CREDS_FILE": target,
    }
    if profile.dns.mode == "resolver":
        # ",z" relabels for SELinux: without it an enforcing host denies the
        # container read access to anything under $HOME.
        volumes += [
            (str(rt / "dnscrypt-proxy.toml"), "/run/kf/dnscrypt-proxy.toml", "ro,z"),
            (str(paths.blocklists_dir()), "/blocklist", "ro,z"),
        ]
    return ContainerSpec(
        name=paths.gateway_name(profile.id),
        image=GATEWAY_IMAGE,
        network="pasta",
        env=env,
        volumes=volumes,
        secrets=[(secret, target)],
        cap_drop=["all"],
        # NET_ADMIN to build the ruleset, NET_BIND_SERVICE because the resolver
        # listens on 53 and dropping all caps denies that even to container-root.
        cap_add=["NET_ADMIN", "NET_RAW", "NET_BIND_SERVICE"],
        security_opt=["no-new-privileges"],
        userns=None,  # needs container-root to configure its own netns
        labels={"app": "kiwi-fox", "kiwi-fox.profile": profile.id, "kiwi-fox.role": "gateway"},
    )


def write_resolv_conf(profile: Profile) -> Path:
    """The browser is a separate container with its own mount namespace, so it
    needs its own resolv.conf pointing at the gateway's resolver. Mounted rather
    than written, because --dns cannot be combined with --network container:."""
    path = runtime_dir(profile.id) / "resolv.conf"
    path.write_text(f"nameserver {dns.LISTEN_ADDR}\noptions edns0 trust-ad\n")
    return path


def browser_spec(profile: Profile, fp: Fingerprint, gateway: str, exit_ip: str | None):
    spec = get_engine(fp.engine).build_spec(profile, fp, gateway=gateway, exit_ip=exit_ip)
    if profile.dns.mode == "resolver":
        spec.volumes.append((str(write_resolv_conf(profile)), "/etc/resolv.conf", "ro,z"))
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


# ------------------------------------------------------------------- launch
def preflight(profile: Profile) -> tuple[str, ExitInfo | None, list[str]]:
    notes: list[str] = []
    endpoint_ip = proxy.resolve(profile.endpoint.host)
    if endpoint_ip != profile.endpoint.host:
        notes.append(f"resolved {profile.endpoint.host} -> {endpoint_ip}")
    password = secrets.lookup(profile.id)
    try:
        info = proxy.preflight(profile.endpoint, password)
    except Exception as exc:  # noqa: BLE001 - never block the launch on this
        notes.append(f"pre-flight could not reach the exit: {exc}")
        return endpoint_ip, None, notes
    if profile.endpoint.module:
        store.record_provider(
            ProviderRecord(
                module=profile.endpoint.module,
                lease=profile.endpoint.lease or profile.endpoint.label,
                ip=info.ip,
                country=info.country,
                city=info.city,
                asn=info.asn,
                verified_at=dt.datetime.now(dt.UTC),
            )
        )
    return endpoint_ip, info, notes


def _start_gateway(profile: Profile, endpoint_ip: str) -> ContainerSpec:
    gw = gateway_spec(profile, endpoint_ip)
    # The browser joins the gateway's network namespace, which makes it a dependent
    # container: podman refuses to replace the gateway while it exists, with
    # "has dependent containers which must be removed before it". So the browser
    # goes first, even when it is already stopped.
    podman.rm(paths.browser_name(profile.id))
    podman.start(gw)
    if not podman.is_running(gw.name):
        raise LaunchError(f"gateway failed to start:\n{podman.logs(gw.name)}")
    return gw


def start_gateway(profile: Profile) -> tuple[str, ExitInfo | None]:
    """Bring up a profile's network namespace with no browser in it.

    For the probe, which needs the namespace and nothing else. Only call this
    when the gateway is not already running: it replaces it.
    """
    if not podman.available():
        raise LaunchError("podman not found")
    endpoint_ip, info, _notes = preflight(profile)
    write_credentials(profile)
    write_resolver_config(profile)
    return _start_gateway(profile, endpoint_ip).name, info


def launch(profile: Profile, *, strict: bool = False, start_url: str | None = None) -> LaunchResult:
    if not podman.available():
        raise LaunchError("podman not found")
    fp = store.load_fingerprint(profile.id)

    endpoint_ip, info, notes = preflight(profile)

    issues = validate(
        fp,
        engine_version=fp.engine_version,
        exit_country=info.country if info else None,
        prefs=get_engine(fp.engine).prefs(fp, profile),  # type: ignore[attr-defined]
        allow_prefs={"webgl.disabled"} if profile.webgl == "off" else set(),
    )
    from . import gpu
    from .fingerprint.validator import check_webgl_mode, check_window_fits

    engine_dir = paths.engines_dir() / f"camoufox-{fp.engine_version}"
    if profile.gpu_accel and gpu.measurement() is None and (engine_dir / "camoufox").exists():
        # Once per host: the prefs below depend on whether a GPU is really
        # reachable, and guessing wrong either way costs — forced hardware with no
        # GPU crash-loops, software with one reads as a virtual machine.
        with contextlib.suppress(Exception):  # a failed measurement must not block a launch
            gpu.measure(engine_dir)
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
        store.load_fingerprint(p.id)
        for p in store.list_profiles()
        if p.id != profile.id and (paths.profile_dir(p.id) / "fingerprint.json").exists()
    ]
    issues += validate_against(fp, others)
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

    if not (engine_dir / "camoufox").exists():
        raise LaunchError(
            f"engine missing at {engine_dir}; run `kiwi-fox engine fetch {fp.engine_version}`"
        )

    write_credentials(profile)
    write_fontconfig(profile, fp)
    write_resolver_config(profile)
    write_user_js(profile, fp)
    write_user_chrome(profile, fp)
    if note := install_langpack(profile, fp):
        notes.append(note)
    reset_toolbar_layout(profile)
    geometry.prepare(profile, fp)

    gw = _start_gateway(profile, endpoint_ip)

    clear_stale_lock(profile)
    br = browser_spec(profile, fp, gw.name, info.ip if info else None)
    if start_url:
        br.args = [start_url]
    if "WAYLAND_DISPLAY" not in br.env:
        notes.append("no Wayland socket found; the browser window cannot open")
    try:
        podman.start(br)
    except podman.PodmanError as exc:
        podman.rm(gw.name)
        raise LaunchError(f"browser failed to start: {exc}") from exc

    if info:
        profile.last_exit = info
    store.touch(profile)
    return LaunchResult(profile, gw.name, br.name, info, warnings, notes)


def stop(profile: Profile) -> None:
    podman.rm(paths.browser_name(profile.id))
    podman.rm(paths.gateway_name(profile.id))
    podman.secret_rm(creds_secret_name(profile.id))


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
    """Stop gateways whose browser is gone. Safe to call at any time."""
    cleaned = []
    for p in store.list_profiles():
        gw, br = paths.gateway_name(p.id), paths.browser_name(p.id)
        if podman.is_running(gw) and not podman.is_running(br):
            stop(p)
            cleaned.append(p.name)
    return cleaned
