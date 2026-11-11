"""kiwi-fox command line. The GUI is a layer over this; the CLI is the truth."""

from __future__ import annotations

import argparse
import json
import os
import sys

from kiwi_proxy import dns, exits, gateway, podman, providers
from kiwi_proxy import endpoint as proxy
from kiwi_proxy import paths as proxy_paths
from kiwi_proxy import secrets as proxy_secrets

from . import __version__
from .core import desktop, engine_versions, geometry, gpu, launch, paths, secrets, settings, store
from .core import snapshots as profile_snapshots
from .core.engines import TITLES, installed_versions
from .core.engines import fetch as engine_fetch
from .core.fingerprint import edit, generate, validate, validate_against, webgl
from .core.fingerprint import windows11 as w11
from .core.fingerprint.validator import check_webgl_mode as validate_webgl
from .core.fingerprint.validator import check_window_fits, errors
from .core.models import Fingerprint, Profile

WEBGL_MODES = ("host", "preset", "custom", "off", "raw")


def _p(*args: object) -> None:
    print(*args)


def _fail(msg: str) -> int:
    print(f"kiwi-fox: {msg}", file=sys.stderr)
    return 1


# ------------------------------------------------------------------ commands
class _NewError(Exception):
    pass


def _exit_for_new(a: argparse.Namespace):
    """Where a new profile exits: a proxy kiwi-proxy has (--exit), or none
    (--no-proxy). kiwi-fox makes no proxies — that is kiwi-proxy's, by hand or in
    its app — so an endpoint given here is sent there."""
    if a.endpoint:
        raise _NewError(
            "kiwi-fox does not make proxies. Define it in kiwi-proxy first — "
            f"`kiwi-proxy add NAME {a.endpoint}`, or the Kiwi Proxy app — then "
            f"`kiwi-fox new {a.name} --exit NAME`"
        )
    if bool(a.exit) == bool(a.no_proxy):
        raise _NewError(
            "say where the profile exits: --exit PROXY (one kiwi-proxy has — `kiwi-proxy "
            "list`; `kiwi-proxy add` makes one), or --no-proxy (this machine's own connection)"
        )
    if a.no_proxy:
        return None
    try:
        return exits.resolve_ref(a.exit)
    except exits.ExitError as exc:
        raise _NewError(f"{exc} (kiwi-proxy list shows them; kiwi-proxy add makes one)") from exc


def _probe_for_region(a: argparse.Namespace, ex) -> tuple[str | None, str | None]:
    """The country and timezone a Camoufox profile's region follows: --country, or
    what the exit reports. A plain exit is asked from the host; a provider exit
    sits on a bridge the host cannot reach, so its last measurement is used; no
    proxy means this machine's own connection."""
    if a.country or a.no_probe:
        return a.country, None
    try:
        if ex is None:
            info = launch.measure_direct()
        elif providers.manages(ex.endpoint.module):
            info = ex.last_exit
            if info is None:
                _p(
                    f"note: {ex.name} has not been up yet, so its region is unknown; pass "
                    "--country, or accept the default region"
                )
                return None, None
        else:
            info = proxy.preflight(ex.endpoint, proxy_secrets.lookup(ex.id, kind="endpoint"))
    except Exception as exc:  # noqa: BLE001
        _p(f"warning: could not probe the exit ({exc}); falling back to --country")
        return None, None
    _p(f"exit: {info.ip} {info.country or '?'} {info.city or ''} ({info.timezone or '?'})")
    return info.country, info.timezone


# Spoof-only flags, by their CLI name, with the value that means "given". A
# non-spoofing engine refuses them rather than silently ignoring a request.
def _spoof_flags_given(a: argparse.Namespace) -> list[str]:
    pairs = {
        "--form": a.form,
        "--gpu-family": a.gpu_family,
        "--webgl": a.webgl,
        "--card": a.card,
        "--series": a.series,
        "--exact": a.exact or None,
        "--webgl-vendor": a.webgl_vendor,
        "--webgl-renderer": a.webgl_renderer,
        "--extra-fonts": a.extra_fonts or None,
        "--seed": a.seed,
    }
    return [flag for flag, val in pairs.items() if val]


def _new_firefox(a: argparse.Namespace, ex) -> int:
    from .core.engines import firefox_fetch

    given = _spoof_flags_given(a)
    if given:
        return _fail(
            f"stock Firefox shows this machine's own values, so {', '.join(given)} do not apply"
        )
    # No version given: the profile follows (the default, else the newest installed).
    if a.engine_version and a.engine_version not in firefox_fetch.installed():
        return _fail(
            f"Firefox {a.engine_version} is not installed (kiwi-fox engine fetch --engine firefox {a.engine_version})"
        )
    version = a.engine_version or None
    profile = store.create(
        a.name, ex.id if ex else None, None, engine="firefox", engine_version=version
    )
    profile.appearance = a.appearance
    profile.desktop_entry = bool(a.desktop_entry)
    profile.tags = store.normalize_tags(a.tag or [])
    store.save(profile)
    _p(f"created {profile.name}  {profile.id}")
    if version:
        _p(f"  engine  : stock Firefox {version}")
    else:
        _p(
            "  engine  : stock Firefox (none installed yet — kiwi-fox engine fetch --engine firefox)"
        )
    _p("  identity: none — this machine's own Firefox, nothing spoofed")
    _p(f"  exit    : {store.describe_exit(ex)}")
    if profile.desktop_entry:
        _p(f"  app grid: {desktop.entry_path(profile.id)}")
    return 0


def _new_torbrowser(a: argparse.Namespace, ex) -> int:
    from .core.engines import torbrowser_fetch

    given = _spoof_flags_given(a)
    if given:
        return _fail(
            f"Tor Browser keeps its own uniform fingerprint, so {', '.join(given)} do not apply"
        )
    if a.engine_version and a.engine_version not in torbrowser_fetch.installed():
        return _fail(f"Tor Browser {a.engine_version} is not installed")
    version = a.engine_version or None  # None: follows the newest installed
    try:
        profile = store.create(
            a.name, ex.id if ex else None, None, engine="torbrowser", engine_version=version
        )
    except store.StoreError as exc:
        return _fail(str(exc))
    profile.appearance = a.appearance  # the window; pages see light
    profile.desktop_entry = bool(a.desktop_entry)
    profile.tags = store.normalize_tags(a.tag or [])
    store.save(profile)
    _p(f"created {profile.name}  {profile.id}")
    if version:
        _p(f"  engine  : Tor Browser {version}")
    else:
        _p("  engine  : Tor Browser (none installed — kiwi-fox engine fetch --engine torbrowser)")
    _p("  identity: Tor Browser's own uniform fingerprint, untouched")
    _p("  circuits: one per first-party site (New Identity / New Circuit work)")
    try:
        from kiwi_proxy import selection

        sel = selection.of(ex.endpoint)
        chosen = bool(sel and (sel.only_countries or sel.only_nodes))
    except ImportError:
        chosen = bool(ex.endpoint.country)
    if chosen or ex.endpoint.lease:
        _p("  note    : holding a Tor exit to some countries or relays shrinks your anonymity set")
    _p(f"  exit    : {store.describe_exit(ex)}")
    if profile.desktop_entry:
        _p(f"  app grid: {desktop.entry_path(profile.id)}")
    return 0


def cmd_new(a: argparse.Namespace) -> int:
    try:
        ex = _exit_for_new(a)
    except _NewError as exc:
        return _fail(str(exc))
    return _new_profile(a, ex)


def _new_profile(a: argparse.Namespace, ex) -> int:
    if a.engine == "firefox":
        return _new_firefox(a, ex)
    if a.engine == "torbrowser":
        return _new_torbrowser(a, ex)

    version = a.engine_version or engine_versions.for_new_profile("camoufox")
    if not version:
        return _fail(
            "Camoufox is not installed; run `kiwi-fox setup` first "
            "(or choose --engine firefox / torbrowser)"
        )

    try:
        mode, card, series = _webgl_choice(
            a.webgl, a.card, a.series, a.webgl_vendor, a.webgl_renderer, family=a.gpu_family
        )
    except ValueError as exc:
        return _fail(str(exc))
    if hard := errors(validate_webgl(mode, a.webgl_vendor, a.webgl_renderer, series)):
        return _fail("; ".join(i.message for i in hard))

    country, exit_timezone = _probe_for_region(a, ex)

    fp = generate(
        series=series,
        engine_version=version,
        country=country,
        form_factor=a.form,
        gpu_family=a.gpu_family,
        timezone=exit_timezone,
        seed=a.seed,
        extra_fonts=a.extra_fonts,
    )
    issues = validate(fp, engine_version=version, exit_country=country)
    others = [
        store.load_fingerprint(p.id)
        for p in store.list_profiles()
        if (paths.profile_dir(p.id) / "fingerprint.json").exists()
    ]
    issues += validate_against(fp, others)
    if hard := errors(issues):
        for i in hard:
            _p(f"  {i}")
        return _fail("generated fingerprint is incoherent; this is a bug, please report it")
    for i in issues:
        _p(f"  {i}")

    profile = store.create(a.name, ex.id if ex else None, fp)
    profile.webgl = mode  # type: ignore[assignment]
    profile.webgl_series = series
    profile.webgl_card = card
    profile.webgl_exact = bool(a.exact) and mode in ("host", "preset")
    profile.webgl_vendor = a.webgl_vendor if mode == "custom" else None
    profile.webgl_renderer = a.webgl_renderer if mode == "custom" else None
    profile.appearance = a.appearance
    profile.language = a.language
    profile.desktop_entry = bool(a.desktop_entry)
    profile.tags = store.normalize_tags(a.tag or [])
    store.save(profile)
    for issue in validate_webgl(mode, profile.webgl_vendor, profile.webgl_renderer, series):
        _p(f"  {issue}")
    _p(f"created {profile.name}  {profile.id}")
    _p(f"  machine : {fp.form_factor}, {fp.hardware_concurrency} cores")
    for line in _webgl_lines(profile, fp):
        _p(f"  {line}")
    for issue in check_window_fits(fp):
        _p(f"  {issue}")
    _p(
        f"  screen  : {fp.screen.width}x{fp.screen.height} @{fp.screen.device_pixel_ratio} (avail {fp.screen.avail_width}x{fp.screen.avail_height})"
    )
    _p(f"  region  : {fp.locale} / {fp.timezone}")
    _p(f"  fonts   : {len(fp.fonts)} families")
    _p(f"  exit    : {store.describe_exit(ex)}")
    if profile.desktop_entry:
        _p(f"  app grid: {desktop.entry_path(profile.id)}")
    return 0


