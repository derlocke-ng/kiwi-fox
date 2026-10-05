"""Dialogs: create a profile, show what a profile actually is, change its graphics."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

from ..core import dns, launch, proxy, store  # noqa: E402
from ..core.engines import fetch as engine_fetch  # noqa: E402
from ..core.engines.camoufox import webgl_config, webgl_series  # noqa: E402
from ..core.fingerprint import (  # noqa: E402
    generate,
    validate,
    validate_against,
    webgl,
)
from ..core.fingerprint.validator import check_webgl_mode, errors  # noqa: E402
from ..core.models import DnsConfig  # noqa: E402
from ..core.paths import profile_dir  # noqa: E402
from . import worker  # noqa: E402

COUNTRIES = ["(from the exit)", "DE", "AT", "CH", "NL", "SE", "FR", "FI", "NO", "DK", "GB", "US"]

# One control decides what a page is told about the GPU. Each mode shows only
# what it needs underneath: nothing, a list of series, or two text fields.
WEBGL_MODES: list[tuple[str, str]] = [
    ("host", "This machine's GPU"),
    ("preset", "A GPU series I choose"),
    ("custom", "Custom strings"),
    ("off", "No WebGL"),
    ("raw", "Raw — spoof nothing"),
]

HOW = {
    "measured": "measured on this machine",
    "family": "matched by vendor; `kiwi-fox selfcheck NAME --host` measures the exact series",
    "unknown": "this machine's GPU could not be identified",
}


class GraphicsChooser:
    """The graphics rows of a preferences group, and the choice they hold.

    Firefox reports a GPU *series*, never a card, so that is what is chosen here.
    The summary row always says, in the page's own terms, what will be reported.
    """

    def __init__(self, group: Adw.PreferencesGroup) -> None:
        host, self._how = webgl.host_series()
        self._host = host
        self._series = (host or webgl.SERIES[0]).key

        self.mode_row = Adw.ComboRow(title="Reported as")
        self.mode_row.set_model(Gtk.StringList.new([label for _key, label in WEBGL_MODES]))
        group.add(self.mode_row)

        # Directly under the dropdown, so the consequence of a choice is always in
        # view — below a six-row list it needed scrolling to find.
        self.summary = Adw.ActionRow(title="Pages will see")
        # Plain text, not markup: this row shows renderer strings and whatever was
        # typed into the custom fields, and one "<" or "&" in markup mode blanks
        # the whole row.
        self.summary.set_use_markup(False)
        self.summary.set_subtitle_lines(0)  # never clip what a page will be told
        self.summary.set_subtitle_selectable(True)
        group.add(self.summary)

        self.series_rows: list[Adw.ActionRow] = []
        self._radios: dict[str, Gtk.CheckButton] = {}
        first: Gtk.CheckButton | None = None
        for series in webgl.SERIES:
            kind = "integrated" if series.kind == "igpu" else "discrete"
            row = Adw.ActionRow(
                title=series.label,
                subtitle=f"{series.covers}\n{kind} · {webgl.share(series) * 100:.0f}% of "
                "Windows Firefox users",
            )
            row.set_use_markup(False)
            row.set_title_lines(2)
            row.set_subtitle_lines(3)
            radio = Gtk.CheckButton(valign=Gtk.Align.CENTER)
            if first is None:
                first = radio
            else:
                radio.set_group(first)
            radio.set_active(series.key == self._series)
            radio.connect("toggled", self._on_series, series.key)
            row.add_prefix(radio)
            row.set_activatable_widget(radio)
            group.add(row)
            self.series_rows.append(row)
            self._radios[series.key] = radio

        start = host or webgl.SERIES[0]
        self.vendor_row = Adw.EntryRow(title="Vendor")
        self.vendor_row.set_text(start.vendor)
        self.renderer_row = Adw.EntryRow(title="Renderer")
        self.renderer_row.set_text(start.renderer)
        for row in (self.vendor_row, self.renderer_row):
            row.connect("changed", self._refresh)
            group.add(row)

        self.mode_row.connect("notify::selected", self._refresh)
        self._refresh()

    # ------------------------------------------------------------- the choice
    @property
    def mode(self) -> str:
        return WEBGL_MODES[self.mode_row.get_selected()][0]

    def set_mode(self, mode: str) -> None:
        self.mode_row.set_selected([key for key, _label in WEBGL_MODES].index(mode))

    def value(self) -> dict[str, str | None]:
        """-> the four Profile fields: webgl, webgl_series, webgl_vendor, webgl_renderer."""
        mode = self.mode
        custom = mode == "custom"
        return {
            "webgl": mode,
            "webgl_series": self._series if mode == "preset" else None,
            "webgl_vendor": self.vendor_row.get_text().strip() or None if custom else None,
            "webgl_renderer": self.renderer_row.get_text().strip() or None if custom else None,
        }

    def problem(self) -> str | None:
        """Why this choice cannot be saved, or None."""
        v = self.value()
        hard = errors(
            check_webgl_mode(v["webgl"], v["webgl_vendor"], v["webgl_renderer"], v["webgl_series"])
        )
        return "; ".join(i.message for i in hard) if hard else None

    def load(self, profile, fp) -> None:
        """Show an existing profile's choice."""
        frozen = webgl.BY_KEY.get(profile.webgl_series or "") or webgl.series_for(fp.webgl.renderer)
        if frozen:
            self._radios[frozen.key].set_active(True)
        if profile.webgl_vendor:
            self.vendor_row.set_text(profile.webgl_vendor)
        if profile.webgl_renderer:
            self.renderer_row.set_text(profile.webgl_renderer)
        self.set_mode(profile.webgl)
        self._refresh()

    # --------------------------------------------------------------- widgets
    def _on_series(self, button: Gtk.CheckButton, key: str) -> None:
        if button.get_active():
            self._series = key
            self._refresh()

    def _refresh(self, *_args) -> None:
        mode = self.mode
        for row in self.series_rows:
            row.set_visible(mode == "preset")
        for row in (self.vendor_row, self.renderer_row):
            row.set_visible(mode == "custom")
        self.summary.set_subtitle(self._describe(mode))

    def _describe(self, mode: str) -> str:
        if mode == "off":
            return (
                "No WebGL context at all, so nothing about the GPU. Rare on Windows — "
                "it stands out more than any card would."
            )
        if mode == "raw":
            return (
                "This machine's real WebGL strings, limits and extensions. On Linux "
                "that is Mesa's wording under a Windows user agent: for measuring and "
                "testing, not for browsing."
            )
        if mode == "host":
            if not self._host:
                return f"{HOW['unknown']}; the series stored in the profile is used instead."
            return f"{self._host.renderer}\n{self._host.label} — {HOW[self._how]}."
        if mode == "preset":
            return webgl.BY_KEY[self._series].renderer
        if problem := self.problem():
            return problem
        v = self.value()
        notes = check_webgl_mode("custom", v["webgl_vendor"], v["webgl_renderer"])
        base = webgl.resolve("custom", custom_renderer=v["webgl_renderer"])
        text = f"{v['webgl_renderer']}\nwith the limits and extensions of: {base.label}"
        return text + "".join(f"\n{note.message}" for note in notes)


