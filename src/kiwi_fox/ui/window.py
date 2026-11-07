"""Main window: the profile list, and the setup state behind it."""

from __future__ import annotations

import json

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402
from kiwi_proxy import exits, podman  # noqa: E402
from kiwi_proxy import paths as proxy_paths  # noqa: E402

from ..core import launch, modules, paths, secrets, store  # noqa: E402
from ..core.engines import TITLES, installed_versions  # noqa: E402
from ..core.store import grouped_by_tag  # noqa: E402
from . import worker  # noqa: E402
from .dialogs import (  # noqa: E402
    EnginesDialog,
    NewProfileDialog,
    ProfileDetails,
    ProfileEditor,
    exit_label,
)

REFRESH_SECONDS = 4


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

        self.toasts = Adw.ToastOverlay()
        header = Adw.HeaderBar()

        new_button = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="New profile")
        new_button.connect("clicked", self._on_new)
        header.pack_start(new_button)

        menu = Gio.Menu()
        menu.append("Set up environment", "win.setup")
        menu.append("Browser engines", "win.engines")
        menu.append("Check environment", "win.doctor")
        menu.append("Stop everything", "win.stop-all")
        menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu)
        header.pack_end(menu_button)

        self.refresh_button = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Refresh")
        self.refresh_button.connect("clicked", lambda *_: self.refresh())
        header.pack_end(self.refresh_button)

        self.status_banner = Adw.Banner(revealed=False)
        self.status_banner.set_button_label("Set up")
        self.status_banner.connect("button-clicked", lambda *_: self._run_setup())

        self.page = Adw.PreferencesPage()
        # One group per tag (a profile sits under its first tag), the untagged
        # last; a single "Profiles" group while nothing is tagged.
        self._groups: dict[str, Adw.PreferencesGroup] = {}

        self.empty = Adw.StatusPage(
            icon_name="avatar-default-symbolic",
            title="No profiles yet",
            description="A profile is one identity: its own storage, on a kiwi-proxy exit or "
            "this machine's own connection, in Camoufox with a frozen Windows fingerprint, "
            "in stock Firefox, or in Tor Browser.",
        )
        create = Gtk.Button(label="Create a profile", halign=Gtk.Align.CENTER)
        create.add_css_class("suggested-action")
        create.add_css_class("pill")
        create.connect("clicked", self._on_new)
        self.empty.set_child(create)

        self.stack = Gtk.Stack()
        self.stack.add_named(self.page, "list")
        self.stack.add_named(self.empty, "empty")

        view = Adw.ToolbarView()
        view.add_top_bar(header)
        view.add_top_bar(self.status_banner)
        view.set_content(self.stack)
        self.toasts.set_child(view)
        self.set_content(self.toasts)

        for name, handler in (
            ("setup", lambda *_: self._run_setup()),
            ("engines", lambda *_: EnginesDialog(self._run_setup).present(self)),
            ("doctor", lambda *_: self._check_environment(announce=True)),
            ("stop-all", lambda *_: self._stop_all()),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            self.add_action(action)

        self.refresh()
        self._check_environment()
        GLib.timeout_add_seconds(REFRESH_SECONDS, self._tick)

    # ------------------------------------------------------------------ list

    def _on_close_request(self, *_args) -> bool:
        remember_geometry(self)
        return False  # and close

    def _tick(self) -> bool:
        self.refresh(rebuild=False)
        if any(launch.running(p) for p in store.list_profiles()):
            # An exit whose tunnel node died comes back on its own (kiwi-proxy's
            # heal), off the main loop; the next tick shows it.
            worker.run(launch.heal_exits, lambda _healed: None, lambda _exc: None)
        return True

    def refresh(self, rebuild: bool = True) -> None:
        profiles = store.list_profiles()
        self.stack.set_visible_child_name("list" if profiles else "empty")
        if rebuild:
            for group in self._groups.values():
                self.page.remove(group)
            self._groups.clear()
            self._rows.clear()
            for title, members in grouped_by_tag(profiles):
                group = Adw.PreferencesGroup(title=title)
                self.page.add(group)
                self._groups[title] = group
                for profile in members:
                    row = self._build_row(profile)
                    self._rows[profile.id] = row
                    group.add(row)
        for profile in profiles:
            row = self._rows.get(profile.id)
            if row:
                self._update_row(row, profile)

    def _build_row(self, profile) -> Adw.ActionRow:
        row = Adw.ActionRow(title=profile.name, activatable=True)
        row.connect("activated", lambda *_: ProfileDetails(profile, self._after_edit).present(self))

        run_button = Gtk.Button(valign=Gtk.Align.CENTER)
        run_button.connect("clicked", self._on_toggle, profile)
        row.add_suffix(run_button)
        row.run_button = run_button  # type: ignore[attr-defined]

        menu = Gio.Menu()
        menu.append("Details", f"win.details::{profile.id}")
        menu.append("Edit…", f"win.edit::{profile.id}")
        menu.append("Duplicate", f"win.duplicate::{profile.id}")
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
        for name, handler in (
            ("details", self._act_details),
            ("edit", self._act_edit),
            ("duplicate", self._act_duplicate),
            ("delete", self._act_delete),
        ):
            action = Gio.SimpleAction.new(name, GLib.VariantType.new("s"))
            action.connect("activate", handler)
            self.add_action(action)

    def _update_row(self, row: Adw.ActionRow, profile) -> None:
        running = profile.id in self._busy or launch.running(profile)
        exit_bits = []
        if seen := store.seen_exit(profile):
            exit_bits.append(seen.country or "?")
            if seen.city:
                exit_bits.append(seen.city)
        where = " · ".join(exit_bits) or "not measured yet"
        subtitle = f"{TITLES[profile.engine]} · {exit_label(profile)} · {where}"
        if profile.tags:
            subtitle += " · " + " ".join(f"#{t}" for t in profile.tags)
        row.set_subtitle(subtitle)
        button = row.run_button  # type: ignore[attr-defined]
        if profile.id in self._busy:
            button.set_label("Working…")
            button.set_sensitive(False)
            return
        button.set_sensitive(True)
        button.set_label("Stop" if running else "Launch")
        for css in ("suggested-action", "destructive-action"):
            button.remove_css_class(css)
        button.add_css_class("destructive-action" if running else "suggested-action")

    # --------------------------------------------------------------- actions
    def _profile(self, ident: str):
        return next((p for p in store.list_profiles() if p.id == ident), None)

    def _act_details(self, _action, param) -> None:
        if profile := self._profile(param.get_string()):
            ProfileDetails(profile, self._after_edit).present(self)

    def _after_edit(self, profile) -> None:
        self.refresh()
        self._toast(f"Saved {profile.name}")

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

    def _on_toggle(self, _button, profile) -> None:
        running = launch.running(profile)
        self._busy.add(profile.id)
        self.refresh(rebuild=False)

        def work():
            if running:
                launch.stop(profile)
                return None
            return launch.launch(profile)

        def done(result) -> None:
            self._busy.discard(profile.id)
            self.refresh()
            if result is None:
                self._toast(f"Stopped {profile.name}")
                return
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
            self.refresh()
            self._alert(f"Could not launch {profile.name}", str(exc))

        worker.run(work, done, failed)

    def _stop_all(self) -> None:
        def work():
            for profile in store.list_profiles():
                launch.stop(profile)
            launch.reap()

        worker.run(work, lambda _r: (self.refresh(), self._toast("Everything stopped")))

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