def _exit_column(p, names: dict[str, str]) -> str:
    if not p.exit:
        return "no proxy"
    return names.get(p.exit) or f"MISSING ({p.exit[:8]})"


def cmd_list(a: argparse.Namespace) -> int:
    profiles = store.list_profiles()
    if not profiles:
        _p(
            "no profiles yet — `kiwi-fox new NAME --exit PROXY` (a proxy from `kiwi-proxy list`) "
            "or `kiwi-fox new NAME --no-proxy`"
        )
        return 0
    from .core.engines import TITLES

    if a.tag:
        wanted = a.tag.lower()
        profiles = [p for p in profiles if wanted in (t.lower() for t in p.tags)]
        if not profiles:
            _p(f"no profile is tagged {a.tag!r}")
            return 0
    if a.by_tag:
        # Tagged first, by their first tag, then the untagged; names within.
        profiles.sort(key=lambda p: ((p.tags[0].lower() if p.tags else "~"), p.name))
    names = {ex.id: ex.name for ex in exits.list_exits()}
    _p(f"{'NAME':16} {'BROWSER':12} {'EXIT':24} {'COUNTRY':8} {'STATE':9} {'TAGS':16} ID")
    for p in profiles:
        state = (
            "open"
            if launch.running(p)
            else "container"
            if launch.container_running(p)
            else "stopped"
        )
        seen = store.seen_exit(p)
        country = (seen.country if seen else None) or "-"
        where = _exit_column(p, names)
        tags = ",".join(p.tags) or "-"
        _p(
            f"{p.name:16} {TITLES[p.engine]:12} {where:24} {country:8} {state:9} "
            f"{tags:16} {p.id[:8]}"
        )
    return 0


def _show_common(p) -> None:
    _p(f"{p.name}  ({p.id})")
    _p(f"  created   {p.created:%Y-%m-%d %H:%M}  last used {p.last_used or 'never'}")
    try:
        ex = store.exit_of(p)
    except store.StoreError:
        _p(f"  exit      MISSING ({p.exit[:8]}) — kiwi-fox set {p.name} --exit NAME, or --no-proxy")
    else:
        _p(f"  exit      {store.describe_exit(ex)}" + ("  (kiwi-proxy)" if ex else ""))
        if ex and ex.endpoint.username:
            _p(f"  auth      user {ex.endpoint.username}")
    if p.desktop_entry:
        _p(f"  app grid  yes — {desktop.entry_path(p.id)}")
    if p.tags:
        _p(f"  tags      {', '.join(p.tags)}")
    if e := store.seen_exit(p):
        _p(
            f"  last exit {e.ip} {e.country or '?'} {e.city or ''} asn={e.asn or '?'} at {e.seen:%Y-%m-%d %H:%M}"
            "  (kiwi-proxy check EXIT measures it again)"
        )


def cmd_show(a: argparse.Namespace) -> int:
    p = store.resolve_ref(a.ref)
    if p.engine == "torbrowser":
        from .core.engines import torbrowser_fetch

        _show_common(p)
        version = p.engine_version or torbrowser_fetch.latest_installed() or "none installed"
        _p(f"  engine    Tor Browser {version}")
        _p("  identity  Tor Browser's own uniform fingerprint, untouched")
        _p("  circuits  one per first-party site (New Identity / New Circuit work)")
        return 0
    if p.engine != "camoufox":
        from .core.engines import firefox_fetch

        _show_common(p)
        version = p.engine_version or firefox_fetch.latest_installed() or "none installed"
        _p(f"  engine    stock Firefox {version}")
        _p(f"  looks     {p.appearance}")
        _p("  identity  none — this machine's own values, nothing spoofed")
        return 0

    fp = store.load_fingerprint(p.id)
    _show_common(p)
    _p(f"  engine    camoufox {fp.engine_version} (buildID {fp.build_id})")
    _p(f"  ua        {p.user_agent or fp.ua}{'  (custom)' if p.user_agent else ''}")
    _p(f"  looks     {p.appearance}")
    said = w11.browser_languages(fp.locale, fp.languages, p.language)
    build = w11.firefox_build(fp.locale) if p.language == "local" else "en-US"
    _p(f"  language  {build} Firefox, announcing {w11.accept_language_for(said)}")
    _p(
        f"  machine   {fp.form_factor} / {fp.hardware_concurrency} cores / touch={fp.max_touch_points}"
    )
    _p(
        f"  screen    {fp.screen.width}x{fp.screen.height} @{fp.screen.device_pixel_ratio}, avail {fp.screen.avail_width}x{fp.screen.avail_height}"
    )
    _p(f"  window    {geometry.describe(p, fp)}")
    for line in _webgl_lines(p, fp):
        _p(f"  {line}")
    _p(f"  audio     {fp.audio.sample_rate} Hz, seed {fp.audio.seed}")
    _p(f"  canvas    seed {fp.canvas_seed}")
    _p(f"  region    {fp.locale} / {fp.timezone}")
    _p(f"  fonts     {len(fp.fonts)} families, {len(fp.font_files)} files")
    return 0


def cmd_check(a: argparse.Namespace) -> int:
    profiles = [store.resolve_ref(a.ref)] if a.ref else store.list_profiles()
    bad = 0
    for p in profiles:
        # Only camoufox carries a spoofed identity to check. A firefox/torbrowser
        # profile has no fingerprint; say so and move on rather than abort the run.
        if p.engine != "camoufox":
            _p(f"{p.name}: {p.engine} — no spoofed identity to check")
            continue
        fp = store.load_fingerprint(p.id)
        from .core.engines import get_engine

        issues = validate(
            fp,
            engine_version=fp.engine_version,
            exit_country=p.last_exit.country if p.last_exit else None,
            prefs=get_engine(p.engine).prefs(fp, p),  # type: ignore[attr-defined]
            allow_prefs={"webgl.disabled"} if p.webgl == "off" else set(),
        )
        others = [
            store.load_fingerprint(o.id)
            for o in store.list_profiles()
            if o.id != p.id and (paths.profile_dir(o.id) / "fingerprint.json").exists()
        ]
        issues += validate_against(fp, others)
        issues += validate_webgl(p.webgl, p.webgl_vendor, p.webgl_renderer, p.webgl_series)
        issues += check_window_fits(fp)
        issues += _ua_issues(p, fp)
        if not issues:
            _p(f"{p.name}: coherent")
            continue
        _p(f"{p.name}:")
        for i in issues:
            _p(f"  {i}")
        bad += len(errors(issues))
    return 1 if bad else 0


def cmd_run(a: argparse.Namespace) -> int:
    p = store.resolve_ref(a.ref)
    if launch.running(p):
        return _fail(f"{p.name} is already running")
    if profile_snapshots.available() and not a.as_is:
        p = _look_before_start(p, a)
        if p is None:
            return 1
    try:
        res = launch.launch(p, strict=a.strict, start_url=a.url)
    except launch.LaunchError as exc:
        return _fail(str(exc))
    for note in res.notes:
        _p(f"note: {note}")
    for w in res.warnings:
        _p(f"  {w}")
    if res.exit_info:
        e = res.exit_info
        _p(f"exit: {e.ip} {e.country or '?'} {e.city or ''}")
    _p(f"gateway {res.gateway or 'none (no proxy)'}")
    _p(f"browser {res.browser}")
    if a.wait:
        _p("waiting for the browser to exit (ctrl-c detaches without tearing down)")
        try:
            code = launch.wait_and_teardown(p)
        except KeyboardInterrupt:
            _p("detached; the profile keeps running")
            return 0
        _p(f"browser exited ({code}); gateway released")
        if note := profile_snapshots.after_stop(p):
            _p(f"note: {note}")
    return 0


def cmd_up(a: argparse.Namespace) -> int:
    """The profile's container without its browser: the exit is up and the
    browser starts at once later (run, or Start browser in the window)."""
    p = store.resolve_ref(a.ref)
    try:
        res = launch.launch(p, browser=False)
    except launch.LaunchError as exc:
        return _fail(str(exc))
    for note in res.notes:
        _p(f"note: {note}")
    _p(f"{p.name}: container {res.browser} running, no browser; kiwi-fox run {p.name} opens it")
    return 0


def cmd_quit(a: argparse.Namespace) -> int:
    """Close the browser; its container follows unless the preference keeps it."""
    for ref in a.refs:
        p = store.resolve_ref(ref)
        if not launch.running(p):
            _p(f"{p.name}: no browser open")
            continue
        try:
            launch.quit_browser(p)
        except launch.LaunchError as exc:
            return _fail(str(exc))
        kept = settings.load().keep_container
        _p(
            f"{p.name}: browser closing"
            + ("; the container keeps running" if kept else ", and its container")
        )
    return 0


def cmd_watch(a: argparse.Namespace) -> int:
    """Internal: the watcher a start leaves behind (a transient user unit)."""
    try:
        p = store.load(a.profile_id)
    except store.StoreError:
        return 0
    return launch.watch(p)


