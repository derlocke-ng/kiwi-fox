"""Main window: the profile list, and the setup state behind it."""

from __future__ import annotations

import contextlib
import json

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402
from kiwi_proxy import exits, podman  # noqa: E402
from kiwi_proxy import paths as proxy_paths  # noqa: E402

from ..core import launch, modules, paths, secrets, settings, store  # noqa: E402
from ..core import snapshots as profile_snapshots  # noqa: E402
from ..core.engines import TITLES, installed_versions  # noqa: E402
from ..core.store import grouped_by_tag  # noqa: E402
from . import worker  # noqa: E402
from .dialogs import (  # noqa: E402
    NewProfileDialog,
    ProfileDetails,
    ProfileEditor,
    exit_label,
)
from .engines import EnginesDialog, EnginesPage, VersionDialog  # noqa: E402
from .help import APP, explain, widen  # noqa: E402

REFRESH_SECONDS = 4
# How often the snapshot folder is looked at (in window ticks): a sync client
# brings new snapshots now and then, not every few seconds.
SNAPSHOT_TICKS = 5

if profile_snapshots.available():
    from kiwi_proxy import snapshots as snap  # noqa: E402
    from kiwi_proxy.ui import snapshots as snapshot_ui  # noqa: E402
else:  # pragma: no cover - kiwi-proxy older than 0.8
    snap = snapshot_ui = None
try:
    from kiwi_proxy.ui import storage as storage_ui  # noqa: E402
except ImportError:  # pragma: no cover - kiwi-proxy older than 0.8.2
    storage_ui = None
PROXY_APP_ID = "eu.kiwinetwork.KiwiProxy"


# A window large enough for the largest dialog (a profile editor is 660×780) to open
# at its own size instead of being squeezed; the size it had when last closed wins.
DEFAULT_SIZE = (1040, 840)
MIN_SIZE = (640, 480)


def saved_geometry() -> tuple[int, int, bool]:
    """(width, height, maximized) from config/window.json, else the default."""
    try:
        d = json.loads((paths.config_dir() / "window.json").read_text())
        width = max(int(d["width"]), MIN_SIZE[0])
        height = max(int(d["height"]), MIN_SIZE[1])
        return width, height, bool(d.get("maximized"))
    except (OSError, ValueError, KeyError, TypeError):
        return DEFAULT_SIZE[0], DEFAULT_SIZE[1], False


def remember_geometry(window) -> None:
    """Keep the window's size for the next start. GTK 4 tracks the user's resizing
    in the default size, and keeps the un-maximized one while maximized."""
    width, height = window.get_default_size()
    try:
        paths.config_dir().mkdir(parents=True, exist_ok=True)
        (paths.config_dir() / "window.json").write_text(
            json.dumps({"width": width, "height": height, "maximized": window.is_maximized()})
        )
    except OSError:
        pass


