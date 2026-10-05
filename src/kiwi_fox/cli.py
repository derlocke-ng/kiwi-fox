"""kiwi-fox command line. The GUI is a layer over this; the CLI is the truth."""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .core import dns, geometry, gpu, launch, paths, podman, proxy, secrets, store
from .core.engines import fetch as engine_fetch
from .core.fingerprint import edit, generate, validate, validate_against, webgl
from .core.fingerprint import windows11 as w11
from .core.fingerprint.validator import check_webgl_mode as validate_webgl
from .core.fingerprint.validator import check_window_fits, errors
from .core.models import DnsConfig, Fingerprint, Profile

WEBGL_MODES = ("host", "preset", "custom", "off", "raw")


def _p(*args: object) -> None:
    print(*args)


def _fail(msg: str) -> int:
    print(f"kiwi-fox: {msg}", file=sys.stderr)
    return 1


# ------------------------------------------------------------------ commands
def cmd_new(a: argparse.Namespace) -> int:
    endpoint, password = proxy.parse(a.endpoint)
    endpoint.module = a.module
    endpoint.lease = a.lease
    version = a.engine_version or engine_fetch.preferred()
    if not version:
        return _fail("no engine installed; run `kiwi-fox engine fetch` first")

    try:
        mode, card, series = _webgl_choice(
            a.webgl, a.card, a.series, a.webgl_vendor, a.webgl_renderer, family=a.gpu_family
        )
    except ValueError as exc:
        return _fail(str(exc))
    if hard := errors(validate_webgl(mode, a.webgl_vendor, a.webgl_renderer, series)):
        return _fail("; ".join(i.message for i in hard))

    country = a.country
    exit_timezone = None
    if not country and not a.no_probe:
        try:
            info = proxy.preflight(endpoint, password)
            country = info.country
            exit_timezone = info.timezone
            _p(f"exit: {info.ip} {info.country or '?'} {info.city or ''} ({info.timezone or '?'})")
        except Exception as exc:  # noqa: BLE001
            _p(f"warning: could not probe the exit ({exc}); falling back to --country")

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

    profile = store.create(
        a.name,
        endpoint,
        fp,
        password=password,
        dns=DnsConfig(mode=a.dns_mode, upstream=a.upstream),
    )
    profile.webgl = mode  # type: ignore[assignment]
    profile.webgl_series = series
    profile.webgl_card = card
    profile.webgl_exact = bool(a.exact) and mode in ("host", "preset")
    profile.webgl_vendor = a.webgl_vendor if mode == "custom" else None
    profile.webgl_renderer = a.webgl_renderer if mode == "custom" else None
    profile.appearance = a.appearance
    profile.language = a.language
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
    _p(f"  exit    : {endpoint.label}")
    return 0


def cmd_list(a: argparse.Namespace) -> int:
    profiles = store.list_profiles()
    if not profiles:
        _p("no profiles yet — `kiwi-fox new <name> <endpoint>`")
        return 0
    _p(f"{'NAME':16} {'EXIT':24} {'COUNTRY':8} {'STATE':9} ID")
    for p in profiles:
        state = "running" if launch.running(p) else "stopped"
        country = (p.last_exit.country if p.last_exit else None) or "-"
        _p(f"{p.name:16} {p.endpoint.label:24} {country:8} {state:9} {p.id[:8]}")
    return 0