def cmd_repair(a: argparse.Namespace) -> int:
    done = launch.repair()
    for line in done:
        _p(line)
    if not done:
        _p("nothing to repair")
    return 0


def cmd_prefs(a: argparse.Namespace) -> int:
    s = settings.load()
    if a.keep_container is not None:
        s.keep_container = a.keep_container == "on"
    if a.repair_on_start is not None:
        s.repair_on_start = a.repair_on_start == "on"
    if a.engine_updates is not None:
        s.engine_updates = a.engine_updates
    if (
        a.keep_container is not None
        or a.repair_on_start is not None
        or a.engine_updates is not None
    ):
        settings.save(s)
        launch.apply_keep_setting()
    _p(
        f"when the browser quits  {'keep its container running' if s.keep_container else 'stop its container'}"
    )
    _p(f"repair on start         {'on' if s.repair_on_start else 'off'}")
    words = {
        "tell": "tell me, and I install it",
        "auto": "install it by itself",
        "off": "do nothing",
    }
    _p(f"a new engine release    {words[s.engine_updates]}")
    return 0


def cmd_stop(a: argparse.Namespace) -> int:
    for ref in a.refs or [p.name for p in store.list_profiles()]:
        p = store.resolve_ref(ref)
        launch.stop(p)
        _p(f"stopped {p.name}")
        if note := profile_snapshots.after_stop(p):
            _p(f"  {note}")
    return 0


def cmd_delete(a: argparse.Namespace) -> int:
    p = store.resolve_ref(a.ref)
    if not a.yes:
        return _fail(f"this removes {p.name}; pass --yes to confirm")
    launch.down(p)
    store.delete(p.id, purge=a.purge)
    _p(f"deleted {p.name}" + (" (purged)" if a.purge else ""))
    return 0


def cmd_test(a: argparse.Namespace) -> int:
    endpoint, password = proxy.parse(a.endpoint)
    try:
        info = proxy.preflight(endpoint, password, geo_url=a.geo_url)
    except Exception as exc:  # noqa: BLE001
        return _fail(f"endpoint unreachable: {exc}")
    _p(f"ip       {info.ip}")
    _p(f"country  {info.country or '?'}")
    _p(f"city     {info.city or '?'}")
    _p(f"timezone {info.timezone or '?'}")
    _p(f"asn      {info.asn or '?'}")
    return 0


def cmd_engine(a: argparse.Namespace) -> int:
    if a.engine_cmd == "default-search":
        for v in engine_fetch.installed():
            path = engine_fetch.target_dir(v)
            if a.list:
                _p(f"camoufox {v} engines: {', '.join(engine_fetch.search_engine_ids(path))}")
                continue
            try:
                changed = engine_fetch.set_default_search(path, a.identifier)
            except engine_fetch.RepairError as exc:
                return _fail(str(exc))
            now = engine_fetch.current_default_search(path)
            _p(f"camoufox {v}: default search is {now}" + ("" if changed else " (unchanged)"))
        return 0

    if a.engine_cmd == "helpers":
        for v in engine_fetch.installed():
            path = engine_fetch.target_dir(v)
            if a.remove:
                gone = engine_fetch.remove_gl_helpers(path)
                _p(f"camoufox {v}: removed {', '.join(gone) if gone else 'nothing'}")
                continue
            try:
                added = engine_fetch.install_gl_helpers_from_mozilla(path, v)
            except engine_fetch.RepairError as exc:
                return _fail(str(exc))
            have = engine_fetch.gl_helpers_installed(path)
            _p(
                f"camoufox {v}: "
                + (f"installed {', '.join(added)}" if added else "already present")
                + f" (present: {', '.join(have) or 'none'})"
            )
        return 0

    if a.engine_cmd == "tweaks":
        for v in [a.version] if a.version else engine_fetch.installed():
            path = engine_fetch.target_dir(v)
            state = engine_fetch.tweak_state(path)
            _p(f"camoufox {v}:  default search: {engine_fetch.current_default_search(path)}")
            for name, tw in engine_fetch.TWEAKS.items():
                mark = "stock" if state.get(name) else "camoufox"
                _p(f"  [{mark:8}] {name:16} {tw.what}")
                _p(f"               fingerprint: {tw.fingerprint}")
        return 0

    if a.engine_cmd == "tweak":
        versions = engine_fetch.installed()
        if not versions:
            return _fail("no engine installed")
        names = list(engine_fetch.TWEAKS) if a.all else a.names
        if not names:
            return _fail("name a tweak, or pass --all (see `kiwi-fox engine tweaks`)")
        for v in versions:
            path = engine_fetch.target_dir(v)
            for name in names:
                try:
                    changed = engine_fetch.apply_tweak(path, name)
                except engine_fetch.RepairError as exc:
                    return _fail(f"{name}: {exc}")
                _p(f"camoufox {v}: {name} " + ("applied" if changed else "already stock"))
        return 0

    if a.engine_cmd in ("repair", "restore"):
        versions = [a.version] if a.version else engine_fetch.installed()
        if not versions:
            return _fail("no engine installed")
        for v in versions:
            path = engine_fetch.target_dir(v)
            try:
                if a.engine_cmd == "repair":
                    changed = engine_fetch.repair_search(path)
                    _p(f"camoufox {v}: " + ("search re-enabled" if changed else "already repaired"))
                else:
                    _p(
                        f"camoufox {v}: "
                        + (
                            f"restored {', '.join(engine_fetch.restore_engine(path))}"
                            if engine_fetch.restore_engine(path)
                            else "no backups to restore"
                        )
                    )
            except engine_fetch.RepairError as exc:
                return _fail(str(exc))
        return 0

    if a.engine_cmd == "list" and a.available:
        for engine in engine_versions.ENGINES:
            have = installed_versions(engine)
            default = engine_versions.default_for(engine)
            _p(f"{TITLES[engine]}:")
            for rel in engine_versions.releases(engine, refresh=a.refresh):
                users = engine_versions.users(engine, rel.version) if rel.version in have else []
                bits = ["installed" if rel.version in have else "not installed"]
                if rel.beta:
                    bits.append("beta")
                if default == rel.version:
                    bits.append("default")
                if users:
                    bits.append(", ".join(p.name for p in users))
                _p(f"  {rel.version:12} {' · '.join(bits)}")
        return 0

    if a.engine_cmd == "remove":
        try:
            engine_versions.remove(a.engine, a.version)
        except engine_versions.VersionError as exc:
            return _fail(str(exc))
        _p(f"removed {TITLES[a.engine]} {a.version}")
        return 0

    if a.engine_cmd == "default":
        try:
            engine_versions.set_default(
                a.engine, "" if a.version in ("auto", "newest") else a.version
            )
        except engine_versions.VersionError as exc:
            return _fail(str(exc))
        now = engine_versions.default_for(a.engine) or "the newest installed"
        what = (
            "new Camoufox profiles get" if a.engine == "camoufox" else "profiles without a pin use"
        )
        _p(f"{TITLES[a.engine]}: {what} {now}")
        return 0

    if a.engine_cmd == "check":
        found = engine_versions.news(force=True)
        if not found.news:
            _p("every engine you use is on its newest release")
        for item in found.news:
            if item.installed:
                _p(f"{TITLES[item.engine]} {item.version}: installed")
            elif item.error:
                _p(f"{TITLES[item.engine]} {item.version}: could not install: {item.error}")
            else:
                _p(
                    f"{TITLES[item.engine]} {item.version} is out: kiwi-fox engine fetch --engine {item.engine} {item.version}"
                )
        return 0

    if a.engine_cmd == "use":
        profile = store.resolve_ref(a.ref)
        try:
            if profile.engine == "camoufox":
                if a.version in ("newest", "auto"):
                    return _fail("a Camoufox profile moves to a version by number")
                refused, warnings = engine_versions.move(profile, a.version)
                if refused:
                    for line in refused:
                        _p(f"  {line}")
                    return _fail(
                        f"{profile.name} stays on its version: its fingerprint would not fit {a.version}"
                    )
                _p(f"{profile.name} moved to Camoufox {a.version}")
            else:
                version = None if a.version in ("newest", "auto") else a.version
                profile, warnings = engine_versions.pin(profile, version)
                now = engine_versions.version_of(profile)
                _p(
                    f"{profile.name}: {'pinned to' if version else 'follows, now'} {TITLES[profile.engine]} {now}"
                )
        except engine_versions.VersionError as exc:
            return _fail(str(exc))
        for line in warnings:
            _p(f"warning: {line}")
        if launch.container_running(profile):
            _p("its container is running: the version applies when it next starts")
        return 0

    if a.engine_cmd == "list":
        from .core.engines import firefox_fetch, torbrowser_fetch

        any_found = False
        for v in engine_fetch.installed():
            any_found = True
            state = (
                "search disabled (run `kiwi-fox engine repair`)"
                if engine_fetch.search_is_disabled(engine_fetch.target_dir(v))
                else "search ok"
            )
            _p(f"camoufox   {v}  {paths.engines_dir() / f'camoufox-{v}'}  [{state}]")
        for v in firefox_fetch.installed():
            any_found = True
            _p(f"firefox    {v}  {firefox_fetch.target_dir(v)}  [signature verified]")
        for v in torbrowser_fetch.installed():
            any_found = True
            _p(f"torbrowser {v}  {torbrowser_fetch.target_dir(v)}  [signature verified]")
        if not any_found:
            _p("none installed")
        return 0

    def progress(done: int, total: int) -> None:
        if total:
            pct = done * 100 // total
            print(f"\rdownloading {done >> 20} / {total >> 20} MiB ({pct}%)", end="", flush=True)

    if getattr(a, "engine", "camoufox") == "firefox":
        from .core.engines import firefox_fetch

        try:
            path = firefox_fetch.fetch(a.version, force=a.force, progress=progress)
        except Exception as exc:  # noqa: BLE001
            print()
            return _fail(str(exc))
        print()
        _p(f"firefox ready at {path}")
        return 0

    if getattr(a, "engine", "camoufox") == "torbrowser":
        from .core.engines import torbrowser_fetch

        try:
            path = torbrowser_fetch.fetch(a.version, force=a.force, progress=progress)
        except Exception as exc:  # noqa: BLE001
            print()
            return _fail(str(exc))
        print()
        _p(f"tor browser ready at {path}")
        return 0

    try:
        path = engine_fetch.fetch(
            a.version, allow_prerelease=a.prerelease, force=a.force, progress=progress
        )
    except Exception as exc:  # noqa: BLE001
        print()
        return _fail(str(exc))
    print()
    _p(f"engine ready at {path} ({engine_fetch.version_of(path) or '?'})")
    return 0