class Window(Adw.ApplicationWindow):
    def __init__(self, **kwargs) -> None:
        width, height, maximized = saved_geometry()
        super().__init__(default_width=width, default_height=height, title="Kiwi Fox", **kwargs)
        if maximized:
            self.maximize()
        self.connect("close-request", self._on_close_request)
        self._rows: dict[str, Adw.ActionRow] = {}
        self._busy: set[str] = set()
        self._busy_what: dict[str, str] = {}  # profile id -> open | quit | up | stop
        # Snapshots: what the folder says about each profile here, and what it
        # holds that is not here; which profiles ran at the last tick (a browser
        # that ended since gets its snapshot).
        self._relations: dict[str, object] = {}
        self._in_use: dict[str, list] = {}
        self._away: list = []
        self._away_rows: list[Adw.ActionRow] = []
        self._snap_polling = False
        self._ticks = 0
        self._was_running: set[str] = set()
        self._silent: set[str] = set()  # profiles whose VPN is not answering

        self.toasts = Adw.ToastOverlay()
        header = Adw.HeaderBar()

        new_button = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="New profile")
        new_button.connect("clicked", self._on_new)
        header.pack_start(new_button)

        menu = Gio.Menu()
        menu.append("Preferences", "win.preferences")
        menu.append("Browser engines", "win.engines")
        if snapshot_ui is not None:
            menu.append("Snapshot everything now", "win.snapshot-all")
        menu.append("Set up environment", "win.setup")
        menu.append("Check environment", "win.doctor")
        if storage_ui is not None:
            menu.append("Check and repair", "win.storage")
        menu.append("Stop everything", "win.stop-all")
        menu.append("About Kiwi Fox", "app.about")
        menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu)
        header.pack_end(menu_button)

        self.refresh_button = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Refresh")
        self.refresh_button.connect("clicked", lambda *_: self.refresh())
        header.pack_end(self.refresh_button)

        self.status_banner = Adw.Banner(revealed=False)
        self.status_banner.set_button_label("Set up")
        self.status_banner.connect("button-clicked", lambda *_: self._run_setup())
        self.snap_banner = Adw.Banner(
            title="Snapshots are locked on this device", button_label="Unlock", revealed=False
        )
        if snapshot_ui is not None:
            self.snap_banner.connect(
                "button-clicked", lambda *_: snapshot_ui.ask_unlock(self, self._snapshots_changed)
            )

        self.page = Adw.PreferencesPage()
        widen(self.page)  # two buttons per row need the room
        # One group per tag (a profile sits under its first tag), the untagged
        # last; a single "Profiles" group while nothing is tagged.
        self._groups: dict[str, Adw.PreferencesGroup] = {}

        self.empty = Adw.StatusPage(
            icon_name="avatar-default-symbolic",
            title="No profiles yet",
            description="One identity per profile, on its own exit",
        )
        create = Gtk.Button(label="Create a profile", halign=Gtk.Align.CENTER)
        create.add_css_class("suggested-action")
        create.add_css_class("pill")
        create.connect("clicked", self._on_new)
        buttons = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, halign=Gtk.Align.CENTER)
        buttons.append(create)
        if snapshot_ui is not None:
            from_folder = Gtk.Button(label="Use a snapshot folder", halign=Gtk.Align.CENTER)
            from_folder.add_css_class("pill")
            from_folder.set_tooltip_text(
                "Bring the profiles of another device here, from snapshots"
            )
            from_folder.connect(
                "clicked", lambda *_: snapshot_ui.choose_folder(self, self._snapshots_changed)
            )
            buttons.append(from_folder)
        self.empty.set_child(buttons)
        self.away_group = Adw.PreferencesGroup(
            title="In your snapshot folder, not on this device", visible=False
        )

        self.stack = Gtk.Stack()
        self.stack.add_named(self.page, "list")
        self.stack.add_named(self.empty, "empty")

        view = Adw.ToolbarView()
        view.add_top_bar(header)
        view.add_top_bar(self.status_banner)
        view.add_top_bar(self.snap_banner)
        view.set_content(self.stack)
        self.toasts.set_child(view)
        self.set_content(self.toasts)

        for name, handler in (
            ("setup", lambda *_: self._run_setup()),
            ("engines", lambda *_: self._open_engines()),
            ("doctor", lambda *_: self._check_environment(announce=True)),
            ("stop-all", lambda *_: self._stop_all()),
            ("preferences", lambda *_: self._open_preferences()),
            ("snapshot-all", lambda *_: self._snapshot_all()),
            ("storage", lambda *_: storage_ui and storage_ui.check_and_repair(self, self.refresh)),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            self.add_action(action)

        self.refresh()
        self._check_environment()
        self._was_running = {p.id for p in store.list_profiles() if launch.running(p)}
        self._repair_on_start()
        self._look_for_engines()
        self._catch_up()
        GLib.timeout_add_seconds(REFRESH_SECONDS, self._tick)

    # ------------------------------------------------------------------ list

    def _on_close_request(self, *_args) -> bool:
        remember_geometry(self)
        return False  # and close

    def _tick(self) -> bool:
        self._ticks += 1
        if self._ticks % SNAPSHOT_TICKS == 0:
            self._poll_snapshots()
        self.refresh(rebuild=False)
        running = {p.id for p in store.list_profiles() if launch.running(p)}
        ended = self._was_running - running - self._busy
        self._was_running = running
        for profile in store.list_profiles():
            if profile.id in ended:
                self._after_stop(profile)  # its browser was closed: snapshot what ran
        if running:
            # An exit whose tunnel node died comes back on its own (kiwi-proxy's
            # heal), off the main loop; the next tick shows it.
            worker.run(launch.heal_exits, lambda _healed: None, lambda _exc: None)
        mine = [p for p in store.list_profiles() if p.id in running]
        worker.run(lambda: launch.silent_exits(mine), self._on_silent, lambda _exc: None)
        return True

    def _on_silent(self, silent: set[str]) -> None:
        if silent != self._silent:
            self._silent = silent
            self.refresh(rebuild=False)

    def refresh(self, rebuild: bool = True) -> None:
        profiles = store.list_profiles()
        self.stack.set_visible_child_name("list" if profiles or self._away else "empty")
        if rebuild:
            for group in self._groups.values():
                self.page.remove(group)
            self._groups.clear()
            self._rows.clear()
            if self.away_group.get_parent() is not None:
                self.page.remove(self.away_group)
            for title, members in grouped_by_tag(profiles):
                group = Adw.PreferencesGroup(title=title)
                self.page.add(group)
                self._groups[title] = group
                for profile in members:
                    row = self._build_row(profile)
                    self._rows[profile.id] = row
                    group.add(row)
            self.page.add(self.away_group)
            self._poll_snapshots()
        for profile in profiles:
            row = self._rows.get(profile.id)
            if row:
                self._update_row(row, profile)

    def _build_row(self, profile) -> Adw.ActionRow:
        row = Adw.ActionRow(title=profile.name, activatable=True)
        row.connect("activated", lambda *_: ProfileDetails(profile, self._after_edit).present(self))

        browser_button = Gtk.Button(valign=Gtk.Align.CENTER)
        browser_button.connect("clicked", self._on_browser, profile)
        row.add_suffix(browser_button)
        row.browser_button = browser_button  # type: ignore[attr-defined]
        container_button = Gtk.Button(valign=Gtk.Align.CENTER)
        container_button.connect("clicked", self._on_container, profile)
        row.add_suffix(container_button)
        row.container_button = container_button  # type: ignore[attr-defined]

        menu = Gio.Menu()
        menu.append("Details", f"win.details::{profile.id}")
        menu.append("Edit…", f"win.edit::{profile.id}")
        menu.append("Version…", f"win.version::{profile.id}")
        if profile.exit:
            menu.append("Open in Kiwi Proxy", "win.open-proxy")
        menu.append("Duplicate", f"win.duplicate::{profile.id}")
        if snapshot_ui is not None:
            menu.append("Snapshots…", f"win.snapshots::{profile.id}")
        menu.append("Delete", f"win.delete::{profile.id}")
        more = Gtk.MenuButton(
            icon_name="view-more-symbolic", valign=Gtk.Align.CENTER, menu_model=menu
        )
        more.add_css_class("flat")
        row.add_suffix(more)
        self._ensure_row_actions()
        return row

    def _ensure_row_actions(self) -> None:
        if self.lookup_action("details"):
            return
        action = Gio.SimpleAction.new("open-proxy", None)
        action.connect("activate", lambda *_: self._open_kiwi_proxy())
        self.add_action(action)
        for name, handler in (
            ("details", self._act_details),
            ("edit", self._act_edit),
            ("version", self._act_version),
            ("duplicate", self._act_duplicate),
            ("delete", self._act_delete),
            ("snapshots", self._act_snapshots),
            ("forget-snapshots", self._act_forget_snapshots),
        ):
            action = Gio.SimpleAction.new(name, GLib.VariantType.new("s"))
            action.connect("activate", handler)
            self.add_action(action)

    def _update_row(self, row: Adw.ActionRow, profile) -> None:
        container = launch.container_running(profile)
        browser = container and launch.running(profile)
        exit_bits = []
        if seen := store.seen_exit(profile):
            exit_bits.append(seen.country or "?")
            if seen.city:
                exit_bits.append(seen.city)
        where = " · ".join(exit_bits) or "not measured yet"
        subtitle = f"{TITLES[profile.engine]} · {exit_label(profile)} · {where}"
        if profile.tags:
            subtitle += " · " + " ".join(f"#{t}" for t in profile.tags)
        state = [
            "browser open" if browser else "browser closed",
            "container running" if container else "container stopped",
        ]
        if browser and profile.id in self._silent:
            state.append("VPN not answering")
        if note := self._snapshot_note(profile):
            state.append(note)
        subtitle += "\n" + " · ".join(state)
        row.set_subtitle(subtitle)
        row.set_subtitle_lines(0)
        browser_button = row.browser_button  # type: ignore[attr-defined]
        container_button = row.container_button  # type: ignore[attr-defined]
        busy = self._busy_what.get(profile.id) if profile.id in self._busy else None
        for button in (browser_button, container_button):
            button.set_sensitive(busy is None)
            button.remove_css_class("suggested-action")
        browser_button.set_label(
            "Working…"
            if busy in ("open", "quit")
            else "Quit browser"
            if browser
            else "Start browser"
        )
        container_button.set_label(
            "Working…"
            if busy in ("up", "stop")
            else "Stop container"
            if container
            else "Start container"
        )
        if not browser and busy is None:
            browser_button.add_css_class("suggested-action")

    # --------------------------------------------------------------- actions
    def _profile(self, ident: str):
        return next((p for p in store.list_profiles() if p.id == ident), None)

    def _act_details(self, _action, param) -> None:
        if profile := self._profile(param.get_string()):
            ProfileDetails(profile, self._after_edit).present(self)

    def _after_edit(self, profile) -> None:
        self.refresh()
        self._toast(f"Saved {profile.name}")

        def done(note) -> None:
            if note:
                self._toast(note)
            self._poll_snapshots()

        worker.run(lambda: profile_snapshots.changed(profile), done, lambda _exc: None)

    def _act_version(self, _action, param) -> None:
        profile = self._profile(param.get_string())
        if not profile:
            return

        def done(warnings) -> None:
            self.refresh()
            self._toast(f"{profile.name}: version changed")
            for line in warnings:
                self._toast(line)

        VersionDialog(profile, done).present(self)

    def _open_engines(self) -> None:
        EnginesDialog(self._run_setup, on_changed=self.refresh).present(self)

    def _look_for_engines(self) -> None:
        """Once a day: new engine releases, as the preference says."""
        from ..core import engine_versions as ev
        from ..core.engines import TITLES as ENGINE_TITLES

        def done(found) -> None:
            for item in found.news:
                name = f"{ENGINE_TITLES[item.engine]} {item.version}"
                if item.installed:
                    self._toast(f"Installed {name}")
                elif item.error:
                    self._toast(f"{name} is out; it could not be installed: {item.error}")
                else:
                    toast = Adw.Toast(title=f"{name} is out", button_label="Engines…", timeout=0)
                    toast.connect("button-clicked", lambda *_: self._open_engines())
                    self.toasts.add_toast(toast)

        worker.run(ev.news, done, lambda _exc: None)

    def _act_edit(self, _action, param) -> None:
        if profile := self._profile(param.get_string()):
            ProfileEditor(profile, self._after_edit).present(self)

    def _act_duplicate(self, _action, param) -> None:
        profile = self._profile(param.get_string())
        if not profile:
            return
        # A duplicate must be a *different* machine with a different exit, or it
        # defeats the point; so this opens the dialog pre-filled rather than copying.
        dialog = NewProfileDialog(self, self._after_create)
        dialog.name_row.set_text(f"{profile.name}-2")
        dialog.select_engine(profile.engine)
        dialog.exits.select(profile.exit)
        dialog.present(self)

    def _act_delete(self, _action, param) -> None:
        profile = self._profile(param.get_string())
        if not profile:
            return
        if profile.engine == "camoufox":
            body = (
                "Its identity cannot be regenerated: the seed, fingerprint and browser "
                "data are removed. Logins tied to this identity will be lost."
            )
        else:
            body = (
                "Its browser data are removed. Logins tied to this profile will be lost. "
                "A proxy kiwi-fox made for it alone goes too; one made in kiwi-proxy stays."
            )
        dialog = Adw.AlertDialog(heading=f"Delete {profile.name}?", body=body)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")

        def on_response(_d, response: str) -> None:
            if response != "delete":
                return
            launch.down(profile)
            store.delete(profile.id, purge=True)
            self.refresh()
            self._toast(f"Deleted {profile.name}")

        dialog.connect("response", on_response)
        dialog.present(self)

    def _on_new(self, *_args) -> None:
        NewProfileDialog(self, self._after_create).present(self)

    def _after_create(self, profile) -> None:
        self.refresh()
        self._toast(f"Created {profile.name}")

    def _on_container(self, _button, profile) -> None:
        self._do(profile, "stop" if launch.container_running(profile) else "up")

    def _on_browser(self, _button, profile) -> None:
        if launch.running(profile):
            self._do(profile, "quit")
            return
        if snapshot_ui is None:
            self._start_or_stop(profile)
            return

        def look():
            return profile_snapshots.before_start(profile)

        def decide(check) -> None:
            if not check.needs_asking:
                self._start_or_stop(profile)
                return
            self._ask_before_start(profile, check)

        worker.run(look, decide, lambda _exc: self._start_or_stop(profile))

    def _ask_before_start(self, profile, check) -> None:
        def newer() -> None:
            rel = check.relation
            if not (rel and rel.newer_elsewhere):
                self._start_or_stop(profile)
                return

            def restore_then_start() -> None:
                def work():
                    return profile_snapshots.restore(profile.id, rel.head.id)

                def done(restored) -> None:
                    self._snapshots_changed()
                    if missing := profile_snapshots.missing_engine(restored):
                        self._offer_engine(restored, missing)
                        return
                    self._start_or_stop(restored)

                worker.run(
                    work,
                    done,
                    lambda exc: self._alert(f"Could not restore {profile.name}", str(exc)),
                )

            def keep_mine() -> None:
                worker.run(
                    lambda: profile_snapshots.keep_mine(profile, check),
                    lambda _m: (self._snapshots_changed(), self._start_or_stop(profile)),
                    lambda exc: self._alert("No snapshot taken", str(exc)),
                )

            snapshot_ui.ask_newer(
                self,
                profile.name,
                rel,
                verb="start",
                on_restore=restore_then_start,
                on_as_is=lambda: self._start_or_stop(profile),
                on_keep_mine=keep_mine,
            )

        if check.in_use:
            from .start_prompt import in_use_dialog

            in_use_dialog(
                profile.name, check.in_use, lambda r: newer() if r == "start" else None
            ).present(self)
        else:
            newer()

    def _start_or_stop(self, profile) -> None:
        """The browser button, after the look before a start."""
        self._do(profile, "quit" if launch.running(profile) else "open")

    def _do(self, profile, what: str) -> None:
        """open | quit (the browser) · up | stop (the container)."""
        self._busy.add(profile.id)
        self._busy_what[profile.id] = what
        self.refresh(rebuild=False)

        def work():
            if what == "quit":
                launch.quit_browser(profile)
                return "quit"
            if what == "stop":
                launch.stop(profile)
                return None
            return launch.launch(profile, browser=what == "open")

        def done(result) -> None:
            self._busy.discard(profile.id)
            self._busy_what.pop(profile.id, None)
            self.refresh()
            if result == "quit":
                kept = settings.load().keep_container
                self._toast(
                    f"Closing {profile.name}" + ("; its container keeps running" if kept else "")
                )
                return
            if result is None:
                self._was_running.discard(profile.id)
                self._toast(f"Stopped {profile.name}'s container")
                self._after_stop(profile)
                return
            if what == "up":
                self._toast(f"{profile.name}'s container is running; the browser starts at once")
                return
            self._was_running.add(profile.id)
            for issue in result.warnings:
                self._toast(str(issue))
            if result.exit_info:
                self._toast(
                    f"{profile.name}: {result.exit_info.ip} {result.exit_info.country or '?'}"
                )
            else:
                self._toast(f"Launched {profile.name}")

        def failed(exc: Exception) -> None:
            self._busy.discard(profile.id)
            self._busy_what.pop(profile.id, None)
            self.refresh()
            verb = {"open": "start", "quit": "close", "up": "start", "stop": "stop"}[what]
            thing = "the browser of" if what in ("open", "quit") else "the container of"
            self._alert(f"Could not {verb} {thing} {profile.name}", str(exc))

        worker.run(work, done, failed)

    def _repair_on_start(self) -> None:
        if not settings.load().repair_on_start:
            return

        def done(lines) -> None:
            for line in lines[:3]:
                self._toast(line[0].upper() + line[1:])
            if lines:
                self.refresh()

        worker.run(launch.repair, done, lambda _exc: None)

    def _open_kiwi_proxy(self) -> None:
        info = Gio.DesktopAppInfo.new(f"{PROXY_APP_ID}.desktop")
        try:
            if info is not None:
                info.launch([], None)
            else:
                import subprocess

                subprocess.Popen(["kiwi-proxy-gui"])  # noqa: S603, S607
        except Exception:  # noqa: BLE001 - say so
            self._toast("Kiwi Proxy could not be opened: kiwi install kiwi-proxy")

    def _stop_all(self) -> None:
        def work():
            notes = []
            for profile in store.list_profiles():
                was = launch.running(profile)
                launch.stop(profile)
                if was and (note := profile_snapshots.after_stop(profile)):
                    notes.append(note)
            launch.reap()
            return notes

        def done(notes) -> None:
            self._was_running.clear()
            self.refresh()
            self._toast("Everything stopped")
            for note in notes:
                self._toast(note)

        worker.run(work, done)

    # ------------------------------------------------------------- snapshots
    def _snapshot_note(self, profile) -> str:
        """The second line of a row: what the snapshot folder says."""
        if snap is None:
            return ""
        bits = []
        for device, since in self._in_use.get(profile.id, []):
            bits.append(f"in use on {device} since {snap.when_text(since)}")
        rel = self._relations.get(profile.id)
        if rel is not None and rel.state != "only_here":
            bits.append(rel.describe())
        return " · ".join(bits)

    def _poll_snapshots(self) -> None:
        """Read the snapshot folder off the main loop."""
        if snap is None or self._snap_polling:
            return
        self._snap_polling = True

        def work():
            st = snap.status()
            if st.settings is None or not st.folder_present or not st.unlocked:
                return st, {}, {}, []
            opened = snap.folder()
            here = {p.id for p in store.list_profiles()}
            grouped: dict[str, list] = {}
            for meta in opened.metas():
                if meta.kind == profile_snapshots.KIND:
                    grouped.setdefault(meta.item, []).append(meta)
            relations, in_use, away = {}, {}, []
            for pid in here:
                relations[pid] = snap.relation(
                    profile_snapshots.KIND,
                    pid,
                    here=True,
                    metas=grouped.get(pid, []),
                    folder_id=opened.id,
                )
                if pid in grouped:
                    in_use[pid] = snap.in_use_elsewhere(profile_snapshots.KIND, pid)
            for pid, metas in grouped.items():
                if pid not in here:
                    away.append((pid, metas[0].name, metas))
            away.sort(key=lambda a: a[1])
            return st, relations, in_use, away

        def done(result) -> None:
            self._snap_polling = False
            st, relations, in_use, away = result
            self.snap_banner.set_revealed(
                bool(st.settings and st.folder_present and not st.unlocked)
            )

            def key(rels):
                return {k: (v.state, v.head.id if v.head else None) for k, v in rels.items()}

            changed = (
                key(relations) != key(self._relations)
                or in_use != self._in_use
                or [a[:2] for a in away] != [a[:2] for a in self._away]
            )
            self._relations, self._in_use, self._away = relations, in_use, away
            if changed:
                self._show_away()
                self.refresh(rebuild=False)

        def failed(_exc: Exception) -> None:
            self._snap_polling = False

        worker.run(work, done, failed)

    def _show_away(self) -> None:
        for row in self._away_rows:
            self.away_group.remove(row)
        self._away_rows = []
        for pid, name, metas in self._away:
            head = metas[0]
            engine = TITLES.get(head.extra.get("engine", ""), head.extra.get("engine", ""))
            version = head.extra.get("engine_version") or ""
            row = Adw.ActionRow(use_markup=False)
            row.set_title(name)
            row.set_subtitle(
                " · ".join(
                    x
                    for x in (
                        f"{engine} {version}".strip(),
                        f"from {head.device}, {snap.when_text(head.created)}",
                        snap.size_text(head.size),
                    )
                    if x
                )
            )
            restore = Gtk.Button(label="Restore", valign=Gtk.Align.CENTER)
            restore.connect("clicked", self._on_restore_away, pid, name, head)
            row.add_suffix(restore)
            menu = Gio.Menu()
            menu.append("Snapshots…", f"win.snapshots::{pid}")
            menu.append("Delete from the snapshot folder", f"win.forget-snapshots::{pid}")
            more = Gtk.MenuButton(
                icon_name="view-more-symbolic", valign=Gtk.Align.CENTER, menu_model=menu
            )
            more.add_css_class("flat")
            row.add_suffix(more)
            self.away_group.add(row)
            self._away_rows.append(row)
        self.away_group.set_visible(bool(self._away))
        self.stack.set_visible_child_name(
            "list" if self._away or store.list_profiles() else "empty"
        )

    def _on_restore_away(self, _button, pid: str, name: str, head) -> None:
        if exit_name := profile_snapshots.missing_exit(head):
            self._alert(
                f"Restore {exit_name} in Kiwi Proxy first",
                f"{name} goes out through the exit {exit_name}, which is not on this device. "
                "Kiwi Proxy restores exits from the same snapshot folder; then restore "
                f"{name} here.",
            )
            return
        self._restore(pid, head.id, name)

    def _restore(self, pid: str, sid: str, name: str) -> None:
        def done(restored) -> None:
            self._toast(f"Restored {restored.name}")
            self._snapshots_changed()
            if missing := profile_snapshots.missing_engine(restored):
                self._offer_engine(restored, missing)

        worker.run(
            lambda: profile_snapshots.restore(pid, sid),
            done,
            lambda exc: self._alert(f"Could not restore {name}", str(exc)),
        )

    def _offer_engine(self, profile, missing: tuple[str, str]) -> None:
        engine, version = missing
        title = f"{TITLES.get(engine, engine)} {'' if version == 'newest' else version}".strip()
        dialog = Adw.AlertDialog(
            heading=f"{profile.name} needs {title}",
            body=f"This device does not have {title}. It is downloaded from its publisher "
            "and its signature or checksum is checked, as at any first install.",
        )
        dialog.add_response("later", "Later")
        dialog.add_response("install", "Install it now")
        dialog.set_response_appearance("install", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_close_response("later")

        def on_response(_d, response: str) -> None:
            if response != "install":
                return
            self._toast(f"Installing {title}…")
            worker.run(
                lambda: profile_snapshots.fetch_engine(engine, version),
                lambda _r: (self._toast(f"{title} installed"), self.refresh()),
                lambda exc: self._alert(f"Could not install {title}", str(exc)),
            )

        dialog.connect("response", on_response)
        dialog.present(self)

    def _after_stop(self, profile) -> None:
        """A profile's browser ended: snapshot it when it ran, off the main loop."""

        def done(note) -> None:
            if note:
                self._toast(note)
            self._poll_snapshots()

        worker.run(lambda: profile_snapshots.after_stop(profile), done, lambda _exc: None)

    def _catch_up(self) -> None:
        """At start: snapshot stopped profiles that ran since their last snapshot
        (their browser ended while no window watched), one after the other."""
        if snap is None or snap.load_settings() is None:
            return
        stopped = [p for p in store.list_profiles() if not launch.running(p)]

        def work():
            return [n for p in stopped if (n := profile_snapshots.after_stop(p))]

        def done(notes) -> None:
            for note in notes[:3]:
                self._toast(note)
            self._poll_snapshots()

        worker.run(work, done, lambda _exc: None)

    def _snapshots_changed(self) -> None:
        self._relations = {}
        self.refresh()

    def _general_page(self) -> Adw.PreferencesPage:
        s = settings.load()
        page = Adw.PreferencesPage(title="General", icon_name="preferences-system-symbolic")
        group = Adw.PreferencesGroup(title="Browser and container")
        quits = Adw.ComboRow(
            title="When the browser quits",
            model=Gtk.StringList.new(["Stop its container", "Keep it running"]),
        )
        explain(
            quits,
            "A stopped container lets go of its exit; Kiwi Proxy takes the exit down when "
            "nothing else uses it. A container kept running starts its browser again at once.",
            app=APP,
            anchor="browser-and-container",
        )
        quits.set_selected(1 if s.keep_container else 0)

        def on_quits(row, _param) -> None:
            cur = settings.load()
            cur.keep_container = row.get_selected() == 1
            settings.save(cur)
            worker.run(launch.apply_keep_setting, lambda _r: None, lambda _e: None)

        quits.connect("notify::selected", on_quits)
        group.add(quits)
        repair = Adw.SwitchRow(title="Repair on start", active=s.repair_on_start)
        explain(
            repair,
            "Before anything starts, remove this app's containers an unclean shutdown "
            "left, clear stale profile locks, and give running containers their watcher.",
            app=APP,
            anchor="browser-and-container",
        )

        def on_repair(row, _param) -> None:
            cur = settings.load()
            cur.repair_on_start = row.get_active()
            settings.save(cur)

        repair.connect("notify::active", on_repair)
        group.add(repair)
        page.add(group)
        page.add(self._new_profiles_group(s))
        page.add(self._window_group())
        return page

    def _new_profiles_group(self, s) -> Adw.PreferencesGroup:
        from ..core.engines import TITLES as ENGINE_TITLES

        group = Adw.PreferencesGroup(title="New profiles")
        engines = ["camoufox", "firefox", "torbrowser"]
        engine = Adw.ComboRow(
            title="Engine", model=Gtk.StringList.new([ENGINE_TITLES[e] for e in engines])
        )
        engine.set_selected(engines.index(s.new_engine) if s.new_engine in engines else 0)

        def on_engine(row, _param) -> None:
            cur = settings.load()
            cur.new_engine = engines[row.get_selected()]
            settings.save(cur)

        engine.connect("notify::selected", on_engine)
        group.add(engine)
        found = sorted(exits.list_exits(), key=lambda e: e.name)
        choices = [("", "Ask every time"), ("none", "No proxy")] + [(e.id, e.name) for e in found]
        exit_row = Adw.ComboRow(
            title="Exit", model=Gtk.StringList.new([label for _k, label in choices])
        )
        keys = [k for k, _l in choices]
        exit_row.set_selected(keys.index(s.new_exit) if s.new_exit in keys else 0)

        def on_exit(row, _param) -> None:
            cur = settings.load()
            cur.new_exit = keys[row.get_selected()]
            settings.save(cur)

        exit_row.connect("notify::selected", on_exit)
        group.add(exit_row)
        return group

    def _window_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Window")
        row = Adw.ActionRow(title="Size")

        def show() -> None:
            w, h, maxed = saved_geometry()
            row.set_subtitle("maximized" if maxed else f"{w} × {h}, kept when you close it")

        reset = Gtk.Button(label="Reset", valign=Gtk.Align.CENTER)

        def on_reset(*_a) -> None:
            with contextlib.suppress(OSError):
                (paths.config_dir() / "window.json").unlink()
            self.unmaximize()
            self.set_default_size(*DEFAULT_SIZE)
            show()

        reset.connect("clicked", on_reset)
        row.add_suffix(reset)
        show()
        group.add(row)
        return group

    def _open_preferences(self) -> None:
        general = self._general_page()
        engines = EnginesPage(self._open_engines)
        if snapshot_ui is None:
            dialog = Adw.PreferencesDialog(title="Preferences")
            dialog.add(general)
            dialog.add(engines)
            dialog.present(self)
            return
        page = snapshot_ui.SnapshotsPage(
            "when a profile stops after it ran, and when you change its settings",
            on_changed=self._snapshots_changed,
            take_all=self._take_all,
            take_all_text="every stopped profile; a running one is taken when it stops",
        )
        snapshot_ui.preferences_dialog(general, engines, page).present(self)

    def _take_all(self) -> str:
        taken = skipped = size = 0
        for profile in store.list_profiles():
            if launch.running(profile):
                skipped += 1
                continue
            size += profile_snapshots.take(profile).size
            taken += 1
        if not taken and not skipped:
            return "nothing to snapshot yet"
        line = f"{taken} profile{'s' if taken != 1 else ''} · {snap.size_text(size)}"
        if skipped:
            line += f" · {skipped} running, taken when {'they stop' if skipped > 1 else 'it stops'}"
        return line

    def _snapshot_all(self) -> None:
        if snap is None:
            return
        if not snap.load_settings():
            self._open_preferences()
            return
        if not snap.unlocked():
            snapshot_ui.ask_unlock(self, self._snapshot_all)
            return
        self._toast("Taking snapshots…")
        worker.run(
            self._take_all,
            lambda summary: (self._toast(f"Snapshots taken: {summary}"), self._snapshots_changed()),
            lambda exc: self._alert("No snapshot taken", str(exc)),
        )

    def _act_snapshots(self, _action, param) -> None:
        if snap is None:
            return
        pid = param.get_string()
        if not snap.load_settings():
            self._open_preferences()
            return
        if not snap.unlocked():
            snapshot_ui.ask_unlock(self, lambda: self._act_snapshots(_action, param))
            return
        profile = self._profile(pid)
        here = profile is not None
        name = profile.name if here else next((a[1] for a in self._away if a[0] == pid), pid)
        take = (lambda: profile_snapshots.take(store.load(pid))) if here else None
        snapshot_ui.HistoryDialog(
            profile_snapshots.KIND,
            pid,
            name,
            here=here,
            take=take,
            restore=lambda sid: profile_snapshots.restore(pid, sid),
            on_changed=self._snapshots_changed,
            toast=self._toast,
        ).present(self)

    def _act_forget_snapshots(self, _action, param) -> None:
        pid = param.get_string()
        name = next((a[1] for a in self._away if a[0] == pid), pid)
        dialog = Adw.AlertDialog(
            heading=f"Delete the snapshots of {name}?",
            body="Every snapshot of it is deleted from the snapshot folder, on every device "
            "that syncs the folder. This cannot be undone.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_close_response("cancel")

        def on_response(_d, response: str) -> None:
            if response != "delete":
                return
            worker.run(
                lambda: snap.forget(profile_snapshots.KIND, pid),
                lambda n: (
                    self._toast(f"Deleted {n} snapshot(s) of {name}"),
                    self._snapshots_changed(),
                ),
                lambda exc: self._alert("Could not delete", str(exc)),
            )

        dialog.connect("response", on_response)
        dialog.present(self)

    # ----------------------------------------------------------- environment
    def _check_environment(self, announce: bool = False) -> None:
        def work():
            missing = []
            profiles = store.list_profiles()
            have_podman = podman.available()
            if not have_podman:
                missing.append("podman")
            # The engines the profiles need; any one at all before there are profiles.
            wanted = sorted({p.engine for p in profiles}, key=list(TITLES).index)
            if not wanted and not any(installed_versions(e) for e in TITLES):
                missing.append("a browser engine")
            missing += [TITLES[e] for e in wanted if not installed_versions(e)]
            if have_podman:
                for image in (proxy_paths.GATEWAY_IMAGE, launch.BROWSER_IMAGE):
                    if not podman.image_exists(image):
                        missing.append(image.split("/")[-1].split(":")[0] + " image")
            present = {m.name for m in modules.installed()}
            by_id = {e.id: e for e in exits.list_exits()}
            needed = {
                by_id[p.exit].endpoint.module
                for p in profiles
                if p.exit in by_id and by_id[p.exit].endpoint.module
            }
            for name in sorted(needed):
                if name not in present:
                    missing.append(f"the {name} module ({modules.install_hint(name)})")
            if not (proxy_paths.blocklists_dir() / "blocked-names.txt").exists():
                missing.append("blocklists")
            if not secrets.available():
                missing.append("secret-tool")
            from ..core import gpu

            seen = gpu.measurement()
            if (seen is not None and not seen.get("accelerated")) or gpu.plan().kind == "software":
                missing.append("hardware rendering (software reads as a virtual machine)")
            return missing

        def done(missing) -> None:
            if missing:
                self.status_banner.set_title("Setup incomplete: " + ", ".join(missing))
                self.status_banner.set_revealed(True)
            else:
                self.status_banner.set_revealed(False)
                if announce:
                    self._toast("Environment is ready")

        worker.run(work, done)

    def _run_setup(self) -> None:
        from ..core import setup

        progress = Adw.AlertDialog(heading="Setting up", body="Starting…")
        progress.add_response("close", "Run in background")
        progress.present(self)

        def say(message: str) -> None:
            GLib.idle_add(progress.set_body, message)

        def work():
            return setup.run(progress=say)

        def done(steps) -> None:
            progress.close()
            self._check_environment()
            self.refresh()
            self._alert("Setup finished", "\n".join(steps))

        def failed(exc: Exception) -> None:
            progress.close()
            self._alert("Setup failed", str(exc))

        worker.run(work, done, failed)

    # ---------------------------------------------------------------- toasts
    def _toast(self, text: str) -> None:
        self.toasts.add_toast(Adw.Toast(title=text, timeout=4))

    def _alert(self, heading: str, body: str) -> None:
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("ok", "OK")
        dialog.present(self)
