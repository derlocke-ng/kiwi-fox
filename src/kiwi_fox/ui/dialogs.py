"""Dialogs: create a profile, show what a profile actually is, and edit one."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

from ..core import dns, geometry, launch, proxy, secrets, store  # noqa: E402
from ..core.engines import fetch as engine_fetch  # noqa: E402
from ..core.engines.camoufox import webgl_report  # noqa: E402
from ..core.fingerprint import (  # noqa: E402
    edit,
    generate,
    validate,
    validate_against,
    webgl,
)
from ..core.fingerprint import windows11 as w11  # noqa: E402
from ..core.fingerprint.validator import check_webgl_mode, check_window_fits, errors  # noqa: E402
from ..core.models import DnsConfig  # noqa: E402
from ..core.paths import profile_dir  # noqa: E402
from . import worker  # noqa: E402

COUNTRIES = ["(from the exit)", "DE", "AT", "CH", "NL", "SE", "FR", "FI", "NO", "DK", "GB", "US"]

# One control decides what a page is told about the graphics card. Each choice
# shows only what it needs underneath, and one row always says, in plain words,
# what websites will see and why.
WEBGL_MODES: list[tuple[str, str]] = [
    ("host", "My graphics card"),
    ("preset", "Another graphics card"),
    ("custom", "Custom text"),
    ("off", "No WebGL"),
    ("raw", "Unchanged (testing)"),
]

CARD_GROUPS: list[tuple[str, str]] = [
    ("nvidia", "NVIDIA GeForce"),
    ("amd", "AMD Radeon"),
    ("intel", "Intel (integrated)"),
]


def _shown_as(series) -> str:
    """The short form of what Firefox reports for a series: "GTX 980, or similar"."""
    return f"{series.device.removeprefix('NVIDIA GeForce ').removeprefix('Intel(R) ')}, or similar"


class GraphicsChooser:
    """The graphics rows of a preferences group, and the choice they hold.

    People think in cards, so cards are what is chosen. Firefox tells a page only
    the group a card is in, and the "Websites will see" row says so every time —
    otherwise "I picked my RTX 4060, why does it say GTX 980?" has no answer on
    screen.
    """

    def __init__(self, group: Adw.PreferencesGroup) -> None:
        self._host_card = webgl.host_card()
        self._card = (webgl.BY_NAME.get(self._host_card or "") or webgl.CARDS[0]).name

        self.mode_row = Adw.ComboRow(title="Graphics card")
        self.mode_row.set_model(Gtk.StringList.new([label for _key, label in WEBGL_MODES]))
        group.add(self.mode_row)

        # Directly under the dropdown, so the consequence of a choice is in view.
        self.summary = Adw.ActionRow(title="Websites will see")
        # Plain text, not markup: this row shows renderer strings and whatever was
        # typed into the custom fields, and one "<" or "&" in markup mode blanks
        # the whole row.
        self.summary.set_use_markup(False)
        self.summary.set_subtitle_lines(0)  # never clip what a page will be told
        self.summary.set_subtitle_selectable(True)
        group.add(self.summary)

        self.exact_row = Adw.SwitchRow(
            title="Show the exact model",
            subtitle="Off, like every Firefox: websites get the group the card is in. On: "
            "one extra field names the card itself — only a Firefox with a hidden "
            "setting changed does that, so it is rarer.",
        )
        self.exact_row.set_subtitle_lines(0)
        self.exact_row.connect("notify::active", self._refresh)
        group.add(self.exact_row)

        self.card_groups: list[Adw.ExpanderRow] = []
        self._radios: dict[str, Gtk.CheckButton] = {}
        first: Gtk.CheckButton | None = None
        for family, title in CARD_GROUPS:
            expander = Adw.ExpanderRow(title=title)
            for card in (c for c in webgl.CARDS if c.family == family):
                row = Adw.ActionRow(
                    title=card.short, subtitle=f"Firefox shows: {_shown_as(card.series)}"
                )
                row.set_use_markup(False)
                radio = Gtk.CheckButton(valign=Gtk.Align.CENTER)
                if first is None:
                    first = radio
                else:
                    radio.set_group(first)
                radio.set_active(card.name == self._card)
                radio.connect("toggled", self._on_card, card.name)
                row.add_prefix(radio)
                row.set_activatable_widget(radio)
                expander.add_row(row)
                self._radios[card.name] = radio
            expander.family = family  # type: ignore[attr-defined]
            group.add(expander)
            self.card_groups.append(expander)

        start = webgl.report("host") or webgl.report("preset", card=self._card)
        self.vendor_row = Adw.EntryRow(title="Vendor")
        self.vendor_row.set_text(start.vendor)
        self.renderer_row = Adw.EntryRow(title="Renderer")
        self.renderer_row.set_text(start.unmasked)
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

    def set_card(self, name: str) -> None:
        self._radios[name].set_active(True)

    def value(self) -> dict[str, object]:
        """-> the Profile fields this control owns."""
        mode = self.mode
        custom, preset = mode == "custom", mode == "preset"
        return {
            "webgl": mode,
            "webgl_card": self._card if preset else None,
            "webgl_series": webgl.BY_NAME[self._card].series.key if preset else None,
            "webgl_exact": self.exact_row.get_active() and mode in ("host", "preset"),
            "webgl_vendor": self.vendor_row.get_text().strip() or None if custom else None,
            "webgl_renderer": self.renderer_row.get_text().strip() or None if custom else None,
        }

    def _told(self):
        v = self.value()
        return webgl.report(
            v["webgl"],
            card=v["webgl_card"],
            series_key=v["webgl_series"],
            exact=bool(v["webgl_exact"]),
            custom_vendor=v["webgl_vendor"],
            custom_renderer=v["webgl_renderer"],
        )

    def problem(self) -> str | None:
        """Why this choice cannot be saved, or None."""
        v = self.value()
        hard = errors(
            check_webgl_mode(v["webgl"], v["webgl_vendor"], v["webgl_renderer"], v["webgl_series"])
        )
        return "; ".join(i.message for i in hard) if hard else None

    def load(self, profile, fp) -> None:
        """Show an existing profile's choice."""
        card = profile.webgl_card
        if card not in self._radios:
            # Chosen before cards could be: any card of the same group reads the same.
            series = webgl.BY_KEY.get(profile.webgl_series or "") or webgl.series_for(
                fp.webgl.renderer
            )
            card = next((c.name for c in webgl.CARDS if c.series is series), None)
        if card:
            self.set_card(card)
        if profile.webgl_vendor:
            self.vendor_row.set_text(profile.webgl_vendor)
        if profile.webgl_renderer:
            self.renderer_row.set_text(profile.webgl_renderer)
        self.exact_row.set_active(profile.webgl_exact)
        self.set_mode(profile.webgl)
        self._refresh()

    # --------------------------------------------------------------- widgets
    def _on_card(self, button: Gtk.CheckButton, name: str) -> None:
        if button.get_active():
            self._card = name
            self._refresh()

    def _refresh(self, *_args) -> None:
        mode = self.mode
        chosen = webgl.BY_NAME[self._card]
        for expander in self.card_groups:
            expander.set_visible(mode == "preset")
            mine = expander.family == chosen.family  # type: ignore[attr-defined]
            expander.set_subtitle(chosen.short if mine else "")
        for row in (self.vendor_row, self.renderer_row):
            row.set_visible(mode == "custom")
        has_card = mode == "preset" or (mode == "host" and bool(self._host_card))
        self.exact_row.set_visible(has_card)
        self.summary.set_subtitle(self._describe(mode))

    def _describe(self, mode: str) -> str:
        if mode == "off":
            return (
                "No WebGL at all, so nothing about the graphics card. That is rare on "
                "Windows and stands out more than any card would."
            )
        if mode == "raw":
            return (
                "Exactly what this Linux machine reports, nothing changed: Linux "
                "wording and limits under a Windows browser. For measuring and "
                "testing — it does not look like Windows."
            )
        if mode == "custom" and (problem := self.problem()):
            return problem
        told = self._told()
        if mode == "custom":
            v = self.value()
            notes = check_webgl_mode("custom", v["webgl_vendor"], v["webgl_renderer"])
            text = f"{told.unmasked}\nwith the limits and extensions of: {told.series.label}"
            return text + "".join(f"\n{note.message}" for note in notes)
        if mode == "host":
            card = self._host_card or "this machine's card (model not measured yet — run Setup)"
        else:
            card = told.card
        if told.exact:
            return f"{told.masked}\nand in the debug field, the exact model:\n{told.unmasked}"
        return (
            f"{told.unmasked}\n\n"
            f"Why not “{card}”? Firefox never shows the exact model. It reports this "
            f"same text for {told.series.covers} — a real one on Windows reads exactly "
            "like this."
        )