def cmd_dns(a: argparse.Namespace) -> int:
    paths.ensure_tree()
    if a.dns_cmd == "sync":
        try:
            stamps = dns.sync_stamps()
        except Exception as exc:  # noqa: BLE001
            return _fail(f"could not sync resolver stamps: {exc}")
        for name in sorted(stamps):
            _p(f"stamp {name}")
        return 0
    if a.dns_cmd == "update":
        for name in a.lists or ["oisd-big"]:
            try:
                path = dns.fetch_blocklist(name)
            except Exception as exc:  # noqa: BLE001
                return _fail(f"{name}: {exc}")
            lines = sum(1 for _ in path.open())
            _p(f"{name}: {lines} entries -> {path}")
        merged = dns.merged_blocklist(a.lists or ["oisd-big"])
        _p(f"merged -> {merged}")
        return 0
    return _fail("unknown dns subcommand")


def cmd_selfcheck(a: argparse.Namespace) -> int:
    from .core import probe as probe_mod

    profile = store.resolve_ref(a.ref)
    if (refused := _camoufox_only(profile, "selfcheck")) is not None:
        return refused
    what = "this machine, with nothing spoofed" if a.host else profile.name
    _p(f"probing {what} — a separate window opens briefly; your own session is not touched…")
    try:
        report = probe_mod.probe(profile, raw=a.host, skip=a.skip or "")
    except Exception as exc:  # noqa: BLE001
        return _fail(str(exc))
    if a.json:
        _p(json.dumps(report, indent=2))
        return 0
    if a.host:
        seen = (report.get("webgl") or {}).get("renderer")
        series, how = webgl.host_series()
        _p(f"  this machine's Firefox reports: {seen or '(no WebGL)'}")
        if series and how == "measured":
            _p(f"  series : {series.label}")
            _p(f"  on Windows that reads: {series.renderer}")
        else:
            _p("  that is not a GPU series Firefox reports on Windows; `host` mode will")
            _p(f"  go by the vendor instead ({series.label if series else 'unknown'})")
        return 0
    flat = probe_mod.flatten(report)
    for path in sorted(flat):
        source = probe_mod.SOURCES.get(path, probe_mod.SOURCES.get(path.split(".")[0], "?"))
        _p(f"  {source:8} {path:34} {probe_mod._short(flat[path], 60)}")
    problems = probe_mod.audit(report, profile)
    _p("")
    if not problems:
        _p("coherent: nothing a page can read contradicts the Windows claim")
        return 0
    _p(f"{len(problems)} thing(s) a page could catch:")
    for line in problems:
        _p(f"  - {line}")
    return 1


def cmd_compare(a: argparse.Namespace) -> int:
    from .core import probe as probe_mod

    first, second = store.resolve_ref(a.a), store.resolve_ref(a.b)
    for profile in (first, second):
        if (refused := _camoufox_only(profile, "compare")) is not None:
            return refused
    reports = {}
    for profile in (first, second):
        _p(f"probing {profile.name}…")
        try:
            reports[profile.name] = probe_mod.probe(profile)
        except Exception as exc:  # noqa: BLE001
            return _fail(f"{profile.name}: {exc}")
    rows = probe_mod.compare(reports[first.name], reports[second.name])
    _p("")
    _p(f"{'':3} {'SOURCE':8} {'SIGNAL':34} {first.name[:22]:22} {second.name[:22]:22}")
    counts: dict[tuple[str, bool], int] = {}
    for path, source, va, vb, differs in rows:
        counts[(source, differs)] = counts.get((source, differs), 0) + 1
        if a.only_same and differs:
            continue
        if a.only_diff and not differs:
            continue
        _p(f"{'≠' if differs else '=':3} {source:8} {path:34} {va[:22]:22} {vb[:22]:22}")
    _p("")
    _p("summary — a signal we never set is not spoofed just because it looks plausible:")
    for source in ("spoofed", "derived", "host", "engine", "unknown"):
        same = counts.get((source, False), 0)
        diff = counts.get((source, True), 0)
        if same or diff:
            _p(f"  {source:8} {diff:3} differ   {same:3} identical")
    return 0


def _webgl_choice(
    mode: str | None,
    card: str | None,
    series: str | None,
    vendor: str | None,
    renderer: str | None,
    *,
    family: str | None = None,
    current: str = "host",
) -> tuple[str, str | None, str | None]:
    """-> (mode, card name, series key). What was given decides the mode when it
    is not stated."""
    if mode is None:
        if card or series or family:
            mode = "preset"
        elif vendor or renderer:
            mode = "custom"
        else:
            mode = current
    if (card or series) and mode != "preset":
        raise ValueError(f"a card can only be chosen for `preset`, not `{mode}`")
    if (vendor or renderer) and mode != "custom":
        raise ValueError(f"vendor and renderer strings are for `custom`, not `{mode}`")
    if card:
        chosen = webgl.find_card(card)
        return mode, chosen.name, chosen.series.key
    return mode, None, (webgl.find(series).key if series else None)


def _webgl_lines(profile: Profile, fp: Fingerprint) -> list[str]:
    """What a page is told about the graphics card, and why it reads the way it does."""
    from .core.engines.camoufox import webgl_report

    if profile.webgl == "off":
        return ["webgl     off — pages get no WebGL at all"]
    if profile.webgl == "raw":
        return [
            "webgl     raw — nothing changed: pages get this machine's Linux strings and",
            "          limits. For measuring and testing; it does not look like Windows.",
        ]
    told = webgl_report(fp, profile)
    assert told is not None
    if profile.webgl == "custom":
        lines = ["webgl     custom text"]
    elif profile.webgl == "host":
        known = webgl.host_series()[1]
        what = told.card or {
            "family": "this machine's card (model not measured yet — run `kiwi-fox doctor`)",
            "unknown": "no GPU found on this machine — using the profile's own",
        }.get(known, "this machine's card")
        lines = [f"webgl     my card: {what}"]
    else:
        lines = [f"webgl     chosen card: {told.card or told.series.label}"]
    if told.exact:
        lines += [
            f"          pages see  {told.masked}",
            f"          and, in the debug field, the exact model:  {told.unmasked}",
        ]
    else:
        lines.append(f"          pages see  {told.unmasked}")
        if profile.webgl != "custom":
            lines.append(
                f"          Firefox never shows the exact model. It reports this text for: {told.series.covers}."
            )
    if profile.webgl == "custom":
        lines.append(f"          limits and extensions of: {told.series.label}")
    return lines


def cmd_gpus(a: argparse.Namespace) -> int:
    mine = webgl.host_card()
    _p("Cards a profile can be given. Firefox does not tell a page the exact model:")
    _p("it reports the group a card is in, the same text for every card in the group.")
    _p("So choosing between two cards of one group changes nothing a page can see,")
    _p("unless the profile is told to show the exact model (--exact).")
    for series in webgl.SERIES:
        cards = [c for c in webgl.CARDS if c.series is series]
        _p("")
        _p(f"Firefox shows:  {series.renderer}")
        _p(f"                ({webgl.share(series) * 100:.0f}% of Windows Firefox users)")
        line = "   "
        for card in cards:
            name = card.short + (
                "  <- like yours"
                if mine and series_of(mine) is series and card.name == mine
                else ""
            )
            if len(line) + len(name) > 92:
                _p(line.rstrip(" ,"))
                line = "   "
            line += name + ", "
        _p(line.rstrip(" ,"))
    _p("")
    if mine:
        told = webgl.series_for(webgl.exact_renderer(mine))
        _p(f"This machine: {mine}")
        _p(f"  -> Firefox shows it as: {told.renderer if told else '(not a known group)'}")
    else:
        _p("This machine's card has not been measured yet; `kiwi-fox doctor` does that.")
    _p("")
    _p('choose with:  kiwi-fox webgl NAME --card "RTX 3060"     (or --mode host for your own)')
    return 0


def series_of(card_name: str):
    return webgl.series_for(webgl.exact_renderer(card_name))


def cmd_webgl(a: argparse.Namespace) -> int:
    profile = store.resolve_ref(a.ref)
    if (refused := _camoufox_only(profile, "the graphics card it reports")) is not None:
        return refused
    fp = store.load_fingerprint(profile.id)
    given = (a.mode, a.card, a.series, a.vendor, a.renderer, a.exact)
    changing = any(v is not None for v in given)
    if changing:
        try:
            mode, card, series = _webgl_choice(
                a.mode, a.card, a.series, a.vendor, a.renderer, current=profile.webgl
            )
        except ValueError as exc:
            return _fail(str(exc))
        vendor = renderer = None
        if mode == "preset" and not (card or series):
            card, series = profile.webgl_card, profile.webgl_series
        elif mode == "custom":
            vendor = a.vendor or profile.webgl_vendor
            renderer = a.renderer or profile.webgl_renderer
        exact = profile.webgl_exact if a.exact is None else a.exact
        issues = validate_webgl(mode, vendor, renderer, series)
        if hard := errors(issues):
            return _fail("; ".join(i.message for i in hard))
        profile.webgl = mode  # type: ignore[assignment]
        profile.webgl_card = card if mode == "preset" else None
        profile.webgl_series = series if mode == "preset" else None
        profile.webgl_exact = bool(exact) and mode in ("host", "preset")
        profile.webgl_vendor, profile.webgl_renderer = vendor, renderer
        store.save(profile)
        for issue in issues:
            _p(f"  {issue}")
    _p(f"{profile.name}:")
    for line in _webgl_lines(profile, fp):
        _p(f"  {line}")
    if changing and launch.running(profile):
        _p("  (running — takes effect at the next launch)")
    return 0


