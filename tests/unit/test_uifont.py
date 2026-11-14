"""The desktop's interface font reaches the browser's own interface."""

from __future__ import annotations

from kiwi_fox.core import uifont


def test_the_desktops_font_name_is_read_with_its_size():
    assert uifont.parse("Adwaita Sans 12") == ("Adwaita Sans", 12.0)
    assert uifont.parse("Cantarell Bold 11.5") == ("Cantarell Bold", 11.5)
    assert uifont.parse("") is None and uifont.parse("Sans") is None
    assert uifont.parse("Sans 400") is None  # not a size anyone reads


def test_the_settings_file_keeps_the_images_icon_theme_and_adds_the_font():
    text = uifont.gtk_settings(("Adwaita Sans", 12.0, 1.0))
    assert text == "[Settings]\ngtk-icon-theme-name=AdwaitaLegacy\ngtk-font-name=Adwaita Sans 12\n"
    assert "gtk-xft-dpi=122880\n" in uifont.gtk_settings(("Sans", 11.0, 1.25))  # 96 dpi x 1.25
    assert uifont.gtk_settings(None) == uifont.BASE


def test_only_stock_firefox_gets_the_fonts_files(tmp_path, monkeypatch):
    monkeypatch.setenv("KF_UI_FONT", "Adwaita Sans 12")
    monkeypatch.setattr(uifont, "_gsetting", lambda key: "")
    fonts = tmp_path / "adwaita"
    fonts.mkdir()
    monkeypatch.setattr(uifont, "font_dirs", lambda family: [fonts])
    for engine in ("camoufox", "torbrowser"):
        vols = uifont.volumes(tmp_path, engine)
        assert [v[1] for v in vols] == [uifont.SETTINGS_MOUNT]  # the size; never the family's files
    vols = uifont.volumes(tmp_path, "firefox")
    assert (str(fonts), "/usr/share/kf-firefox-fonts/host-ui-0", "ro") in vols
    assert "gtk-font-name=Adwaita Sans 12" in (tmp_path / "gtk-settings.ini").read_text()
    monkeypatch.delenv("KF_UI_FONT")
    assert uifont.volumes(tmp_path, "firefox") == []  # no desktop to ask: as before
