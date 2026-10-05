"""Windows 11 font families mapped to the files Camoufox bundles.

Source of truth is the engine's own `fonts/windows/` directory (144 files in
v152.0.4-beta.30), so we never redistribute a font ourselves — we select from
what the pinned engine already ships.

CORE is what any Windows 11 install has. OPTIONAL is the supplemental /
language-pack block, which genuinely varies between real machines; that
variation is our main per-profile differentiator, because the font set is the
one thing measured to move canvas, DOMRect and SVG text metrics.
"""

from __future__ import annotations

# family -> bundled filenames
CORE: dict[str, list[str]] = {
    "Arial": ["arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"],
    "Arial Black": ["ariblk.ttf"],
    "Bahnschrift": ["bahnschrift.ttf"],
    "Calibri": [
        "calibri.ttf",
        "calibrib.ttf",
        "calibrii.ttf",
        "calibriz.ttf",
        "calibril.ttf",
        "calibrili.ttf",
    ],
    "Cambria": ["cambria.ttc", "cambriab.ttf", "cambriai.ttf", "cambriaz.ttf"],
    "Candara": [
        "Candara.ttf",
        "Candarab.ttf",
        "Candarai.ttf",
        "Candaraz.ttf",
        "Candaral.ttf",
        "Candarali.ttf",
    ],
    "Comic Sans MS": ["comic.ttf", "comicbd.ttf", "comici.ttf", "comicz.ttf"],
    "Consolas": ["consola.ttf", "consolab.ttf", "consolai.ttf", "consolaz.ttf"],
    "Constantia": ["constan.ttf", "constanb.ttf", "constani.ttf", "constanz.ttf"],
    "Corbel": [
        "corbel.ttf",
        "corbelb.ttf",
        "corbeli.ttf",
        "corbelz.ttf",
        "corbell.ttf",
        "corbelli.ttf",
    ],
    "Courier New": ["cour.ttf", "courbd.ttf", "couri.ttf", "courbi.ttf"],
    "Ebrima": ["ebrima.ttf", "ebrimabd.ttf"],
    "Franklin Gothic Medium": ["framd.ttf", "framdit.ttf"],
    "Gabriola": ["Gabriola.ttf"],
    "Gadugi": ["gadugi.ttf", "gadugib.ttf"],
    "Georgia": ["georgia.ttf", "georgiab.ttf", "georgiai.ttf", "georgiaz.ttf"],
    "HoloLens MDL2 Assets": ["holomdl2.ttf"],
    "Impact": ["impact.ttf"],
    "Ink Free": ["Inkfree.ttf"],
    "Leelawadee UI": ["LeelawUI.ttf", "LeelaUIb.ttf", "LeelUIsl.ttf"],
    "Lucida Console": ["lucon.ttf"],
    "Lucida Sans Unicode": ["l_10646.ttf"],
    "Marlett": ["marlett.ttf"],
    "Microsoft Sans Serif": ["micross.ttf"],
    "MV Boli": ["mvboli.ttf"],
    "Nirmala UI": ["Nirmala.ttf", "NirmalaB.ttf", "NirmalaS.ttf"],
    "Palatino Linotype": ["pala.ttf", "palab.ttf", "palai.ttf", "palabi.ttf"],
    "Segoe Fluent Icons": ["SegoeIcons.ttf"],
    "Segoe MDL2 Assets": ["segmdl2.ttf"],
    "Segoe Print": ["segoepr.ttf", "segoeprb.ttf"],
    "Segoe Script": ["segoesc.ttf", "segoescb.ttf"],
    "Segoe UI": [
        "segoeui.ttf",
        "segoeuib.ttf",
        "segoeuii.ttf",
        "segoeuiz.ttf",
        "segoeuil.ttf",
        "segoeuisl.ttf",
        "seguibl.ttf",
        "seguibli.ttf",
        "seguili.ttf",
        "seguisb.ttf",
        "seguisbi.ttf",
        "seguisli.ttf",
    ],
    "Segoe UI Emoji": ["seguiemj.ttf"],
    "Segoe UI Symbol": ["seguisym.ttf"],
    "Segoe UI Variable": ["SegUIVar.ttf"],
    "Sitka": ["SitkaVF.ttf", "SitkaVF-Italic.ttf"],
    "Sylfaen": ["sylfaen.ttf"],
    "Symbol": ["symbol.ttf"],
    "Tahoma": ["tahoma.ttf", "tahomabd.ttf"],
    "Times New Roman": ["times.ttf", "timesbd.ttf", "timesi.ttf", "timesbi.ttf"],
    "Trebuchet MS": ["trebuc.ttf", "trebucbd.ttf", "trebucit.ttf", "trebucbi.ttf"],
    "Verdana": ["verdana.ttf", "verdanab.ttf", "verdanai.ttf", "verdanaz.ttf"],
    "Webdings": ["webdings.ttf"],
    "Wingdings": ["wingding.ttf"],
}