def _ua_issues(profile: Profile, fp: Fingerprint) -> list:
    from .core.fingerprint.validator import Issue

    if not profile.user_agent:
        return []
    notes = edit.check_user_agent(profile.user_agent, fp.engine_version)
    return [Issue("warn", "ua.custom", f"custom user agent: {note}") for note in notes]


def _camoufox_only(profile: Profile, what: str) -> int | None:
    """A refusal for a command that reads or changes the spoofed Windows machine,
    which only a Camoufox profile has; None when the profile is one."""
    if profile.engine == "camoufox":
        return None
    from .core.engines import TITLES

    return _fail(
        f"{profile.name} is a {TITLES[profile.engine]} profile: {what} is about the Windows "
        "machine a Camoufox profile claims to be, and this one spoofs nothing"
    )


# `set` flags that change the spoofed machine, which only a Camoufox profile has.
_SET_IDENTITY_FLAGS = (
    ("--form", "form"),
    ("--screen", "screen"),
    ("--country", "country"),
    ("--timezone", "timezone"),
    ("--cores", "cores"),
    ("--audio-rate", "audio_rate"),
    ("--camera", "camera"),
    ("--font-add", "font_add"),
    ("--font-remove", "font_remove"),
    ("--language", "language"),
    ("--user-agent", "user_agent"),
    ("--default-user-agent", "default_user_agent"),
)


def _edited(fp: Fingerprint, a: argparse.Namespace) -> Fingerprint:
    new = fp
    if a.form:
        new = edit.with_form(new, a.form)
    if a.screen:
        new = edit.with_screen(new, a.screen)
    if a.country:
        new = edit.with_region(new, a.country, keep_timezone=bool(a.timezone))
    if a.timezone:
        new = edit.with_timezone(new, a.timezone)
    if a.cores is not None:
        new = edit.with_cores(new, a.cores)
    if a.audio_rate:
        new = edit.with_audio_rate(new, a.audio_rate)
    if a.camera:
        new = edit.with_camera(new, a.camera == "yes")
    if a.font_add or a.font_remove:
        new = edit.with_fonts(new, add=a.font_add or [], remove=a.font_remove or [])
    return new


def cmd_set(a: argparse.Namespace) -> int:
    """Change what a profile reports. Nothing is saved unless all of it is coherent.

    A Firefox or Tor Browser profile spoofs nothing, so only its name, exit and
    appearance can change. The exit's own settings — endpoint, DNS, blocklists —
    are kiwi-proxy's: `kiwi-proxy set NAME …`."""
    profile = store.resolve_ref(a.ref)
    fp = store.fingerprint_of(profile)
    if fp is None:
        given = [f for f, attr in _SET_IDENTITY_FLAGS if getattr(a, attr) not in (None, False, [])]
        if given:
            return _camoufox_only(profile, ", ".join(given)) or 1
    try:
        new = _edited(fp, a) if fp is not None else None
    except edit.EditError as exc:
        return _fail(str(exc))

    updates: dict[str, object] = {}
    if a.name and a.name != profile.name:
        if store.find_by_name(a.name):
            return _fail(f"a profile named {a.name!r} already exists")
        updates["name"] = a.name
    if a.appearance:
        updates["appearance"] = a.appearance
    if a.language:
        updates["language"] = a.language
    if a.user_agent:
        updates["user_agent"] = a.user_agent
    if a.default_user_agent:
        updates["user_agent"] = None
    if a.exit and a.no_proxy:
        return _fail("--exit and --no-proxy exclude each other")
    if a.exit:
        try:
            ex = exits.resolve_ref(a.exit)
            if profile.engine == "torbrowser":
                store.check_tor_exit(ex)
        except (exits.ExitError, store.StoreError) as exc:
            return _fail(str(exc))
        if ex.id != profile.exit:
            updates["exit"] = ex.id
    if a.no_proxy:
        if profile.engine == "torbrowser":
            return _fail(
                "Tor Browser needs an exit on the tor module; it cannot run without a proxy"
            )
        if profile.exit:
            updates["exit"] = None
    if a.tag or a.untag or a.no_tags:
        tags = [] if a.no_tags else list(profile.tags)
        tags = store.normalize_tags([*tags, *(a.tag or [])])
        drop = {t.lower() for t in store.normalize_tags(a.untag or [])}
        tags = [t for t in tags if t.lower() not in drop]
        if tags != profile.tags:
            updates["tags"] = tags
    if getattr(a, "icon", None) is not None:
        from .core import icons

        keys = {i.key for i in icons.choices()}
        if a.icon not in keys and a.icon != "kiwi-fox":
            return _fail(
                f"no icon {a.icon!r}; one of: kiwi-fox, {', '.join(sorted(k for k in keys if k))}"
            )
        updates["icon"] = "" if a.icon == "kiwi-fox" else a.icon
    if a.desktop_entry and a.no_desktop_entry:
        return _fail("--desktop-entry and --no-desktop-entry exclude each other")
    if a.desktop_entry and not profile.desktop_entry:
        updates["desktop_entry"] = True
    if a.no_desktop_entry and profile.desktop_entry:
        updates["desktop_entry"] = False

    changed = new != fp or bool(updates)
    if changed:
        if new is not None:
            issues = validate(new, engine_version=new.engine_version)
            if hard := errors(issues):
                for issue in hard:
                    _p(f"  {issue}")
                return _fail("that would make the profile incoherent; nothing was changed")
        candidate = profile.model_copy(update=updates)
        if new is not None and new != fp:
            store.save_fingerprint(profile.id, new)
        store.save(candidate)
        profile, fp = candidate, new
    cmd_show(argparse.Namespace(ref=profile.id))
    if fp is not None:
        for issue in check_window_fits(fp) + _ua_issues(profile, fp):
            _p(f"  {issue}")
    if not changed:
        _p("")
        if fp is None:
            _p(
                "nothing changed — pass what to change: --name, --exit, --no-proxy, "
                "--appearance, --desktop-entry, --tag"
            )
        else:
            _p(
                "nothing changed — pass what to change, e.g. --screen 2560x1440; "
                "see `kiwi-fox set -h`"
            )
            _p(
                "  screens : "
                + ", ".join(edit.screen_label(s) for s in edit.screen_choices(fp.form_factor))
            )
            _p("  regions : " + " ".join(sorted(w11.REGIONS)))
    elif launch.running(profile):
        _p("  (running — takes effect at the next launch)")
    if changed and (note := profile_snapshots.changed(profile)):
        _p(f"  {note}")
    return 0


def cmd_fonts(a: argparse.Namespace) -> int:
    from .core.fingerprint import fonts

    have: set[str] = set()
    if a.ref:
        profile = store.resolve_ref(a.ref)
        if (refused := _camoufox_only(profile, "its font list")) is not None:
            return refused
        have = set(store.load_fingerprint(profile.id).fonts)
    _p(
        f"{len(fonts.all_core_families())} families ship with every Windows 11 and are always present."
    )
    _p("These vary between real machines, so a profile may or may not have them:")
    _p("")
    for name in edit.optional_fonts():
        mark = "x" if name in have else " "
        probed = "  (on fingerprinters' probe lists)" if name in fonts.THIRD_PARTY else ""
        _p(f"  [{mark}] {name}{probed}" if a.ref else f"  {name}{probed}")
    _p("")
    _p("change with: kiwi-fox set NAME --font-add 'Lato' --font-remove 'Open Sans'")
    return 0


def cmd_module(a: argparse.Namespace) -> int:
    """Provider modules are kiwi-proxy's; `kiwi-fox module …` is `kiwi-proxy module …`."""
    from kiwi_proxy import cli as proxy_cli

    return proxy_cli.main(["module", *a.args])


def cmd_desktop(a: argparse.Namespace) -> int:
    """The profiles' entries in the app grid."""
    profiles = store.list_profiles()
    if a.desktop_cmd == "sync":
        with_entry, removed = desktop.sync_all(profiles, store.entry_description)
        _p(f"entries: {len(with_entry)} ({', '.join(with_entry) or 'none'})")
        if removed:
            _p(f"removed stale: {', '.join(removed)}")
        return 0
    for p in profiles:
        path = desktop.entry_path(p.id)
        state = "yes" if p.desktop_entry else "no"
        _p(f"{p.name:16} {state:4} {path if p.desktop_entry else ''}")
    return 0


def cmd_setup(a: argparse.Namespace) -> int:
    from .core import setup

    try:
        steps = setup.run(progress=lambda m: _p(f"  {m}"), engine_version=a.engine_version)
    except setup.SetupError as exc:
        return _fail(str(exc))
    _p("")
    for step in steps:
        _p(f"  {step}")
    _p("\nReady — create a profile (a proxy is one of kiwi-proxy's: `kiwi-proxy list`):")
    _p(
        "  kiwi-fox new work --exit mullvad                      Camoufox, a Windows identity, on that proxy"
    )
    _p(
        "  kiwi-fox new plain --no-proxy --engine firefox        stock Firefox on this machine's connection"
    )
    _p(
        "  kiwi-fox new anon --engine torbrowser --exit tor-de   Tor Browser; the exit is on the tor module:"
    )
    _p(
        "                                                        kiwi-proxy add tor-de --module tor --country de"
    )
    return 0