def describe_graphics(profile, fp) -> str:
    """What this profile reports as its GPU, for a details row."""
    label = dict(WEBGL_MODES)[profile.webgl]
    if profile.webgl in ("off", "raw"):
        return label
    series = webgl_series(fp, profile)
    renderer = webgl_config(fp, profile).get("webGl:renderer", "")
    return f"{label}: {series.label if series else '?'}\n{renderer}"


class NewProfileDialog(Adw.Dialog):
    """Create one identity. The exit is probed first so locale and timezone can
    be drawn to match it rather than guessed."""

    def __init__(self, parent: Adw.ApplicationWindow, on_created) -> None:
        super().__init__(title="New profile", content_width=640, content_height=760)
        self._parent = parent
        self._on_created = on_created

        page = Adw.PreferencesPage()
        identity = Adw.PreferencesGroup(title="Identity")
        self.name_row = Adw.EntryRow(title="Name")
        identity.add(self.name_row)

        self.endpoint_row = Adw.EntryRow(title="SOCKS5 endpoint")
        self.endpoint_row.set_text("10.64.0.1:1080")
        identity.add(self.endpoint_row)

        self.country_row = Adw.ComboRow(
            title="Region", subtitle="locale and timezone are drawn to match"
        )
        self.country_row.set_model(Gtk.StringList.new(COUNTRIES))
        identity.add(self.country_row)

        self.form_row = Adw.ComboRow(title="Machine")
        self.form_row.set_model(Gtk.StringList.new(["(random)", "desktop", "laptop"]))
        identity.add(self.form_row)
        page.add(identity)

        graphics = Adw.PreferencesGroup(
            title="Graphics",
            description="Firefox tells a page the series a card belongs to, never the "
            "card. Can be changed later.",
        )
        self.graphics = GraphicsChooser(graphics)
        page.add(graphics)

        network = Adw.PreferencesGroup(
            title="DNS",
            description="The resolver runs in the profile's own namespace and its "
            "upstream leaves through the same exit as the traffic.",
        )
        self.dns_row = Adw.ComboRow(title="Mode")
        self.dns_row.set_model(
            Gtk.StringList.new(["resolver (ad-blocking)", "remote (at the proxy)"])
        )
        network.add(self.dns_row)
        self.upstream_row = Adw.ComboRow(title="Upstream")
        self.upstream_row.set_model(Gtk.StringList.new(sorted(dns.UPSTREAMS)))
        network.add(self.upstream_row)
        page.add(network)

        self.status = Adw.PreferencesGroup()
        self.status_label = Gtk.Label(wrap=True, xalign=0, visible=False)
        self.status_label.add_css_class("dim-label")
        self.status.add(self.status_label)
        page.add(self.status)

        header = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: self.close())
        header.pack_start(cancel)
        self.create_button = Gtk.Button(label="Create")
        self.create_button.add_css_class("suggested-action")
        self.create_button.connect("clicked", self._on_create)
        header.pack_end(self.create_button)

        view = Adw.ToolbarView()
        view.add_top_bar(header)
        view.set_content(page)
        self.set_child(view)

    def _say(self, text: str) -> None:
        self.status_label.set_text(text)
        self.status_label.set_visible(bool(text))

    def _on_create(self, *_args) -> None:
        name = self.name_row.get_text().strip()
        spec = self.endpoint_row.get_text().strip()
        if not name:
            self._say("Give the profile a name.")
            return
        if store.find_by_name(name):
            self._say(f"A profile named {name!r} already exists.")
            return
        try:
            endpoint, password = proxy.parse(spec)
        except proxy.ProxyError as exc:
            self._say(str(exc))
            return
        if problem := self.graphics.problem():
            self._say(f"Graphics: {problem}")
            return

        version = engine_fetch.preferred()
        if not version:
            self._say("No engine installed yet — run Setup first.")
            return

        country = COUNTRIES[self.country_row.get_selected()]
        country = None if country.startswith("(") else country
        form = ["(random)", "desktop", "laptop"][self.form_row.get_selected()]
        form = None if form.startswith("(") else form
        graphics = self.graphics.value()
        mode = "resolver" if self.dns_row.get_selected() == 0 else "remote"
        upstream = sorted(dns.UPSTREAMS)[self.upstream_row.get_selected()]

        self.create_button.set_sensitive(False)
        self._say("Probing the exit…")

        def work():
            probed = country
            exit_info = None
            if probed is None:
                try:
                    exit_info = proxy.preflight(endpoint, password)
                    probed = exit_info.country
                except Exception:  # noqa: BLE001 - fall back to a default region
                    probed = None
            fp = generate(
                engine_version=version,
                country=probed,
                form_factor=form,
                series=graphics["webgl_series"],
                timezone=exit_info.timezone if exit_info else None,
            )
            issues = validate(fp, engine_version=version, exit_country=probed)
            others = [
                store.load_fingerprint(p.id)
                for p in store.list_profiles()
                if (profile_dir(p.id) / "fingerprint.json").exists()
            ]
            issues += validate_against(fp, others)
            if hard := errors(issues):
                raise RuntimeError("; ".join(str(i) for i in hard))
            profile = store.create(
                name,
                endpoint,
                fp,
                password=password,
                dns=DnsConfig(mode=mode, upstream=upstream),
            )
            for field, value in graphics.items():
                setattr(profile, field, value)
            store.save(profile)
            return profile, exit_info

        def done(result) -> None:
            profile, _exit = result
            self.close()
            self._on_created(profile)

        def failed(exc: Exception) -> None:
            self.create_button.set_sensitive(True)
            self._say(f"Could not create the profile: {exc}")

        worker.run(work, done, failed)