def cmd_show(a: argparse.Namespace) -> int:
    p = store.resolve_ref(a.ref)
    fp = store.load_fingerprint(p.id)
    _p(f"{p.name}  ({p.id})")
    _p(f"  created   {p.created:%Y-%m-%d %H:%M}  last used {p.last_used or 'never'}")
    _p(f"  endpoint  {p.endpoint.label}  auth={'yes' if p.endpoint.username else 'no'}")
    _p(f"  dns       {p.dns.mode} upstream={p.dns.upstream} lists={','.join(p.dns.blocklists)}")
    if p.last_exit:
        e = p.last_exit
        _p(
            f"  last exit {e.ip} {e.country or '?'} {e.city or ''} asn={e.asn or '?'} at {e.seen:%Y-%m-%d %H:%M}"
        )
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
        fp = store.load_fingerprint(p.id)
        from .core.engines import get_engine

        issues = validate(
            fp,
            engine_version=fp.engine_version,
            exit_country=p.last_exit.country if p.last_exit else None,
            prefs=get_engine(fp.engine).prefs(fp, p),  # type: ignore[attr-defined]
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
    _p(f"gateway {res.gateway}")
    _p(f"browser {res.browser}")
    if a.wait:
        _p("waiting for the browser to exit (ctrl-c detaches without tearing down)")
        try:
            code = launch.wait_and_teardown(p)
        except KeyboardInterrupt:
            _p("detached; the profile keeps running")
            return 0
        _p(f"browser exited ({code}); namespace torn down")
    return 0


def cmd_stop(a: argparse.Namespace) -> int:
    for ref in a.refs or [p.name for p in store.list_profiles()]:
        p = store.resolve_ref(ref)
        launch.stop(p)
        _p(f"stopped {p.name}")
    return 0


def cmd_delete(a: argparse.Namespace) -> int:
    p = store.resolve_ref(a.ref)
    if not a.yes:
        return _fail(f"this removes {p.name}; pass --yes to confirm")
    launch.stop(p)
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

    if a.engine_cmd == "list":
        for v in engine_fetch.installed():
            state = (
                "search disabled (run `kiwi-fox engine repair`)"
                if engine_fetch.search_is_disabled(engine_fetch.target_dir(v))
                else "search ok"
            )
            _p(f"camoufox {v}  {paths.engines_dir() / f'camoufox-{v}'}  [{state}]")
        if not engine_fetch.installed():
            _p("none installed")
        return 0

    def progress(done: int, total: int) -> None:
        if total:
            pct = done * 100 // total
            print(f"\rdownloading {done >> 20} / {total >> 20} MiB ({pct}%)", end="", flush=True)

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


def cmd_set(a: argparse.Namespace) -> int:
    """Change what a profile reports. Nothing is saved unless all of it is coherent."""
    profile = store.resolve_ref(a.ref)
    fp = store.load_fingerprint(profile.id)
    new = fp
    try:
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
    password = None
    if a.endpoint:
        endpoint, password = proxy.parse(a.endpoint)
        updates["endpoint"] = endpoint
    if a.dns_mode or a.upstream:
        updates["dns"] = profile.dns.model_copy(
            update={k: v for k, v in (("mode", a.dns_mode), ("upstream", a.upstream)) if v}
        )

    changed = new != fp or bool(updates)
    if changed:
        issues = validate(new, engine_version=new.engine_version)
        if hard := errors(issues):
            for issue in hard:
                _p(f"  {issue}")
            return _fail("that would make the profile incoherent; nothing was changed")
        candidate = profile.model_copy(update=updates)
        if new != fp:
            store.save_fingerprint(profile.id, new)
        store.save(candidate)
        if password:
            secrets.store(profile.id, password, label=f"kiwi-fox {candidate.name}")
        profile, fp = candidate, new
    cmd_show(argparse.Namespace(ref=profile.id))
    for issue in check_window_fits(fp) + _ua_issues(profile, fp):
        _p(f"  {issue}")
    if not changed:
        _p("")
        _p("nothing changed — pass what to change, e.g. --screen 2560x1440; see `kiwi-fox set -h`")
        _p(
            "  screens : "
            + ", ".join(edit.screen_label(s) for s in edit.screen_choices(fp.form_factor))
        )
        _p("  regions : " + " ".join(sorted(w11.REGIONS)))
    elif launch.running(profile):
        _p("  (running — takes effect at the next launch)")
    return 0


def cmd_fonts(a: argparse.Namespace) -> int:
    from .core.fingerprint import fonts

    have = set(store.load_fingerprint(store.resolve_ref(a.ref).id).fonts) if a.ref else set()
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


def cmd_setup(a: argparse.Namespace) -> int:
    from .core import setup

    try:
        steps = setup.run(progress=lambda m: _p(f"  {m}"), engine_version=a.engine_version)
    except setup.SetupError as exc:
        return _fail(str(exc))
    _p("")
    for step in steps:
        _p(f"  {step}")
    _p("\nReady — create a profile with `kiwi-fox new <name> <endpoint>`")
    return 0


def cmd_doctor(a: argparse.Namespace) -> int:
    ok = True
    _p(f"podman        {podman.version() if podman.available() else 'MISSING'}")
    ok &= podman.available()
    _p(
        f"secret-tool   {'yes' if secrets.available() else 'MISSING (credentials cannot be stored)'}"
    )
    engines = engine_fetch.installed()
    _p(f"engines       {', '.join(engines) if engines else 'none — run `kiwi-fox engine fetch`'}")
    ok &= bool(engines)
    import os

    wayland = os.environ.get("WAYLAND_DISPLAY")
    _p(f"wayland       {wayland or 'none (no window can open)'}")
    stamps = dns.load_stamps()
    _p(f"dns stamps    {len(stamps) or 'none — run `kiwi-fox dns sync`'}")
    blocklist = paths.blocklists_dir() / "blocked-names.txt"
    _p(f"blocklist     {blocklist if blocklist.exists() else 'none — run `kiwi-fox dns update`'}")
    from .core import setup

    for image, name in setup.IMAGES:
        state = setup.image_state(image, name) if podman.available() else "missing"
        note = {
            "current": "yes",
            "stale": "outdated — built by an earlier version; run `kiwi-fox setup`",
            "missing": "MISSING — run `kiwi-fox setup`",
        }[state]
        _p(f"image         {image} {note}")
        ok &= state != "missing"
    _p(f"profiles      {len(store.list_profiles())}")
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
    rows = podman.ps()
    if not rows:
        _p("no kiwi-fox containers")
        return 0
    for c in rows:
        names = ",".join(c.get("Names") or [])
        _p(f"{names:28} {c.get('State', '?'):10} {c.get('Image', '?')}")
    return 0


# -------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="kiwi-fox", description=__doc__)
    ap.add_argument("--version", action="version", version=f"kiwi-fox {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    n = sub.add_parser("new", help="create a profile")
    n.add_argument("name")
    n.add_argument("endpoint", help="socks5://user:pass@host:port | host:port[:user:pass]")
    n.add_argument("--country", help="two-letter code; probed from the exit when omitted")
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
    n.add_argument("--module", help="provider module this endpoint came from")
    n.add_argument("--lease", help="module lease id (9proxy port, myst provider_id)")
    n.add_argument("--dns-mode", choices=["resolver", "remote"], default="resolver")
    n.add_argument("--upstream", choices=sorted(dns.UPSTREAMS), default=dns.DEFAULT_UPSTREAM)
    n.add_argument("--no-probe", action="store_true", help="skip the exit probe")
    n.set_defaults(func=cmd_new)

    sub.add_parser("list", help="list profiles").set_defaults(func=cmd_list)

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
    r.set_defaults(func=cmd_run)

    st = sub.add_parser("stop", help="stop profiles (all when none given)")
    st.add_argument("refs", nargs="*")
    st.set_defaults(func=cmd_stop)

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
    ef.add_argument("--prerelease", action="store_true", help="consider beta releases too")
    ef.add_argument("--force", action="store_true")
    esub.add_parser("list")
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

    dn = sub.add_parser("dns", help="resolver stamps and blocklists")
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
    se.add_argument("--endpoint", help="a different SOCKS5 exit")
    se.add_argument("--dns-mode", choices=["resolver", "remote"])
    se.add_argument("--upstream", choices=sorted(dns.UPSTREAMS))
    se.set_defaults(func=cmd_set)

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
        "setup", help="first-run setup: images, engine, tweaks, GPU helpers, blocklists"
    )
    su.add_argument("--engine-version", help="pin a specific Camoufox version")
    su.set_defaults(func=cmd_setup)

    sub.add_parser("doctor", help="check the environment").set_defaults(func=cmd_doctor)
    sub.add_parser("ps", help="list kiwi-fox containers").set_defaults(func=cmd_ps)
    sub.add_parser("reap", help="tear down gateways whose browser has exited").set_defaults(
        func=cmd_reap
    )
    return ap


def main(argv: list[str] | None = None) -> int:
    paths.ensure_tree()
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (store.StoreError, proxy.ProxyError, podman.PodmanError, launch.LaunchError) as exc:
        return _fail(str(exc))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
