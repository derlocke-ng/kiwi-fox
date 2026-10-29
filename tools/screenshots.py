"""Render the GUI's screenshots (data/screenshots, listed in kiwi.manifest).

    xvfb-run -a -s "-screen 0 1400x1400x24" python3 tools/screenshots.py [OUTDIR]

Everything a screenshot shows is staged: sample profiles in a throwaway home,
the four first-party modules and all three engines shown as installed, a measured
graphics card. Nothing on this machine is read or started. Needs GTK 4 and
libadwaita (PyGObject) and kiwi-proxy on the path, like the GUI itself.
"""

from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile
from pathlib import Path

HOME = Path(tempfile.mkdtemp(prefix="kiwi-fox-shots-"))
for var in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR"):
    os.environ[var] = str(HOME / var.lower())
os.environ.setdefault("GSETTINGS_BACKEND", "memory")

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Graphene", "1.0")
from gi.repository import Adw, Gio, GLib, Graphene, Gtk  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "data/screenshots")
CARD = "NVIDIA GeForce RTX 4060 Laptop GPU"
VERSIONS = {"camoufox": ["152.0.4"], "firefox": ["146.0"], "torbrowser": ["15.0.2"]}
MAX_HEIGHT = 1290
FRAME = 10  # what the window's frame adds around its content


def stage() -> None:
    """The world the screenshots show."""
    from kiwi_proxy import podman

    from kiwi_fox.core import gpu, modules, paths, store
    from kiwi_fox.core.engines import fetch
    from kiwi_fox.core.fingerprint import generate, webgl
    from kiwi_fox.core.models import Endpoint, ExitInfo
    from kiwi_fox.ui import dialogs, window

    webgl.host_card = lambda: CARD
    webgl.host_series = lambda: (webgl.BY_NAME[CARD].series, "measured")
    gpu.measurement = lambda: {"accelerated": True}
    gpu.plan = lambda prefer=None: gpu.Plan("nvidia", (), {}, None, "")
    fetch.preferred = lambda: VERSIONS["camoufox"][-1]
    for mod in (dialogs, window):
        mod.installed_versions = lambda engine: VERSIONS[engine]
    modules.installed = lambda: [
        modules.Module("tor", "Tor", "exit through the Tor network", False, True),
        modules.Module("vpn", "VPN (gluetun)", "a WireGuard/OpenVPN tunnel", True, True),
        modules.Module("9proxy", "9proxy", "a residential proxy", True, True),
        modules.Module("mysterium", "Mysterium", "the Mysterium dVPN", True, True),
    ]
    modules.leases = lambda name: []
    window.Window._check_environment = lambda self, announce=False: None
    podman.available = lambda: True

    paths.ensure_tree()
    seen = dt.datetime(2026, 10, 29, tzinfo=dt.UTC)
    for name, port, country, city in (
        ("work", 1080, "CH", "Zurich"),
        ("shop", 1081, "SE", "Malmö"),
    ):
        fp = generate(engine_version="152.0.4", country=country, seed=name * 8)
        p = store.create(name, Endpoint(host="10.64.0.1", port=port), fp)
        p.last_exit = ExitInfo(ip=f"185.65.{port % 100}.7", country=country, city=city, seen=seen)
        store.save(p)
    research = store.create(
        "research", Endpoint(host="10.64.0.1", port=1082), None, engine="firefox"
    )
    research.last_exit = ExitInfo(ip="185.65.82.7", country="DE", city="Frankfurt", seen=seen)
    store.save(research)
    store.create(
        "anon",
        Endpoint(host="10.89.231.5", port=9050, module="tor"),
        None,
        engine="torbrowser",
    )
    running = {paths.browser_name(store.find_by_name("work").id)}
    podman.is_running = lambda name: name in running


def _scroller(widget: Gtk.Widget) -> Gtk.ScrolledWindow | None:
    child = widget.get_first_child()
    while child is not None:
        if isinstance(child, Gtk.ScrolledWindow):
            return child
        if found := _scroller(child):
            return found
        child = child.get_next_sibling()
    return None