class GraphicsDialog(Adw.Dialog):
    """Change what an existing profile reports as its GPU."""

    def __init__(self, profile, on_saved=None) -> None:
        super().__init__(title=f"Graphics — {profile.name}", content_width=640, content_height=680)
        self._profile = profile
        self._on_saved = on_saved
        fp = store.load_fingerprint(profile.id)

        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(
            description="Firefox tells a page the series a card belongs to, never the "
            "card. The rest of the identity is untouched."
            + (" Takes effect at the next launch." if launch.running(profile) else ""),
        )
        self.graphics = GraphicsChooser(group)
        self.graphics.load(profile, fp)
        page.add(group)

        status = Adw.PreferencesGroup()
        self.status_label = Gtk.Label(wrap=True, xalign=0, visible=False)
        self.status_label.add_css_class("dim-label")
        status.add(self.status_label)
        page.add(status)

        header = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: self.close())
        header.pack_start(cancel)
        self.save_button = Gtk.Button(label="Save")
        self.save_button.add_css_class("suggested-action")
        self.save_button.connect("clicked", self._on_save)
        header.pack_end(self.save_button)

        view = Adw.ToolbarView()
        view.add_top_bar(header)
        view.set_content(page)
        self.set_child(view)

    def _on_save(self, *_args) -> None:
        if problem := self.graphics.problem():
            self.status_label.set_text(problem)
            self.status_label.set_visible(True)
            return
        for field, value in self.graphics.value().items():
            setattr(self._profile, field, value)
        store.save(self._profile)
        self.close()
        if self._on_saved:
            self._on_saved(self._profile)


