"""Kiwi Fox — isolated browser identities in rootless Podman: Camoufox, Firefox, Tor Browser."""

__version__ = "0.11.0"
# The GTK application's id. The desktop entry and the icon are named after it
# (data/<id>.desktop, <id>.svg), which is how GNOME on Wayland connects the
# window to its entry: the app-id of the window is this string. A profile's own
# entry (core/desktop.py) carries it too.
APP_ID = "eu.kiwinetwork.KiwiFox"