def render(win: Gtk.Window, content: Gtk.Widget, path: Path, height: int) -> None:
    """What the window draws inside `content` — its own background included, its
    shadow not — cut to `height`."""
    _ok, bounds = content.compute_bounds(win)
    width = content.get_width()
    height = min(height, content.get_height())
    snapshot = Gtk.Snapshot()
    Gtk.WidgetPaintable.new(win).snapshot(snapshot, win.get_width(), win.get_height())
    texture = win.get_renderer().render_texture(
        snapshot.to_node(), Graphene.Rect().init(bounds.get_x(), bounds.get_y(), width, height)
    )
    texture.save_to_png(str(path))
    print(f"{path}  {width}x{height}", flush=True)


class Shots(Adw.Application):
    def __init__(self) -> None:
        super().__init__(
            application_id="dev.kiwinetwork.KiwiFoxScreenshots",
            flags=Gio.ApplicationFlags.NON_UNIQUE,
        )

    def do_activate(self) -> None:  # noqa: N802
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        # A dialog has a close button only; so do the windows the dialogs are drawn in.
        Gtk.Settings.get_default().set_property("gtk-decoration-layout", ":close")
        self.steps = [
            ("1-profiles", self.profiles),
            ("2-new-profile", lambda: self.new_profile("camoufox")),
            ("3-graphics-card", self.graphics),
            ("4-tor-browser", lambda: self.new_profile("torbrowser", name="anon")),
            ("5-edit-profile", self.edit),
            ("6-browser-engines", self.engines),
        ]
        self.hold()
        GLib.idle_add(self.next)

    def next(self) -> bool:
        if not self.steps:
            self.release()
            self.quit()
            return False
        name, build = self.steps.pop(0)
        win, width, height = build()
        # The window's frame is drawn around the content; the picture is the content.
        win.set_default_size(width + FRAME, height + FRAME)
        win.present()
        GLib.timeout_add(600, lambda: win.set_focus(None) or False)
        GLib.timeout_add(1400, self.shoot, win, name, name != "1-profiles")
        return False

    def shoot(self, win: Gtk.Window, name: str, to_length: bool) -> bool:
        content = win.get_content()
        height = content.get_height()
        scroller = _scroller(content) if to_length else None
        if scroller is not None and scroller.get_child() is not None:
            # Cut where the page ends: as tall as it is, no taller than the cap.
            top = scroller.compute_bounds(content)[1].get_y()
            natural = scroller.get_child().measure(Gtk.Orientation.VERTICAL, scroller.get_width())
            height = int(top + natural[1])
        render(win, content, OUT / f"{name}.png", min(height, MAX_HEIGHT))
        win.destroy()
        GLib.idle_add(self.next)
        return False

    # ------------------------------------------------------------- the views
    def profiles(self):
        from kiwi_fox.ui.window import Window

        return Window(application=self), 760, 620

    def _standalone(self, dialog: Adw.Dialog, width: int):
        """A dialog's content in a window of its own, drawn at full length."""
        child = dialog.get_child()
        dialog.set_child(None)
        win = Adw.Window(application=self, content=child, title=dialog.get_title())
        return win, width, MAX_HEIGHT

    def new_profile(self, engine: str, name: str = "work"):
        from kiwi_fox.ui.dialogs import NewProfileDialog

        d = NewProfileDialog(Adw.ApplicationWindow(application=self), lambda p: None)
        d.name_row.set_text(name)
        d.select_engine(engine)
        return self._standalone(d, 640)

    def graphics(self):
        from kiwi_fox.ui.dialogs import NewProfileDialog

        d = NewProfileDialog(Adw.ApplicationWindow(application=self), lambda p: None)
        d.name_row.set_text("work")
        d.graphics.set_mode("preset")
        d.graphics.set_card("NVIDIA GeForce RTX 3060")
        for group in d.graphics.card_groups:
            group.set_expanded(group.family == "nvidia")  # type: ignore[attr-defined]
        # The card list is the point of this one: start the picture at the Graphics section.
        d.identity.set_visible(False)
        return self._standalone(d, 640)

    def edit(self):
        from kiwi_fox.core import store
        from kiwi_fox.ui.dialogs import ProfileEditor

        return self._standalone(ProfileEditor(store.find_by_name("work")), 660)

    def engines(self):
        from kiwi_fox.ui.dialogs import EnginesDialog

        win, _w, _h = self._standalone(EnginesDialog(lambda: None), 600)
        return win, 600, 520


OUT.mkdir(parents=True, exist_ok=True)
stage()
Shots().run([])