class ProfileDetails(Adw.Dialog):
    """Everything this identity claims to be — the thing worth checking before use."""

    def __init__(self, profile, on_changed=None) -> None:
        super().__init__(title=profile.name, content_width=640, content_height=680)
        self._profile = profile
        self._on_changed = on_changed
        fp = store.load_fingerprint(profile.id)
        page = Adw.PreferencesPage()

        net = Adw.PreferencesGroup(title="Network")
        net.add(_row("Endpoint", profile.endpoint.label))
        net.add(_row("DNS", f"{profile.dns.mode} via {profile.dns.upstream}"))
        if profile.last_exit:
            e = profile.last_exit
            net.add(_row("Last exit", f"{e.ip}  {e.country or '?'} {e.city or ''}  {e.asn or ''}"))
        page.add(net)

        machine = Adw.PreferencesGroup(
            title="Machine", description="Frozen at creation; regenerating is deliberate."
        )
        machine.add(_row("Form factor", fp.form_factor))
        machine.add(_row("CPU cores", str(fp.hardware_concurrency)))
        self.graphics_row = _row("Graphics", describe_graphics(profile, fp))
        self.graphics_row.set_subtitle_lines(4)
        change = Gtk.Button(label="Change…", valign=Gtk.Align.CENTER)
        change.connect("clicked", self._on_change_graphics)
        self.graphics_row.add_suffix(change)
        machine.add(self.graphics_row)
        machine.add(
            _row("Screen", f"{fp.screen.width}x{fp.screen.height} @{fp.screen.device_pixel_ratio}")
        )
        machine.add(_row("Window", f"{fp.window.outer_width}x{fp.window.outer_height}"))
        machine.add(_row("Audio", f"{fp.audio.sample_rate} Hz"))
        machine.add(_row("Hardware rendering", "on" if profile.gpu_accel else "off"))
        machine.add(_row("Fonts", f"{len(fp.fonts)} families"))
        machine.add(_row("Voices", ", ".join(v.split(" - ")[0] for v in fp.voices) or "none"))
        page.add(machine)

        ident = Adw.PreferencesGroup(title="Identity")
        ident.add(_row("User agent", fp.ua))
        ident.add(_row("Locale", f"{fp.locale} / {fp.timezone}"))
        ident.add(_row("Engine", f"camoufox {fp.engine_version}"))
        ident.add(_row("Seed", fp.seed))
        page.add(ident)

        limits = Adw.PreferencesGroup(title="Known limits")
        limits.add(
            _row(
                "What stays this machine's",
                "The frame the GPU actually draws. Pixels read back from a rendered "
                "WebGL scene are identical for every profile on this machine, whichever "
                "series is reported, and so are hardware timings.",
            )
        )
        page.add(limits)

        header = Adw.HeaderBar()
        view = Adw.ToolbarView()
        view.add_top_bar(header)
        view.set_content(page)
        self.set_child(view)

    def _on_change_graphics(self, *_args) -> None:
        def saved(profile) -> None:
            fp = store.load_fingerprint(profile.id)
            self.graphics_row.set_subtitle(describe_graphics(profile, fp))
            if self._on_changed:
                self._on_changed(profile)

        GraphicsDialog(self._profile, saved).present(self)


def _row(title: str, subtitle: str) -> Adw.ActionRow:
    row = Adw.ActionRow(use_markup=False, title=title, subtitle=subtitle)
    row.set_subtitle_selectable(True)
    return row