def describe_graphics(profile, fp) -> str:
    """What this profile reports as its graphics card, for a details row."""
    label = dict(WEBGL_MODES)[profile.webgl]
    told = webgl_report(fp, profile)
    if told is None:
        return label
    card = f" ({told.card})" if told.card else ""
    text = f"{label}{card}\nWebsites see: {told.masked}"
    return text + (f"\nDebug field: {told.unmasked}" if told.exact else "")


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

        self.language_row = Adw.ComboRow(
            title="Browser language",
            subtitle="the region's own Firefox, or an English one used there",
        )
        self.language_row.set_model(Gtk.StringList.new([label for _key, label in LANGUAGES]))
        identity.add(self.language_row)
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
        language = LANGUAGES[self.language_row.get_selected()][0]
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
                series=graphics["webgl_series"],  # the chosen card's group
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
            profile.language = language  # type: ignore[assignment]
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


LANGUAGES: list[tuple[str, str]] = [
    ("local", "Local"),
    ("english", "English"),
]

APPEARANCES: list[tuple[str, str]] = [
    ("host", "Follow this desktop"),
    ("light", "Light"),
    ("dark", "Dark"),
]
FORMS = ["desktop", "laptop"]


def _combo(title: str, labels: list[str], selected: int = 0, subtitle: str = "") -> Adw.ComboRow:
    row = Adw.ComboRow(title=title, subtitle=subtitle)
    row.set_model(Gtk.StringList.new(labels))
    row.set_selected(max(selected, 0))
    return row


