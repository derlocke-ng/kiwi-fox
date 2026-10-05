#!/usr/bin/env python3
"""Refresh src/kiwi_fox/core/fingerprint/data/webgl-windows.json from upstream.

Camoufox ships a database of WebGL fingerprints collected from real browsers
(pythonlib/camoufox/webgl/webgl_data.db). This keeps the Windows hardware records
Firefox still produces and drops everything else. Run it when the pinned engine
tag changes:

    curl -LO https://raw.githubusercontent.com/daijro/camoufox/<tag>/pythonlib/camoufox/webgl/webgl_data.db
    tools/import-webgl-data.py webgl_data.db <tag>
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "src/kiwi_fox/core/fingerprint/data/webgl-windows.json"

# A software rasteriser is the strongest "this is a virtual machine" signal there
# is, so those rows are never offered.
SOFTWARE = ("Microsoft Basic Render Driver", "SwiftShader", "llvmpipe")
KEEP = (
    "webGl:parameters",
    "webGl2:parameters",
    "webGl:supportedExtensions",
    "webGl2:supportedExtensions",
    "webGl:shaderPrecisionFormats",
    "webGl2:shaderPrecisionFormats",
)


def main(db: str, tag: str) -> int:
    rows = sqlite3.connect(db).execute(
        "select vendor, renderer, win, data from webgl_fingerprints where win > 0"
    )
    merged: dict[str, dict] = {}
    for vendor, renderer, weight, blob in rows:
        data = json.loads(blob)
        # Current Firefox always appends ", or similar"; rows without it predate
        # the sanitiser. Feature level below 11_0 and WebGL1-only rows are
        # hardware nobody runs Windows 11 on.
        if not renderer.endswith(", or similar") or "vs_5_0 ps_5_0" not in renderer:
            continue
        if any(s in renderer for s in SOFTWARE) or not data.get("webGl2Enabled"):
            continue
        if renderer in merged:
            if any(merged[renderer][k] != data[k] for k in KEEP):
                raise SystemExit(f"conflicting records for {renderer!r}")
            merged[renderer]["share"] = round(merged[renderer]["share"] + weight, 4)
            continue
        merged[renderer] = {
            "vendor": vendor,
            "renderer": renderer,
            "share": round(weight, 4),
            **{k: data[k] for k in KEEP},
        }
    records = sorted(merged.values(), key=lambda r: -r["share"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "_source": f"daijro/camoufox {tag}: pythonlib/camoufox/webgl/webgl_data.db, "
                "table webgl_fingerprints, win > 0",
                "_license": "MPL-2.0, as the repository it is extracted from "
                "(https://github.com/daijro/camoufox)",
                "_note": "Real Windows Firefox WebGL records. share is that database's "
                "weight for Windows. contextAttributes are dropped on purpose: they "
                "depend on what the page asked for, so they are never spoofed.",
                "records": records,
            },
            indent=1,
        )
        + "\n"
    )
    for r in records:
        print(f"{r['share']:.4f}  {r['renderer']}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
