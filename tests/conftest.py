"""kiwi-fox runs on kiwi-proxy (gateways, providers, DNS), so the tests need it
importable: a sibling checkout (``../kiwi-proxy/src``) or ``KIWI_PROXY_SRC``. An
installed copy (``~/.local/lib/kiwi-proxy``) works too. Unlike a plugin's tests,
these cannot be skipped without it — nearly every module imports it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _find_kiwi_proxy_src() -> Path | None:
    env = os.environ.get("KIWI_PROXY_SRC")
    candidates = [Path(env)] if env else []
    candidates += [
        REPO.parent / "kiwi-proxy" / "src",
        Path.home() / "kiwi-proxy" / "src",
        Path(os.environ.get("KIWI_PREFIX") or Path.home() / ".local") / "lib" / "kiwi-proxy",
    ]
    for c in candidates:
        if (c / "kiwi_proxy" / "gateway.py").exists():
            return c
    return None


_src = _find_kiwi_proxy_src()
if _src and str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

try:
    import kiwi_proxy  # noqa: F401
except ImportError as exc:  # pragma: no cover - a setup problem, not a test
    raise SystemExit(
        "kiwi-proxy not found: clone https://github.com/derlocke-ng/kiwi-proxy beside "
        "this repo, or set KIWI_PROXY_SRC to its src/ directory"
    ) from exc