def cmd_doctor(a: argparse.Namespace) -> int:
    ok = True
    _p(f"podman        {podman.version() if podman.available() else 'MISSING'}")
    ok &= podman.available()
    _p(
        f"secret-tool   {'yes' if secrets.available() else 'MISSING (credentials cannot be stored)'}"
    )
    from .core.engines import firefox_fetch, torbrowser_fetch

    engines = engine_fetch.installed()
    ff = firefox_fetch.installed()
    tb = torbrowser_fetch.installed()
    line = f"camoufox: {', '.join(engines) or 'none'}"
    if ff:
        line += f"; firefox: {', '.join(ff)}"
    if tb:
        line += f"; torbrowser: {', '.join(tb)}"
    _p(
        f"engines       {line}"
        + ("" if (engines or ff or tb) else " — run `kiwi-fox engine fetch`")
    )
    ok &= bool(engines or ff or tb)
    import os

    wayland = os.environ.get("WAYLAND_DISPLAY")
    _p(f"wayland       {wayland or 'none (no window can open)'}")
    import kiwi_proxy
    from kiwi_proxy import setup as proxy_setup

    _p(f"kiwi-proxy    {kiwi_proxy.__version__}")
    stamps = dns.load_stamps()
    _p(f"dns stamps    {len(stamps) or 'none — run `kiwi-fox dns sync`'}")
    blocklist = proxy_paths.blocklists_dir() / "blocked-names.txt"
    _p(f"blocklist     {blocklist if blocklist.exists() else 'none — run `kiwi-fox dns update`'}")
    from .core import setup

    images = [(setup.image_state, i, n) for i, n in setup.IMAGES]
    images += [(proxy_setup.image_state, i, n) for i, n in proxy_setup.IMAGES]
    for state_of, image, name in images:
        state = state_of(image, name) if podman.available() else "missing"
        note = {
            "current": "yes",
            "stale": "outdated — built by an earlier version; run `kiwi-fox setup`",
            "missing": "MISSING — run `kiwi-fox setup`",
        }[state]
        _p(f"image         {image} {note}")
        ok &= state != "missing"
    _p(f"profiles      {len(store.list_profiles())}")
    _p(f"modules       {', '.join(providers.discover()) or 'none'}")
    version = engine_fetch.preferred()
    if version and podman.available():
        gpu.measure(engine_fetch.target_dir(version))
        _p(f"rendering     {gpu.describe()}")
        host, how = webgl.host_series()
        if host:
            _p(f"              pages are told: {host.label} ({how})")
        chosen = gpu.plan()
        if chosen.note:
            _p(f"              {chosen.note}")
        ok &= gpu.accelerated()
    return 0 if ok else 1


def cmd_reap(a: argparse.Namespace) -> int:
    cleaned = launch.reap()
    _p(", ".join(cleaned) + " torn down" if cleaned else "nothing orphaned")
    return 0


def cmd_ps(a: argparse.Namespace) -> int:
    """kiwi-fox's own containers: browsers and the gateways they joined. Provider
    containers are kiwi-proxy's (`kiwi-proxy ps`)."""
    out = podman._run(
        ["ps", "--all", "--format", "json", "--filter", f"label={paths.LABEL}"], check=False
    ).stdout
    rows = json.loads(out or "[]") if podman.available() else []
    if not rows:
        _p("no kiwi-fox containers")
        return 0
    for c in rows:
        names = ",".join(c.get("Names") or [])
        _p(f"{names:28} {c.get('State', '?'):10} {c.get('Image', '?')}")
    return 0


# -------------------------------------------------------------------- parser
# ----------------------------------------------------------------- snapshots
# The folder commands are kiwi-proxy's: one folder, one passphrase for every app.
PROXY_SNAPSHOT_COMMANDS = ("setup", "status", "unlock", "lock", "set")
SNAPSHOT_ERRORS: tuple[type[Exception], ...] = (
    (profile_snapshots.snap.SnapshotError,) if profile_snapshots.available() else ()
)


def _ask_tty(question: str, choices: dict[str, str], default: str) -> str:
    """One letter from the terminal; `choices` maps letters to answers."""
    while True:
        answer = input(question).strip().lower() or default
        if answer in choices:
            return choices[answer]


def _ask_before_start(p: Profile, check) -> str:
    """restore | asis | mine | cancel — from the terminal, a small window when
    started from the app grid, or "asis" with a note when there is neither."""
    if sys.stdin.isatty():
        snap = profile_snapshots.snap
        for device, since in check.in_use or []:
            if (
                _ask_tty(
                    f"{p.name} is in use on {device} since {snap.when_text(since)} "
                    "(as far as the snapshot folder knows). Start anyway? [y/N] ",
                    {"y": "go", "n": "cancel"},
                    "n",
                )
                == "cancel"
            ):
                return "cancel"
        rel = check.relation
        if not (rel and rel.newer_elsewhere):
            return "asis"
        head = rel.head
        when = f"{head.device}, {snap.when_text(head.created)}"
        if rel.state == "diverged":
            _p(f"{p.name} changed here and on {head.device} ({when}) since they parted.")
            return _ask_tty(
                "  [u] use the snapshot (this copy is kept as a snapshot)\n"
                "  [k] keep this device's (it becomes the newest)\n"
                "  [c] cancel\nChoice [c]: ",
                {"u": "restore", "k": "mine", "c": "cancel"},
                "c",
            )
        _p(f"A newer snapshot of {p.name} exists: from {when}.")
        return _ask_tty(
            "  [r] restore it and start (this copy is kept as a snapshot)\n"
            "  [s] start as it is\n  [c] cancel\nChoice [r]: ",
            {"r": "restore", "s": "asis", "c": "cancel"},
            "r",
        )
    if os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"):
        from .ui import start_prompt

        return start_prompt.ask(p.name, check)
    rel = check.relation
    if rel and rel.newer_elsewhere:
        _p(f"note: {rel.describe()} — kiwi-fox snapshot restore {p.name}")
    return "asis"


def _look_before_start(p: Profile, a: argparse.Namespace) -> Profile | None:
    """Before `run`: a newer copy in the folder, or the profile in use elsewhere.
    Returns the profile to start (restored, perhaps), or None to stop."""
    check = profile_snapshots.before_start(p)
    if not check.needs_asking:
        return p
    rel = check.relation
    asked_to_restore = a.restore and rel and rel.newer_elsewhere
    choice = "restore" if asked_to_restore else _ask_before_start(p, check)
    if choice == "cancel":
        _p("not started")
        return None
    if choice == "restore" and rel and rel.head:
        p = profile_snapshots.restore(p.id, rel.head.id)
        _p(f"restored {p.name} from {rel.head.device}")
        if missing := profile_snapshots.missing_engine(p):
            _fail(
                f"{p.name} needs {missing[0]} {missing[1]}: {profile_snapshots.fetch_hint(*missing)}"
            )
            return None
    elif choice == "mine":
        profile_snapshots.keep_mine(p, check)
        _p(f"this device's {p.name} is the newest snapshot now")
    return p


def cmd_snapshot(a: argparse.Namespace) -> int:
    if not profile_snapshots.available():
        return _fail(profile_snapshots.NEEDS)
    snap = profile_snapshots.snap
    cmd = a.snapshot_cmd
    if cmd == "list":
        opened = snap.folder()
        here = {p.id: p for p in store.list_profiles()}
        grouped = snap.catalog((profile_snapshots.KIND,))
        rows = []
        for pid in sorted(
            set(here) | {item for _k, item in grouped},
            key=lambda i: (
                here[i].name if i in here else grouped[(profile_snapshots.KIND, i)][0].name
            ),
        ):
            metas = grouped.get((profile_snapshots.KIND, pid), [])
            name = here[pid].name if pid in here else metas[0].name
            rel = snap.relation(
                profile_snapshots.KIND, pid, here=pid in here, metas=metas, folder_id=opened.id
            )
            newest = (
                f"{metas[0].device}, {snap.when_text(metas[0].created)} · {len(metas)} kept"
                if metas
                else ""
            )
            rows.append((name, rel.describe(), newest))
        if not rows:
            _p("no profiles")
            return 0
        width = max(len(r[0]) for r in rows)
        state_width = max(len(r[1]) for r in rows)
        for name, state, newest in rows:
            _p(f"{name:{width}}  {state:{state_width}}  {newest}".rstrip())
        return 0
    if cmd == "now":
        targets = [store.resolve_ref(r) for r in a.refs] if a.refs else store.list_profiles()
        for p in targets:
            if launch.running(p):
                _p(f"{p.name}: running, skipped (snapshots are taken of stopped profiles)")
                continue
            meta = profile_snapshots.take(p)
            _p(f"{p.name}: snapshot taken ({snap.size_text(meta.size)})")
        return 0
    if cmd == "history":
        pid, name = _profile_ref(a.ref)
        metas = snap.history(profile_snapshots.KIND, pid)
        if not metas:
            _p(f"no snapshot of {name} yet")
            return 0
        for meta in metas:
            aside = " · kept before a restore" if meta.aside else ""
            _p(
                f"{meta.id}  {snap.when_text(meta.created):20} {meta.device:12} {snap.size_text(meta.size):>8}{aside}"
            )
        return 0
    if cmd == "restore":
        pid, name = _profile_ref(a.ref)
        here = (paths.profile_dir(pid) / "profile.json").is_file()
        if a.id:
            sid = a.id
        else:
            rel = snap.relation(profile_snapshots.KIND, pid, here=here)
            if rel.head is None:
                return _fail(f"no snapshot of {name} in the folder")
            if here and rel.state == "same":
                _p(f"{name} is the newest snapshot already")
                return 0
            sid = rel.head.id
        if here and not a.yes:
            if not sys.stdin.isatty():
                return _fail(f"{name} is on this device; restoring replaces it — pass --yes")
            if input(
                f"Replace this device's {name} with snapshot {sid[:8]}? [y/N] "
            ).strip().lower() not in ("y", "yes"):
                _p("nothing changed")
                return 1
        p = profile_snapshots.restore(pid, sid)
        _p(f"restored {p.name}")
        if here:
            _p(f"  what was here is kept as a snapshot: kiwi-fox snapshot history {p.name}")
        if missing := profile_snapshots.missing_engine(p):
            if a.fetch:
                _p(f"  fetching {missing[0]} {missing[1]}…")
                profile_snapshots.fetch_engine(*missing)
            else:
                _p(
                    f"  it needs {missing[0]} {missing[1]}: {profile_snapshots.fetch_hint(*missing)}"
                )
        return 0
    if cmd == "forget":
        pid, name = _profile_ref(a.ref)
        if not a.yes:
            return _fail(f"this deletes every snapshot of {name} from the folder — pass --yes")
        removed = snap.forget(profile_snapshots.KIND, pid)
        _p(f"deleted {removed} snapshot(s) of {name}")
        return 0
    return _fail(f"unknown snapshot command {cmd}")


