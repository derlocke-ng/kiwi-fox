"""Engine versions in the window: the engines dialog (mock-up 09), the Engines
preferences page (mock-up 04), and one profile's version (pin, follow, move)."""

from __future__ import annotations

import contextlib

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from ..core import engine_versions as ev  # noqa: E402
from ..core import settings  # noqa: E402
from ..core.engines import TITLES, installed_versions  # noqa: E402
from ..core.engines import fetch as camoufox_fetch  # noqa: E402
from . import worker  # noqa: E402
from .help import APP, explain  # noqa: E402

OLDER_SHOWN = 12


def _names(profiles, most: int = 3) -> str:
    names = [
        p.name + (" (pinned)" if p.engine != "camoufox" and p.engine_version else "")
        for p in profiles
    ]
    if len(names) <= most:
        return ", ".join(names)
    return f"{', '.join(names[:most])} and {len(names) - most} more"


def _alert(parent, heading: str, body: str) -> None:
    dialog = Adw.AlertDialog(heading=heading, body=body)
    dialog.add_response("close", "Close")
    dialog.present(parent)


# ------------------------------------------------------------------- dialog
class EnginesDialog(Adw.Dialog):
    """Every version of each engine: installed or not, who uses it, Install and
    Remove; older releases behind an expander; Camoufox's search repair per
    version."""

    def __init__(self, on_setup=None, on_changed=None) -> None:
        super().__init__(title="Browser engines", content_width=640, content_height=720)
        self._on_setup = on_setup
        self._on_changed = on_changed
        self._busy: set[tuple[str, str]] = set()
        header = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)
        close = Gtk.Button(label="Close")
        close.connect("clicked", lambda *_: self.close())
        header.pack_start(close)
        self.look = Gtk.Button(label="Look for new versions")
        self.look.connect("clicked", lambda *_: self._load(refresh=True))
        header.pack_end(self.look)
        self.page = Adw.PreferencesPage()
        self.groups: dict[str, Adw.PreferencesGroup] = {}
        for engine in ev.ENGINES:
            group = Adw.PreferencesGroup(title=TITLES[engine])
            self.page.add(group)
            self.groups[engine] = group
        explain(
            self.groups["camoufox"],
            "Each profile runs one of these, mounted read-only. Firefox and Tor Browser "
            "are checked against their publishers' signing keys before they are installed. "
            "A version a profile uses cannot be removed; installing one never removes another.",
            app=APP,
        )
        view = Adw.ToolbarView()
        view.add_top_bar(header)
        view.set_content(self.page)
        self.set_child(view)
        self._rows: list[Gtk.Widget] = []
        self._load()

    # ------------------------------------------------------------- loading
    def _load(self, *, refresh: bool = False) -> None:
        self.look.set_sensitive(False)

        def work():
            out = {}
            for engine in ev.ENGINES:
                rels = ev.releases(engine, refresh=refresh)
                have = installed_versions(engine)
                users = {v: ev.users(engine, v) for v in have}
                out[engine] = (rels, have, users, ev.newest(engine))
            return out

        def done(data) -> None:
            self.look.set_sensitive(True)
            self._show(data)

        def failed(exc: Exception) -> None:
            self.look.set_sensitive(True)
            _alert(self, "Could not list the versions", str(exc))

        worker.run(work, done, failed)

    def _show(self, data) -> None:
        for row in self._rows:
            if row.get_parent() is not None:
                self._remove_row(row)
        self._rows = []
        for engine, (rels, have, users, newest) in data.items():
            group = self.groups[engine]
            default = ev.default_for(engine)
            current = [r for r in rels if r.version in have or r.version == newest]
            if not current and rels:
                current = [rels[0]]
            older = [r for r in rels if r not in current][:OLDER_SHOWN]
            for rel in current:
                row = self._row(engine, rel, have, users, newest, default)
                group.add(row)
                self._rows.append(row)
            if older:
                expander = Adw.ExpanderRow(title="Older releases", use_markup=False)
                shown = [r.version for r in older]
                expander.set_subtitle(
                    ", ".join(shown[:2]) + (f" and {len(shown) - 2} more" if len(shown) > 2 else "")
                )
                for rel in older:
                    expander.add_row(self._row(engine, rel, have, users, newest, default))
                group.add(expander)
                self._rows.append(expander)
            if not rels:
                row = Adw.ActionRow(
                    title="No release list", subtitle="the publisher is out of reach"
                )
                group.add(row)
                self._rows.append(row)

    def _remove_row(self, row) -> None:
        parent = row.get_parent()
        while parent is not None and not isinstance(parent, Adw.PreferencesGroup):
            parent = parent.get_parent()
        if parent is not None:
            parent.remove(row)

    def _row(self, engine, rel, have, users, newest, default) -> Adw.ActionRow:
        v = rel.version
        installed = v in have
        bits = ["installed" if installed else "not installed"]
        if v == newest:
            bits.insert(0, "newest release")
        if rel.beta:
            bits.append("beta")
        if installed and engine != "camoufox":
            bits.append("signature verified")
        if engine == "camoufox" and installed and (default or camoufox_fetch.preferred()) == v:
            bits.append("new profiles use it")
        elif engine != "camoufox" and default == v:
            bits.append("profiles without a pin use it")
        if users.get(v):
            bits.append(_names(users[v]))
        row = Adw.ActionRow(title=v, use_markup=False)
        row.set_subtitle(" · ".join(bits))
        row.set_subtitle_lines(0)
        if (
            engine == "camoufox"
            and installed
            and camoufox_fetch.search_is_disabled(camoufox_fetch.target_dir(v))
        ):
            repair = Gtk.Button(label="Repair search", valign=Gtk.Align.CENTER)
            repair.set_tooltip_text(
                "This build's address bar cannot search; fix it (keeps a backup)"
            )
            repair.connect("clicked", self._on_repair, v, row)
            row.add_suffix(repair)
        button = Gtk.Button(label="Remove" if installed else "Install", valign=Gtk.Align.CENTER)
        button.connect(
            "clicked", self._on_remove if installed else self._on_install, engine, v, row
        )
        row.add_suffix(button)
        return row

    # ------------------------------------------------------------- actions
    def _changed(self) -> None:
        self._load()
        if self._on_changed:
            self._on_changed()

    def _on_install(self, button, engine: str, version: str, row) -> None:
        button.set_sensitive(False)
        row.set_subtitle("downloading…")

        def progress(done: int, total: int) -> None:
            if total:
                GLib.idle_add(row.set_subtitle, f"downloading {done >> 20} of {total >> 20} MiB…")

        def failed(exc: Exception) -> None:
            button.set_sensitive(True)
            row.set_subtitle(f"could not install: {exc}")

        worker.run(
            lambda: ev.install(engine, version, progress=progress),
            lambda _v: self._changed(),
            failed,
        )

    def _on_remove(self, button, engine: str, version: str, row) -> None:
        used = ev.users(engine, version)
        if used:
            _alert(
                self,
                f"{TITLES[engine]} {version} is in use",
                f"{_names(used, 10)} use{'s' if len(used) == 1 else ''} it. Move or pin "
                "them to another version first.",
            )
            return
        dialog = Adw.AlertDialog(
            heading=f"Remove {TITLES[engine]} {version}?",
            body="No profile uses it. It can be installed again later.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("remove", "Remove")
        dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)

        def on_response(_d, response: str) -> None:
            if response != "remove":
                return
            worker.run(
                lambda: ev.remove(engine, version),
                lambda _r: self._changed(),
                lambda exc: _alert(self, "Could not remove", str(exc)),
            )

        dialog.connect("response", on_response)
        dialog.present(self)

    def _on_repair(self, button, version: str, row) -> None:
        button.set_sensitive(False)
        worker.run(
            lambda: camoufox_fetch.repair_search(camoufox_fetch.target_dir(version)),
            lambda _r: self._changed(),
            lambda exc: (button.set_sensitive(True), row.set_subtitle(f"could not repair: {exc}")),
        )