# Supplemental / language-pack families. Present on some real machines, absent
# on others, which is exactly why they are the per-profile lever.
OPTIONAL: dict[str, list[str]] = {
    "Javanese Text": ["javatext.ttf"],
    "Malgun Gothic": ["malgun.ttf", "malgunbd.ttf", "malgunsl.ttf"],
    "Microsoft Himalaya": ["himalaya.ttf"],
    "Microsoft JhengHei": ["msjh.ttc", "msjhbd.ttc", "msjhl.ttc"],
    "Microsoft New Tai Lue": ["ntailu.ttf", "ntailub.ttf"],
    "Microsoft PhagsPa": ["phagspa.ttf", "phagspab.ttf"],
    "Microsoft Tai Le": ["taile.ttf", "taileb.ttf"],
    "Microsoft YaHei": ["msyh.ttc", "msyhbd.ttc", "msyhl.ttc"],
    "Microsoft Yi Baiti": ["msyi.ttf"],
    "MingLiU-ExtB": ["mingliub.ttc"],
    "Mongolian Baiti": ["monbaiti.ttf"],
    "MS Gothic": ["msgothic.ttc"],
    "Myanmar Text": ["mmrtext.ttf", "mmrtextb.ttf"],
    "Segoe UI Historic": ["seguihis.ttf"],
    "SimSun": ["simsun.ttc", "simsunb.ttf"],
    "Yu Gothic": ["YuGothR.ttc", "YuGothB.ttc", "YuGothL.ttc", "YuGothM.ttc"],
}

# CJK families travel together on a real install: a machine with the Japanese
# language feature has MS Gothic *and* Yu Gothic, not one of them.
BUNDLES: list[list[str]] = [
    ["MS Gothic", "Yu Gothic"],
    ["Microsoft YaHei", "SimSun"],
    ["Microsoft JhengHei", "MingLiU-ExtB"],
    ["Malgun Gothic"],
]

# Fonts that fingerprinters actually probe for, which real Windows machines
# genuinely vary on (Office, Adobe and user installs put these on Windows).
#
# This exists because our Windows-family variation was invisible: neoprint probes
# a fixed 48-family list, every Windows entry on it (Arial, Calibri, Cambria,
# Consolas, Segoe UI, Tahoma, Georgia, Times New Roman, Verdana, Courier New) is
# mandatory and therefore in every profile, and nothing we varied — the CJK and
# complex-script block — appears on their list at all. So two profiles with 53 and
# 48 families reported an identical font set.
#
# Open-licensed only, never committed here: the image installs them from the
# distro, and a profile's fontconfig exposes just its own subset. Deliberately
# excludes Liberation, DejaVu, Noto and Roboto, which neoprint categorises as
# Linux fonts and would be a giveaway on a Windows claim.
THIRD_PARTY: dict[str, str] = {
    "Open Sans": "open-sans",
    "Lato": "lato",
    "Source Sans 3": "source-sans",
}
THIRD_PARTY_ROOT = "/usr/share/kf-fonts"

EMOJI_FALLBACK = "TwemojiMozilla.ttf"


def files_for(families: list[str]) -> list[str]:
    """Bundled files only — third-party families come from their own directories."""
    out: list[str] = []
    for fam in families:
        out.extend(CORE.get(fam) or OPTIONAL.get(fam, []))
    return sorted(set(out))


def third_party_dirs(families: list[str]) -> list[str]:
    return [f"{THIRD_PARTY_ROOT}/{THIRD_PARTY[f]}" for f in families if f in THIRD_PARTY]


def all_core_families() -> list[str]:
    return sorted(CORE)


def all_optional_families() -> list[str]:
    return sorted(OPTIONAL)


def all_third_party_families() -> list[str]:
    return sorted(THIRD_PARTY)