class ProfileEditor(Adw.Dialog):
    """Everything a profile reports, in one place, changeable after creation.

    Nothing is saved unless the whole result is coherent: the same check a launch
    runs. What is not here is not settable — the Windows version, because Firefox
    sends the same user agent for 10 and 11.
    """

    def __init__(self, profile, on_saved=None) -> None:
        super().__init__(title=f"Edit {profile.name}", content_width=660, content_height=780)
        self._profile = profile
        self._fp = fp = store.load_fingerprint(profile.id)
        self._on_saved = on_saved
        page = Adw.PreferencesPage()

        # ------------------------------------------------------------ profile
        group = Adw.PreferencesGroup(
            title="Profile",
            description="Takes effect at the next launch." if launch.running(profile) else "",
        )
        self.name_row = Adw.EntryRow(title="Name")
        self.name_row.set_text(profile.name)
        group.add(self.name_row)
        self._endpoint_before = profile.endpoint.label
        self.endpoint_row = Adw.EntryRow(title="SOCKS5 endpoint")
        self.endpoint_row.set_text(self._endpoint_before)
        group.add(self.endpoint_row)
        self.dns_row = _combo(
            "DNS",
            ["resolver (ad-blocking)", "remote (at the proxy)"],
            int(profile.dns.mode == "remote"),
        )
        group.add(self.dns_row)
        self._upstreams = sorted(dns.UPSTREAMS)
        self.upstream_row = _combo(
            "DNS upstream",
            self._upstreams,
            self._upstreams.index(profile.dns.upstream)
            if profile.dns.upstream in self._upstreams
            else 0,
        )
        group.add(self.upstream_row)
        self.appearance_row = _combo(
            "Appearance",
            [label for _key, label in APPEARANCES],
            [key for key, _label in APPEARANCES].index(profile.appearance),
            "light or dark, for the browser and for what pages are told",
        )
        group.add(self.appearance_row)
        page.add(group)

        # ------------------------------------------------------------ machine
        group = Adw.PreferencesGroup(title="Machine")
        self.form_row = _combo("Kind", FORMS, FORMS.index(fp.form_factor))
        self.form_row.connect("notify::selected", self._on_form)
        group.add(self.form_row)
        self.screen_row = Adw.ComboRow(
            title="Screen", subtitle="only resolutions many real machines report"
        )
        group.add(self.screen_row)
        self._fill_screens(fp.form_factor, (fp.screen.width, fp.screen.height))
        series = webgl.series_for(fp.webgl.renderer)
        self._cores = sorted(set(series.cores if series else ()) | {fp.hardware_concurrency})
        self.cores_row = _combo(
            "CPU cores", [str(c) for c in self._cores], self._cores.index(fp.hardware_concurrency)
        )
        group.add(self.cores_row)
        self.camera_row = Adw.SwitchRow(title="Camera")
        self.camera_row.set_active(bool(fp.media_devices.get("webcams")))
        group.add(self.camera_row)
        self._rates = list(w11.SAMPLE_RATES)
        self.audio_row = _combo(
            "Audio sample rate",
            [f"{r} Hz" for r in self._rates],
            self._rates.index(fp.audio.sample_rate) if fp.audio.sample_rate in self._rates else 0,
        )
        group.add(self.audio_row)
        page.add(group)

        # ------------------------------------------------------------- region
        group = Adw.PreferencesGroup(
            title="Region", description="Language, voices and Accept-Language follow the region."
        )
        self._countries = sorted(w11.REGIONS)
        current = next((c for c in self._countries if w11.REGIONS[c].locale == fp.locale), "")
        self.country_row = _combo(
            "Region",
            [f"{c} — {w11.REGIONS[c].locale}" for c in self._countries],
            self._countries.index(current) if current else 0,
        )
        self.country_row.connect("notify::selected", self._on_country)
        group.add(self.country_row)
        self.timezone_row = Adw.EntryRow(title="Timezone")
        self.timezone_row.set_text(fp.timezone)
        group.add(self.timezone_row)
        self.language_row = _combo(
            "Browser language",
            [label for _key, label in LANGUAGES],
            [key for key, _label in LANGUAGES].index(profile.language),
            "the region's own Firefox, or an English one used there",
        )
        self.language_row.set_subtitle_lines(0)
        group.add(self.language_row)
        page.add(group)

        # -------------------------------------------------------------- fonts
        group = Adw.PreferencesGroup(title="Fonts")
        optional = edit.optional_fonts()
        self.fonts_expander = Adw.ExpanderRow(
            title="Optional fonts",
            subtitle=f"{len(set(fp.fonts) & set(optional))} of {len(optional)} — the Windows 11 "
            "core set is always present",
        )
        self._font_rows: dict[str, Adw.SwitchRow] = {}
        for name in optional:
            row = Adw.SwitchRow(title=name)
            row.set_use_markup(False)
            row.set_active(name in fp.fonts)
            self.fonts_expander.add_row(row)
            self._font_rows[name] = row
        group.add(self.fonts_expander)
        page.add(group)

        # ----------------------------------------------------------- graphics
        group = Adw.PreferencesGroup(
            title="Graphics",
            description="Firefox tells a page the series a card belongs to, never the card.",
        )
        self.graphics = GraphicsChooser(group)
        self.graphics.load(profile, fp)
        page.add(group)

        # --------------------------------------------------------- user agent
        group = Adw.PreferencesGroup(
            title="User agent",
            description="The engine's own is stock Firefox of its version, on Windows. "
            "Windows 10 and 11 cannot be told apart here: Firefox sends the same string "
            "for both.",
        )
        self.ua_row = Adw.EntryRow(title="User agent")
        self.ua_row.set_text(profile.user_agent or fp.ua)
        reset = Gtk.Button(icon_name="edit-undo-symbolic", valign=Gtk.Align.CENTER)
        reset.set_tooltip_text("Back to the engine's own")
        reset.add_css_class("flat")
        reset.connect("clicked", lambda *_: self.ua_row.set_text(fp.ua))
        self.ua_row.add_suffix(reset)
        self.ua_row.connect("changed", self._on_ua)
        group.add(self.ua_row)
        self.ua_note = Adw.ActionRow(use_markup=False, visible=False)
        self.ua_note.set_subtitle_lines(0)
        group.add(self.ua_note)
        page.add(group)
        self._on_ua()

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

    # ------------------------------------------------------------- widgets
    def _fill_screens(self, form: str, current: tuple[int, int]) -> None:
        self._screens = edit.screen_choices(form)
        self.screen_row.set_model(Gtk.StringList.new([edit.screen_label(s) for s in self._screens]))
        sizes = [(s.width, s.height) for s in self._screens]
        self.screen_row.set_selected(sizes.index(current) if current in sizes else 0)

    def _on_form(self, *_args) -> None:
        self._fill_screens(
            FORMS[self.form_row.get_selected()], (self._fp.screen.width, self._fp.screen.height)
        )

    def _on_country(self, *_args) -> None:
        # Follow the region unless a timezone was typed that is neither the old
        # region's nor the fingerprint's.
        zones = {r.timezone for r in w11.REGIONS.values()} | {self._fp.timezone}
        if self.timezone_row.get_text().strip() in zones:
            country = self._countries[self.country_row.get_selected()]
            self.timezone_row.set_text(w11.REGIONS[country].timezone)

    def _on_ua(self, *_args) -> None:
        text = self.ua_row.get_text().strip()
        notes = edit.check_user_agent(text, self._fp.engine_version) if text else []
        self.ua_note.set_visible(bool(notes))
        self.ua_note.set_subtitle("This will stand out: " + "; ".join(notes) + "." if notes else "")

    def _say(self, text: str) -> None:
        self.status_label.set_text(text)
        self.status_label.set_visible(bool(text))

    # ---------------------------------------------------------------- save
    def _fingerprint(self):
        """The fingerprint as the widgets now describe it."""
        new = self._fp
        form = FORMS[self.form_row.get_selected()]
        if form != new.form_factor:
            new = edit.with_form(new, form)
        screen = self._screens[self.screen_row.get_selected()]
        if (screen.width, screen.height) != (new.screen.width, new.screen.height):
            new = edit.with_screen(new, f"{screen.width}x{screen.height}")
        country = self._countries[self.country_row.get_selected()]
        if w11.REGIONS[country].locale != new.locale:
            new = edit.with_region(new, country, keep_timezone=True)
        timezone = self.timezone_row.get_text().strip()
        if timezone != new.timezone:
            new = edit.with_timezone(new, timezone)
        cores = self._cores[self.cores_row.get_selected()]
        if cores != new.hardware_concurrency:
            new = edit.with_cores(new, cores)
        rate = self._rates[self.audio_row.get_selected()]
        if rate != new.audio.sample_rate:
            new = edit.with_audio_rate(new, rate)
        if self.camera_row.get_active() != bool(new.media_devices.get("webcams")):
            new = edit.with_camera(new, self.camera_row.get_active())
        wanted = {name for name, row in self._font_rows.items() if row.get_active()}
        have = set(new.fonts) & set(self._font_rows)
        if wanted != have:
            new = edit.with_fonts(new, add=sorted(wanted - have), remove=sorted(have - wanted))
        return new

    def _on_save(self, *_args) -> None:
        profile = self._profile
        name = self.name_row.get_text().strip()
        if not name:
            return self._say("Give the profile a name.")
        if name != profile.name and store.find_by_name(name):
            return self._say(f"A profile named {name!r} already exists.")
        if problem := self.graphics.problem():
            return self._say(f"Graphics: {problem}")
        try:
            new = self._fingerprint()
        except edit.EditError as exc:
            return self._say(str(exc))
        if hard := errors(validate(new, engine_version=new.engine_version)):
            return self._say("Not saved: " + "; ".join(i.message for i in hard))

        updates: dict[str, object] = {"name": name, **self.graphics.value()}
        updates["appearance"] = APPEARANCES[self.appearance_row.get_selected()][0]
        updates["language"] = LANGUAGES[self.language_row.get_selected()][0]
        ua = self.ua_row.get_text().strip()
        updates["user_agent"] = ua if ua and ua != new.ua else None
        updates["dns"] = profile.dns.model_copy(
            update={
                "mode": "remote" if self.dns_row.get_selected() else "resolver",
                "upstream": self._upstreams[self.upstream_row.get_selected()],
            }
        )
        password = None
        spec = self.endpoint_row.get_text().strip()
        if spec != self._endpoint_before:
            try:
                updates["endpoint"], password = proxy.parse(spec)
            except proxy.ProxyError as exc:
                return self._say(str(exc))

        saved = profile.model_copy(update=updates)
        if new != self._fp:
            store.save_fingerprint(profile.id, new)
        store.save(saved)
        if password:
            secrets.store(profile.id, password, label=f"kiwi-fox {saved.name}")
        self.close()
        if self._on_saved:
            self._on_saved(saved)


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
        machine.add(self.graphics_row)
        for issue in check_window_fits(fp):
            note = _row("Screen and window", issue.message)
            note.set_subtitle_lines(0)
            machine.add(note)
        machine.add(
            _row("Screen", f"{fp.screen.width}x{fp.screen.height} @{fp.screen.device_pixel_ratio}")
        )
        window_row = _row("Window", geometry.describe(profile, fp))
        window_row.set_subtitle_lines(0)
        machine.add(window_row)
        machine.add(_row("Audio", f"{fp.audio.sample_rate} Hz"))
        machine.add(_row("Hardware rendering", "on" if profile.gpu_accel else "off"))
        machine.add(_row("Fonts", f"{len(fp.fonts)} families"))
        machine.add(_row("Voices", ", ".join(v.split(" - ")[0] for v in fp.voices) or "none"))
        page.add(machine)

        ident = Adw.PreferencesGroup(title="Identity")
        ident.add(_row("User agent", profile.user_agent or fp.ua))
        ident.add(_row("Appearance", dict(APPEARANCES)[profile.appearance]))
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
        edit_button = Gtk.Button(label="Edit…")
        edit_button.connect("clicked", self._on_edit)
        header.pack_start(edit_button)
        view = Adw.ToolbarView()
        view.add_top_bar(header)
        view.set_content(page)
        self.set_child(view)

    def _on_edit(self, *_args) -> None:
        parent = self.get_root()

        def saved(profile) -> None:
            if self._on_changed:
                self._on_changed(profile)

        self.close()
        ProfileEditor(self._profile, saved).present(parent)


def _row(title: str, subtitle: str) -> Adw.ActionRow:
    row = Adw.ActionRow(use_markup=False, title=title, subtitle=subtitle)
    row.set_subtitle_selectable(True)
    return row