# ------------------------------------------------------------------- page
class EnginesPage(Adw.PreferencesPage):
    """Preferences → Engines (mock-up 04): per engine what is installed, what new
    or unpinned profiles use, the newest release; and what a new release does."""

    def __init__(self, open_dialog) -> None:
        super().__init__(title="Engines", icon_name="applications-internet-symbolic")
        self._open_dialog = open_dialog
        group = Adw.PreferencesGroup(title="New releases")
        self.mode_row = Adw.ComboRow(
            title="When a new version is out",
            model=Gtk.StringList.new(
                ["Tell me, and I install it", "Install it by itself", "Do nothing"]
            ),
        )
        explain(
            self.mode_row,
            "Kiwi Fox looks once a day. A new version never replaces an old one: a Camoufox "
            "profile stays on its version until you move it, and a pinned Firefox or Tor "
            "Browser profile stays on its pin.",
            app=APP,
        )
        modes = ["tell", "auto", "off"]
        self.mode_row.set_selected(modes.index(settings.load().engine_updates))
        self.mode_row.connect("notify::selected", self._on_mode, modes)
        group.add(self.mode_row)
        self.add(group)
        self.groups: dict[str, Adw.PreferencesGroup] = {}
        for engine in ev.ENGINES:
            g = Adw.PreferencesGroup(title=TITLES[engine])
            self.add(g)
            self.groups[engine] = g
        self._built: list[tuple[Adw.PreferencesGroup, Gtk.Widget]] = []
        worker.run(self._collect, self._show, lambda _e: None)

    def _on_mode(self, row, _param, modes) -> None:
        s = settings.load()
        s.engine_updates = modes[row.get_selected()]
        settings.save(s)

    @staticmethod
    def _collect():
        out = {}
        for engine in ev.ENGINES:
            have = installed_versions(engine)
            out[engine] = (have, {v: ev.users(engine, v) for v in have}, ev.newest(engine))
        return out

    def _show(self, data) -> None:
        for group, row in self._built:
            group.remove(row)
        self._built = []
        for engine, (have, users, newest) in data.items():
            group = self.groups[engine]

            def add(row, group=group):
                group.add(row)
                self._built.append((group, row))

            installed = Adw.ActionRow(title="Installed", use_markup=False)
            parts = []
            for v in have:
                n = len(users[v])
                pinned = sum(1 for p in users[v] if p.engine != "camoufox" and p.engine_version)
                tail = f"{n} profile{'s' if n != 1 else ''}" + (
                    f", {pinned} pinned" if pinned else ""
                )
                parts.append(f"{v} ({tail})")
            installed.set_subtitle(" · ".join(parts) or "none")
            installed.set_subtitle_lines(0)
            manage = Gtk.Button(label="Manage…", valign=Gtk.Align.CENTER)
            manage.connect("clicked", lambda *_: self._open_dialog())
            installed.add_suffix(manage)
            add(installed)

            if have:
                choices = (
                    [("", "Preferred")] if engine == "camoufox" else [("", "Newest installed")]
                ) + [(v, v) for v in reversed(have)]
                title = "New profiles use" if engine == "camoufox" else "Profiles without a pin use"
                combo = Adw.ComboRow(
                    title=title, model=Gtk.StringList.new([lbl for _k, lbl in choices])
                )
                keys = [k for k, _l in choices]
                current = ev.default_for(engine)
                combo.set_selected(keys.index(current) if current in keys else 0)
                combo.connect("notify::selected", self._on_default, engine, keys)
                if engine == "camoufox":
                    explain(
                        combo,
                        "A Camoufox profile stays on the version its fingerprint was made for "
                        "until you move it (a profile's menu, Version…).",
                        app=APP,
                    )
                elif engine == "torbrowser":
                    explain(
                        combo,
                        "Old Tor Browser versions stand out among Tor users and miss security "
                        "fixes: let profiles follow the newest unless you must stay.",
                        app=APP,
                    )
                add(combo)

            if newest:
                latest = Adw.ActionRow(title="Newest release", use_markup=False)
                latest.set_subtitle(
                    newest + (" · installed" if newest in have else " · not installed")
                )
                if newest not in have:
                    install = Gtk.Button(label="Install", valign=Gtk.Align.CENTER)
                    install.connect("clicked", self._on_install, engine, newest, latest)
                    latest.add_suffix(install)
                add(latest)

    def _on_default(self, row, _param, engine: str, keys: list[str]) -> None:
        with contextlib.suppress(ev.VersionError):
            ev.set_default(engine, keys[row.get_selected()])

    def _on_install(self, button, engine: str, version: str, row) -> None:
        button.set_sensitive(False)
        row.set_subtitle(f"{version} · downloading…")

        def progress(done: int, total: int) -> None:
            if total:
                GLib.idle_add(row.set_subtitle, f"{version} · {done >> 20} of {total >> 20} MiB…")

        worker.run(
            lambda: ev.install(engine, version, progress=progress),
            lambda _v: worker.run(self._collect, self._show, lambda _e: None),
            lambda exc: (button.set_sensitive(True), row.set_subtitle(f"could not install: {exc}")),
        )