def _profile_ref(ref: str) -> tuple[str, str]:
    """A profile here, or one only in the folder: (id, name)."""
    try:
        p = store.resolve_ref(ref)
        return p.id, p.name
    except store.StoreError:
        return profile_snapshots.find_in_folder(ref)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="kiwi-fox", description=__doc__)
    ap.add_argument("--version", action="version", version=f"kiwi-fox {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    n = sub.add_parser(
        "new",
        help="create a profile",
        description="Create a profile. It exits through a proxy kiwi-proxy has (--exit "
        "PROXY, shared with whatever else is on it) or through none (--no-proxy, this "
        "machine's own connection). Proxies are made in kiwi-proxy: `kiwi-proxy add`, or "
        "the Kiwi Proxy app.",
    )
    n.add_argument("name")
    n.add_argument("endpoint", nargs="?", help=argparse.SUPPRESS)  # says where it belongs
    n.add_argument(
        "--exit",
        metavar="PROXY",
        help="a proxy kiwi-proxy has, by name or id prefix (`kiwi-proxy list`)",
    )
    n.add_argument(
        "--no-proxy",
        action="store_true",
        help="no proxy: the browser on this machine's own connection (not for Tor Browser)",
    )
    n.add_argument(
        "--desktop-entry",
        action="store_true",
        help="also put the profile in the app grid: a desktop entry of its own that launches it",
    )
    n.add_argument(
        "--tag",
        action="append",
        metavar="TAG",
        help="a tag, for grouping and finding profiles (repeatable, or comma-separated)",
    )
    n.add_argument(
        "--engine",
        choices=["camoufox", "firefox", "torbrowser"],
        default="camoufox",
        help="camoufox (default): a spoofed Windows identity; firefox: stock Firefox, "
        "this machine's own values; torbrowser: Tor Browser through an exit on the tor "
        "module, a circuit per site (no spoofing flags apply to the non-camoufox engines)",
    )
    n.add_argument(
        "--country",
        help="two-letter code: the identity's region; probed from the exit when omitted",
    )
    n.add_argument("--form", choices=["desktop", "laptop"], help="force the machine type")
    n.add_argument(
        "--gpu-family",
        choices=["amd", "intel", "nvidia"],
        help="draw the machine around a GPU of this vendor",
    )
    n.add_argument(
        "--webgl",
        choices=WEBGL_MODES,
        help="host (default): this machine's own card, as Windows Firefox shows it; "
        "preset: the card given with --card; custom: your own text; off: no WebGL; "
        "raw: change nothing (Linux values, for testing)",
    )
    n.add_argument("--card", help="a graphics card, e.g. 'RTX 3060'; see `kiwi-fox gpus`")
    n.add_argument("--series", help=argparse.SUPPRESS)
    n.add_argument(
        "--exact",
        action="store_true",
        help="let the debug field name the exact model instead of the card's group",
    )
    n.add_argument(
        "--language",
        choices=["local", "english"],
        default="local",
        help="local (default): the Firefox of the profile's region, in its language; "
        "english: an English Firefox used there",
    )
    n.add_argument("--webgl-vendor", help="custom mode only")
    n.add_argument("--webgl-renderer", help="custom mode only")
    n.add_argument(
        "--appearance",
        choices=["host", "light", "dark"],
        default="host",
        help="light or dark, for the browser and for what pages are told; "
        "host (default) follows this desktop",
    )
    n.add_argument(
        "--extra-fonts",
        action="store_true",
        help="also give the profile a random set of optional fonts; default is the "
        "Windows core set only, which draws fewer flags (change later: set --font-add)",
    )
    n.add_argument("--seed", help="reproduce a previous identity")
    n.add_argument("--engine-version")
    n.add_argument("--no-probe", action="store_true", help="skip the exit probe")
    n.set_defaults(func=cmd_new)

    ls = sub.add_parser("list", help="list profiles")
    ls.add_argument("--tag", metavar="TAG", help="only profiles with this tag")
    ls.add_argument(
        "--by-tag", action="store_true", help="tagged first, grouped by their first tag"
    )
    ls.set_defaults(func=cmd_list)

    s = sub.add_parser("show", help="everything about one profile")
    s.add_argument("ref")
    s.set_defaults(func=cmd_show)
    c = sub.add_parser("check", help="validate fingerprint coherence")
    c.add_argument("ref", nargs="?")
    c.set_defaults(func=cmd_check)

    r = sub.add_parser("run", help="launch a profile")
    r.add_argument("ref")
    r.add_argument("--strict", action="store_true", help="refuse to launch on warnings too")
    r.add_argument("--url", help="open this URL on start")
    r.add_argument(
        "--wait",
        action="store_true",
        help="block until the browser exits, then tear the namespace down",
    )
    r.add_argument(
        "--as-is",
        action="store_true",
        help="start without asking, even when the snapshot folder holds a newer copy",
    )
    r.add_argument(
        "--restore",
        action="store_true",
        help="when the snapshot folder holds a newer copy, restore it first without asking",
    )
    r.set_defaults(func=cmd_run)

    st = sub.add_parser(
        "stop", help="stop profiles' containers, browser and all (all when none given)"
    )
    st.add_argument("refs", nargs="*")
    st.set_defaults(func=cmd_stop)

    up = sub.add_parser("up", help="start a profile's container without its browser")
    up.add_argument("ref")
    up.set_defaults(func=cmd_up)

    qu = sub.add_parser("quit", help="close profiles' browsers (the containers follow unless kept)")
    qu.add_argument("refs", nargs="+")
    qu.set_defaults(func=cmd_quit)

    rp = sub.add_parser("repair", help="remove containers an unclean stop left, clear stale locks")
    rp.set_defaults(func=cmd_repair)

    pf = sub.add_parser("prefs", help="show or change Kiwi Fox's preferences")
    pf.add_argument(
        "--keep-container", choices=("on", "off"), help="keep the container when its browser quits"
    )
    pf.add_argument("--repair-on-start", choices=("on", "off"))
    pf.add_argument(
        "--engine-updates", choices=("tell", "auto", "off"), help="a new engine release"
    )
    pf.set_defaults(func=cmd_prefs)

    wt = sub.add_parser("watch")  # internal: the watcher a start leaves behind
    wt.add_argument("profile_id")
    wt.set_defaults(func=cmd_watch)

    d = sub.add_parser("delete", help="delete a profile")
    d.add_argument("ref")
    d.add_argument("--purge", action="store_true", help="also remove its identity and data")
    d.add_argument("--yes", action="store_true")
    d.set_defaults(func=cmd_delete)

    t = sub.add_parser("test", help="probe an endpoint without creating anything")
    t.add_argument("endpoint")
    t.add_argument("--geo-url", default=proxy.DEFAULT_GEO_URL)
    t.set_defaults(func=cmd_test)

    e = sub.add_parser("engine", help="manage engine builds")
    esub = e.add_subparsers(dest="engine_cmd", required=True)
    ef = esub.add_parser("fetch")
    ef.add_argument("version", nargs="?", help="e.g. 152.0.4; latest non-prerelease by default")
    ef.add_argument(
        "--engine",
        choices=["camoufox", "firefox", "torbrowser"],
        default="camoufox",
        help="which engine to fetch (default camoufox)",
    )
    ef.add_argument("--prerelease", action="store_true", help="consider beta releases too")
    ef.add_argument("--force", action="store_true")
    el = esub.add_parser(
        "list", help="installed versions; --available: every release, who uses what"
    )
    el.add_argument("--available", action="store_true")
    el.add_argument("--refresh", action="store_true", help="ask the publishers now, not the cache")
    erm = esub.add_parser("remove", help="remove an installed version no profile uses")
    erm.add_argument("version")
    erm.add_argument("--engine", choices=["camoufox", "firefox", "torbrowser"], default="camoufox")
    edf = esub.add_parser(
        "default", help="the version new Camoufox profiles get, or unpinned ones use"
    )
    edf.add_argument("version", help="a version, or 'newest' for the engine's own choice")
    edf.add_argument("--engine", choices=["camoufox", "firefox", "torbrowser"], default="camoufox")
    esub.add_parser(
        "check", help="look for new releases now (installs them when the preference says so)"
    )
    eu = esub.add_parser(
        "use", help="pin a profile to a version ('newest' to follow); move a Camoufox one"
    )
    eu.add_argument("ref")
    eu.add_argument("version")
    er = esub.add_parser(
        "repair", help="re-enable address-bar search (edits omni.ja, keeps a backup)"
    )
    er.add_argument("version", nargs="?")
    eds = esub.add_parser(
        "default-search", help="set the default search engine (edits the packaged config)"
    )
    eds.add_argument("identifier", nargs="?", default="ddg")
    eds.add_argument("--list", action="store_true", help="list available engine ids")
    eh = esub.add_parser(
        "helpers", help="install Firefox's GPU probe helpers (glxtest) into the engine"
    )
    eh.add_argument("--remove", action="store_true")
    et = esub.add_parser("tweaks", help="show which Camoufox JS/CSS patches are reverted")
    et.add_argument("version", nargs="?")
    etw = esub.add_parser("tweak", help="revert a Camoufox JS/CSS patch (reversible)")
    etw.add_argument(
        "names", nargs="*", help="one or more of: " + " ".join(sorted(engine_fetch.TWEAKS))
    )
    etw.add_argument("--all", action="store_true")
    ers = esub.add_parser("restore", help="put every backed-up original back")
    ers.add_argument("version", nargs="?")
    e.set_defaults(func=cmd_engine)

    dn = sub.add_parser("dns", help="resolver stamps and blocklists (kiwi-proxy's)")
    dsub = dn.add_subparsers(dest="dns_cmd", required=True)
    dsub.add_parser("sync", help="cache DoH resolver stamps")
    du = dsub.add_parser("update", help="download blocklists")
    du.add_argument("lists", nargs="*", choices=sorted(dns.BLOCKLISTS) or None)
    dn.set_defaults(func=cmd_dns)

    for alias in ("gpus", "cards"):
        sub.add_parser(alias, help="list the GPU series a profile can report").set_defaults(
            func=cmd_gpus
        )

    se = sub.add_parser(
        "set",
        help="change what a profile reports: screen, region, fonts, user agent, …",
        description="Change what an existing profile reports. Everything is checked "
        "together and nothing is saved unless the result is coherent. The GPU has its "
        "own command (`kiwi-fox webgl`). Not settable, because Firefox does not expose "
        "it: the Windows version — 10 and 11 send the same user agent.",
    )
    se.add_argument("ref")
    se.add_argument("--name", help="rename the profile")
    se.add_argument(
        "--icon",
        help="its app-grid icon: kiwi-fox, a colored kiwi-fox-…, firefox, camoufox, torbrowser, web-browser",
    )
    se.add_argument("--screen", metavar="WxH", help="claimed screen, e.g. 2560x1440")
    se.add_argument("--form", choices=["desktop", "laptop"])
    se.add_argument("--cores", type=int, help="logical CPU cores")
    se.add_argument("--country", help="region preset: locale, languages, voices, timezone")
    se.add_argument("--timezone", help="IANA name, e.g. Europe/Berlin")
    se.add_argument("--audio-rate", type=int, help="44100 or 48000")
    se.add_argument("--camera", choices=["yes", "no"])
    se.add_argument("--font-add", action="append", metavar="FAMILY")
    se.add_argument("--font-remove", action="append", metavar="FAMILY")
    se.add_argument("--appearance", choices=["host", "light", "dark"])
    se.add_argument(
        "--language",
        choices=["local", "english"],
        help="local: the region's own Firefox, in its language; english: an English one",
    )
    se.add_argument("--user-agent", help="replace the user agent (warned about when it lies)")
    se.add_argument("--default-user-agent", action="store_true", help="back to the engine's own")
    se.add_argument(
        "--exit", metavar="PROXY", help="put the profile on this kiwi-proxy exit (name or id)"
    )
    se.add_argument(
        "--no-proxy", action="store_true", help="take the profile off its proxy entirely"
    )
    se.add_argument("--desktop-entry", action="store_true", help="put the profile in the app grid")
    se.add_argument("--no-desktop-entry", action="store_true", help="take its desktop entry away")
    se.add_argument("--tag", action="append", metavar="TAG", help="add a tag (repeatable)")
    se.add_argument("--untag", action="append", metavar="TAG", help="remove a tag")
    se.add_argument("--no-tags", action="store_true", help="remove every tag")
    se.set_defaults(func=cmd_set)

    ds = sub.add_parser("desktop", help="the profiles' entries in the app grid")
    dsub = ds.add_subparsers(dest="desktop_cmd", required=True)
    dsub.add_parser(
        "sync",
        help="write the entry of every profile that wants one (they name this launcher) and "
        "remove stale ones",
    )
    dsub.add_parser("list", help="which profiles have an entry, and where")
    ds.set_defaults(func=cmd_desktop)

    fo = sub.add_parser("fonts", help="the font families a profile may or may not have")
    fo.add_argument("ref", nargs="?")
    fo.set_defaults(func=cmd_fonts)

    wg = sub.add_parser("webgl", help="show or change what a profile reports as its GPU")
    wg.add_argument("ref")
    wg.add_argument("--mode", choices=WEBGL_MODES)
    wg.add_argument("--card", help="a card, e.g. 'RTX 3060' (see `kiwi-fox gpus`); implies preset")
    wg.add_argument("--series", help=argparse.SUPPRESS)
    wg.add_argument(
        "--exact",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="let the debug field name the exact model instead of the card's group",
    )
    wg.add_argument("--vendor", help="custom vendor string; implies custom")
    wg.add_argument("--renderer", help="custom renderer string; implies custom")
    wg.set_defaults(func=cmd_webgl)

    sc = sub.add_parser("selfcheck", help="measure what a profile actually exposes")
    sc.add_argument("ref")
    sc.add_argument("--json", action="store_true")
    sc.add_argument(
        "--host",
        action="store_true",
        help="measure this machine instead: WebGL unspoofed, so `host` mode knows the "
        "exact GPU series (uses the profile only for its network namespace)",
    )
    sc.add_argument("--skip", help="collectors to leave out, comma-separated (for bisecting)")
    sc.set_defaults(func=cmd_selfcheck)

    cp = sub.add_parser("compare", help="probe two profiles and diff every signal")
    cp.add_argument("a")
    cp.add_argument("b")
    cp.add_argument("--only-diff", action="store_true")
    cp.add_argument("--only-same", action="store_true")
    cp.set_defaults(func=cmd_compare)

    su = sub.add_parser(
        "setup",
        help="first-run setup: the browser image and Camoufox, then kiwi-proxy's "
        "(gateway image, DNS data, module images)",
    )
    su.add_argument("--engine-version", help="pin a specific Camoufox version")
    su.set_defaults(func=cmd_setup)

    sub.add_parser("doctor", help="check the environment").set_defaults(func=cmd_doctor)
    sub.add_parser("ps", help="list kiwi-fox containers").set_defaults(func=cmd_ps)
    sub.add_parser(
        "reap", help="release gateways whose browser has exited, then kiwi-proxy's sweep"
    ).set_defaults(func=cmd_reap)

    m = sub.add_parser(
        "module",
        help="manage SOCKS5/VPN provider modules (tor, vpn, 9proxy, mysterium) — kiwi-proxy's",
        add_help=False,
    )
    m.add_argument("args", nargs=argparse.REMAINDER, help="as for `kiwi-proxy module`")
    m.set_defaults(func=cmd_module)

    sn = sub.add_parser("snapshot", help="encrypted snapshots of profiles, for your other devices")
    ssub = sn.add_subparsers(dest="snapshot_cmd", required=True)
    for name, text in (
        ("setup", "choose the snapshot folder (kiwi-proxy's, shared by every kiwi app)"),
        ("status", "folder, device, locked or not"),
        ("unlock", "enter the passphrase on this device"),
        ("lock", "forget the passphrase on this device"),
        ("set", "change how snapshots are taken"),
    ):
        ssub.add_parser(name, help=text, add_help=False)
    ssub.add_parser("list", help="the profiles in the folder, and how they relate to here")
    nw = ssub.add_parser("now", help="snapshot stopped profiles now")
    nw.add_argument("refs", nargs="*", metavar="PROFILE", help="default: every stopped profile")
    hi = ssub.add_parser("history", help="the snapshots of one profile")
    hi.add_argument("ref", metavar="PROFILE")
    rs = ssub.add_parser("restore", help="restore a profile from the folder")
    rs.add_argument("ref", metavar="PROFILE")
    rs.add_argument("--id", help="which snapshot (see history); default the newest")
    rs.add_argument("--yes", action="store_true", help="replace this device's copy without asking")
    rs.add_argument("--fetch", action="store_true", help="download its browser engine if missing")
    fg = ssub.add_parser("forget", help="delete every snapshot of a profile from the folder")
    fg.add_argument("ref", metavar="PROFILE")
    fg.add_argument("--yes", action="store_true")
    sn.set_defaults(func=cmd_snapshot)
    return ap


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ["module"]:
        # All of it is kiwi-proxy's, --help included, which kiwi-fox's own
        # parser would take for one of its options.
        return cmd_module(argparse.Namespace(args=argv[1:]))
    if argv[:1] == ["snapshot"] and argv[1:2] and argv[1] in PROXY_SNAPSHOT_COMMANDS:
        # The folder, the passphrase and the settings are shared: kiwi-proxy's.
        if not profile_snapshots.available():
            return _fail(profile_snapshots.NEEDS)
        from kiwi_proxy import cli as proxy_cli

        return proxy_cli.main(argv)
    paths.ensure_tree()
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (
        store.StoreError,
        proxy.EndpointError,
        exits.ExitError,
        gateway.GatewayError,
        podman.PodmanError,
        launch.LaunchError,
        providers.ProviderError,
        *SNAPSHOT_ERRORS,
    ) as exc:
        return _fail(str(exc))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