# --------------------------------------------------------------- a profile
class VersionDialog(Adw.Dialog):
    """One profile's engine version: follow or pin (Firefox, Tor Browser), or move
    (Camoufox, checked against its fingerprint)."""

    def __init__(self, profile, on_done) -> None:
        super().__init__(title=f"{profile.name}: version", content_width=480, content_height=460)
        self._profile = profile
        self._on_done = on_done
        engine = profile.engine
        have = list(reversed(installed_versions(engine)))
        header = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: self.close())
        header.pack_start(cancel)
        self.use = Gtk.Button(label="Move" if engine == "camoufox" else "Use")
        self.use.add_css_class("suggested-action")
        self.use.connect("clicked", self._on_use)
        header.pack_end(self.use)
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(
            title=TITLES[engine],
            description=f"now {ev.version_of(profile) or 'none installed'}",
        )
        if engine == "camoufox":
            explain(
                group,
                "Moving checks that the profile's fingerprint fits the other version; "
                "nothing is changed when it does not. Going back is one more move.",
                app=APP,
            )
        self._choices: list[str | None] = ([] if engine == "camoufox" else [None]) + have
        first = None
        current = profile.engine_version if engine != "camoufox" else ev.version_of(profile)
        for choice in self._choices:
            title = "Follow the newest installed" if choice is None else choice
            row = Adw.ActionRow(title=title, use_markup=False)
            if choice is not None and (n := len(ev.users(engine, choice))):
                row.set_subtitle(f"{n} profile{'s' if n != 1 else ''}")
            check = Gtk.CheckButton(valign=Gtk.Align.CENTER, active=choice == current)
            if first is None:
                first = check
            else:
                check.set_group(first)
            check.choice = choice  # type: ignore[attr-defined]
            row.add_prefix(check)
            row.set_activatable_widget(check)
            group.add(row)
            if first is check and current not in self._choices:
                check.set_active(True)
        self._first = first
        self.note = Adw.Banner(revealed=False)
        page.add(group)
        view = Adw.ToolbarView()
        view.add_top_bar(header)
        view.add_top_bar(self.note)
        view.set_content(page)
        self.set_child(view)

    def _iter_checks(self):
        stack = [self.get_child()]
        while stack:
            w = stack.pop()
            if w is None:
                continue
            if isinstance(w, Gtk.CheckButton):
                yield w
            stack += [w.get_next_sibling(), w.get_first_child()]

    def _on_use(self, *_args) -> None:
        choice = next((c.choice for c in self._iter_checks() if c.get_active()), None)  # type: ignore[attr-defined]
        profile = self._profile

        def work():
            if profile.engine == "camoufox":
                refused, warnings = ev.move(profile, choice)
                return refused, warnings
            _p, warnings = ev.pin(profile, choice)
            return [], warnings

        def done(result) -> None:
            refused, warnings = result
            if refused:
                self.note.set_title("Not moved: " + refused[0])
                self.note.set_revealed(True)
                return
            self.close()
            self._on_done(warnings)

        worker.run(
            work, done, lambda exc: (self.note.set_title(str(exc)), self.note.set_revealed(True))
        )
