"""Measure what a profile actually exposes, and diff two of them.

Claims about a fingerprint are worthless unless measured, and measuring has to
happen inside the profile's own namespace: the probe page is served from the
gateway on loopback, which the firewall permits, and read back from the server's
log. Nothing leaves the namespace.

The measurement runs in a *throwaway* browser: same engine config, same prefs,
same fonts, its own empty data directory. The profile's real browser is never
stopped and its data directory is never opened. The first version did both — it
killed the running session to get at the profile lock, and left the probe page in
the session history, where it came back at every launch as "Unable to connect".
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
import urllib.parse
from pathlib import Path

from . import geometry, launch, paths, podman, store
from .engines.camoufox import PROFILE_MOUNT
from .fingerprint import webgl
from .fingerprint import windows11 as w11
from .models import Profile

PROBE_PORT_BASE = 8900
PROBE_DIR = "/tmp/kf-probe"
PROBE_PAGE = "probe.html"

# Where each signal comes from. This is the audit: a value we never set cannot be
# called spoofed just because it looks plausible.
#   spoofed  we set it explicitly through the engine config
#   host     the real machine produces it; identical for every profile here
#   engine   the browser build decides it; same for every profile on one engine
#   derived  follows from something we set, without being set directly
# canvas.hash is "engine": Firefox randomises canvas readback per session by default
# and the engine's own canvas seed has no effect at the pinned tag (measured), so
# it differs between two runs of the *same* profile and says nothing about either.
SOURCES: dict[str, str] = {
    "navigator.userAgent": "spoofed",
    "navigator.platform": "spoofed",
    "navigator.oscpu": "spoofed",
    "navigator.language": "spoofed",
    "navigator.languages": "spoofed",
    "navigator.hardwareConcurrency": "spoofed",
    "navigator.maxTouchPoints": "engine",
    "navigator.pdfViewerEnabled": "engine",
    "navigator.deviceMemory": "engine",
    "navigator.webdriver": "engine",
    "navigator.doNotTrack": "engine",
    "screen.width": "spoofed",
    "screen.height": "spoofed",
    "screen.availWidth": "spoofed",
    "screen.availHeight": "spoofed",
    "screen.availLeft": "spoofed",
    "screen.availTop": "spoofed",
    "screen.colorDepth": "spoofed",
    "screen.pixelDepth": "spoofed",
    "screen.devicePixelRatio": "spoofed",
    "screen.orientation": "derived",
    "window.outer": "derived",
    "window.inner": "derived",
    "window.screenXY": "derived",
    "intl.timeZone": "spoofed",
    "intl.locale": "spoofed",
    "intl.calendar": "derived",
    "intl.numbering": "derived",
    "intl.tzOffset": "derived",
    "intl.formatted": "derived",
    "webgl.unmaskedVendor": "spoofed",
    "webgl.unmaskedRenderer": "spoofed",
    "webgl.vendor": "spoofed",
    "webgl.renderer": "spoofed",
    "webgl.version": "engine",
    "webgl.shadingLanguage": "engine",
    "webgl.maxTextureSize": "spoofed",
    "webgl.maxRenderbufferSize": "spoofed",
    "webgl.maxVertexAttribs": "spoofed",
    "webgl.maxViewportDims": "spoofed",
    "webgl.extensions": "spoofed",
    "webgl.renderHash": "host",
    "webgl.shaderPrecision": "spoofed",
    "webgl2.unmaskedVendor": "spoofed",
    "webgl2.unmaskedRenderer": "spoofed",
    "webgl2.vendor": "spoofed",
    "webgl2.renderer": "spoofed",
    "webgl2.renderHash": "host",
    "webgl2.shaderPrecision": "spoofed",
    "webgpu.available": "spoofed",
    "canvas.hash": "engine",
    "fonts": "spoofed",
    "audio.sampleRate": "spoofed",
    "audio.maxChannelCount": "spoofed",
    "audio.outputLatency": "spoofed",
    "audio.state": "engine",
    "domRect": "derived",
    "svg": "derived",
    "math": "engine",
    "css.colorScheme": "engine",
    "css.reducedMotion": "engine",
    "css.hdr": "host",
    "css.gamutP3": "host",
    "css.hover": "engine",
    "css.pointer": "engine",
    "css.scrollbar": "engine",
    "media.devices": "spoofed",
    "media.codecs": "engine",
    "speech": "spoofed",
    "storage.localStorage": "engine",
    "storage.indexedDB": "engine",
    "storage.quota": "host",
    "hardwarePerf.ms": "host",
    "hardwarePerf.checksum": "engine",
    "timing.precision": "engine",
}


class ProbeError(RuntimeError):
    pass


def _page() -> Path:
    page = Path(__file__).resolve().parent / PROBE_PAGE
    if not page.exists():
        raise ProbeError(f"cannot find {page}")
    return page


def flatten(data: dict, prefix: str = "") -> dict[str, object]:
    out: dict[str, object] = {}
    for key, value in data.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            out.update(flatten(value, f"{path}."))
        else:
            out[path] = value
    return out


def _port_for(profile_id: str) -> int:
    """A port per profile, so a stale server from another run cannot collide.

    Reusing one port meant a leftover server kept it, the replacement died with
    "address already in use", and the probe reported only that nothing came back.
    """
    return PROBE_PORT_BASE + (int(profile_id[:6], 16) % 90)


def _stop_servers(gateway: str) -> None:
    # procps may be missing from an older gateway image, where `pkill` silently
    # does nothing and a stale server keeps the port. python3 is always there.
    podman.exec_(
        gateway,
        [
            "python3",
            "-c",
            "import os,signal,glob\n"
            "for d in glob.glob('/proc/[0-9]*'):\n"
            "    try:\n"
            "        if b'http.server' in open(d+'/cmdline','rb').read():\n"
            "            os.kill(int(d.rsplit('/',1)[1]), signal.SIGTERM)\n"
            "    except Exception: pass",
        ],
    )


def _serve(gateway: str, port: int) -> None:
    podman.exec_(gateway, ["mkdir", "-p", PROBE_DIR])
    subprocess.run(  # noqa: S603
        ["podman", "cp", str(_page()), f"{gateway}:{PROBE_DIR}/{PROBE_PAGE}"],
        capture_output=True,
        check=False,
    )
    podman.exec_(gateway, ["sh", "-c", f"rm -f {PROBE_DIR}/server.log"])
    _stop_servers(gateway)
    time.sleep(1)
    subprocess.run(  # noqa: S603
        [
            "podman",
            "exec",
            "-d",
            gateway,
            "sh",
            "-c",
            f"cd {PROBE_DIR} && python3 -m http.server {port} "
            f"--bind 127.0.0.1 > {PROBE_DIR}/server.log 2>&1",
        ],
        capture_output=True,
        check=False,
    )
    time.sleep(2)
    ready = podman.exec_(
        gateway,
        [
            "sh",
            "-c",
            f"curl -s -o /dev/null -w '%{{http_code}}' http://127.0.0.1:{port}/{PROBE_PAGE}",
        ],
    ).stdout.strip()
    if ready != "200":
        raise ProbeError(f"probe server did not come up on port {port} (got {ready!r})")


def probe(profile: Profile, *, timeout: int = 70, raw: bool = False, skip: str = "") -> dict:
    """Run the probe in this profile's namespace and return what it saw.

    `raw` measures the machine instead of the profile: WebGL is left unspoofed so
    the host's own renderer comes back, and is remembered for the "host" mode.
    `skip` is a comma-separated list of collectors to leave out, for bisecting a
    native crash that no JavaScript handler can survive.
    """
    gateway = paths.gateway_name(profile.id)
    started_gateway = False
    if not podman.is_running(gateway):
        launch.start_gateway(profile)
        started_gateway = True

    fp = store.load_fingerprint(profile.id)
    subject = profile.model_copy(update={"webgl": "raw"}) if raw else profile
    name = f"{paths.PREFIX}-probe-{profile.id[:8]}"
    scratch = Path(tempfile.mkdtemp(prefix="probe-", dir=launch.runtime_dir(profile.id)))
    port = _port_for(profile.id)
    try:
        _serve(gateway, port)

        data = scratch / "browser-data"
        (scratch / "downloads").mkdir()
        # The profile's prefs, plus two that keep this run from leaving anything
        # behind or picking anything up: no session to restore, none to save.
        launch.write_user_js(
            subject,
            fp,
            data,
            extra={"browser.startup.page": 0, "browser.sessionstore.resume_from_crash": False},
        )
        geometry.prepare(subject, fp, data)
        launch.install_langpack(subject, fp, data)
        launch.write_fontconfig(profile, fp)

        spec = launch.browser_spec(subject, fp, gateway, None)
        spec.name = name
        real = paths.profile_dir(profile.id)
        swap = {
            str(real / "browser-data"): str(data),
            str(real / "downloads"): str(scratch / "downloads"),
        }
        spec.volumes = [(swap.get(src, src), dst, opts) for src, dst, opts in spec.volumes]
        if not any(dst == PROFILE_MOUNT and src == str(data) for src, dst, _o in spec.volumes):
            raise ProbeError("refusing to probe: could not redirect the browser's data directory")
        query = f"?skip={skip}" if skip else ""
        spec.args = [f"http://127.0.0.1:{port}/{PROBE_PAGE}{query}"]
        podman.rm(name)
        podman.start(spec)

        report = None
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(3)
            out = podman.exec_(
                gateway,
                ["sh", "-c", f"grep -o 'GET /report?[^ ]*' {PROBE_DIR}/server.log | head -1"],
            ).stdout.strip()
            if out:
                report = json.loads(urllib.parse.unquote(out.replace("GET /report?", "")))
                break
        if report is None:
            log = podman.logs(name, tail=15).strip() or "(browser produced no output)"
            served = podman.exec_(
                gateway,
                ["sh", "-c", f"grep -c 'GET /{PROBE_PAGE}' {PROBE_DIR}/server.log || true"],
            ).stdout.strip()
            raise ProbeError(
                "the probe page never reported back"
                f" (page fetched {served or '0'} time(s))\n"
                f"browser log:\n{log}"
            )
        if raw:
            # Only an unspoofed run says anything about the machine.
            webgl.remember_host_renderer((report.get("webgl") or {}).get("renderer"))
        # Engines before 156 open a window of their own choosing, so the screen
        # has to be chosen big enough to contain it: remember how tall it is here.
        # Later engines open the size they are told, which says nothing of the host.
        outer = (report.get("window") or {}).get("outer")
        if (
            isinstance(outer, list)
            and len(outer) == 2
            and not w11.engine_sizes_window(fp.engine_version)
        ):
            w11.remember_host_window_height(outer[1])
        return report
    finally:
        podman.rm(name)
        if started_gateway:
            # Not launch.stop(): that would also remove a browser the user started
            # in the meantime. The gateway refuses to go while one depends on it.
            if not podman.is_running(paths.browser_name(profile.id)):
                podman.rm(gateway)
                podman.secret_rm(launch.creds_secret_name(profile.id))
        else:
            _stop_servers(gateway)
        shutil.rmtree(scratch, ignore_errors=True)


def audit(report: dict, profile: Profile) -> list[str]:
    """What in a probe report contradicts the Windows claim. Empty means coherent.

    Each line is something a page can check in one comparison, which is exactly
    why it is checked here first.
    """
    problems: list[str] = []
    for ctx in ("webgl", "webgl2"):
        gl = report.get(ctx) or {}
        if profile.webgl == "off":
            if gl.get("available"):
                problems.append(f"{ctx}: WebGL is on although the profile turns it off")
            continue
        if not gl.get("available"):
            problems.append(f"{ctx}: no context — a Windows desktop without WebGL is rare")
            continue
        masked, unmasked = gl.get("renderer"), gl.get("unmaskedRenderer")
        # With "show the exact model" the two differ on purpose, the way they do
        # in a Firefox whose sanitiser was switched off: one names the card, the
        # other the group that card is in.
        deliberate = profile.webgl_exact and webgl.firefox_masked(str(unmasked)) == masked
        if masked != unmasked and not deliberate:
            problems.append(
                f"{ctx}: RENDERER {masked!r} differs from the unmasked {unmasked!r}; "
                "in Firefox they are the same string"
            )
        if gl.get("vendor") != webgl.MASKED_VENDOR:
            problems.append(f"{ctx}: VENDOR is {gl.get('vendor')!r}, Firefox always says 'Mozilla'")
        if not str(unmasked or "").startswith("ANGLE ("):
            problems.append(
                f"{ctx}: renderer {unmasked!r} is not Direct3D wording — it names Linux"
            )
        extras = gl.get("nonWindowsExtensions") or []
        if extras:
            problems.append(f"{ctx}: extensions Windows does not have: {', '.join(extras)}")
    win, screen = report.get("window") or {}, report.get("screen") or {}
    inner, avail = (win.get("inner") or [0, 0])[1], screen.get("availHeight") or 0
    if inner and avail and inner > avail:
        problems.append(f"window: innerHeight {inner} exceeds screen.availHeight {avail}")
    outer = win.get("outer") or [0, 0]
    for size, name, limit in (
        (outer[0], "Width", screen.get("availWidth") or 0),
        (outer[1], "Height", avail),
    ):
        if size and limit and size > limit:
            problems.append(
                f"window: outer{name} {size} exceeds screen.avail{name} {limit} — "
                "a window larger than its own screen"
            )
    if not report.get("speech"):
        problems.append("speech: no voices — every Windows install has some")
    devices = (report.get("media") or {}).get("devices")
    if devices is None:
        problems.append("media: enumerateDevices() failed")
    if (report.get("webgpu") or {}).get("available"):
        problems.append("webgpu: present, and it would name the real adapter")
    ua = (report.get("navigator") or {}).get("userAgent", "")
    if "Windows NT 10.0" not in ua or "Camoufox" in ua:
        problems.append(f"navigator: user agent is {ua!r}")
    return problems


def compare(a: dict, b: dict) -> list[tuple[str, str, str, str, bool]]:
    """-> (path, source, value_a, value_b, differs), ordered for reading."""
    fa, fb = flatten(a), flatten(b)
    rows = []
    for path in sorted(set(fa) | set(fb)):
        va, vb = fa.get(path), fb.get(path)
        source = SOURCES.get(path, SOURCES.get(path.split(".")[0], "unknown"))
        rows.append((path, source, _short(va), _short(vb), va != vb))
    order = {"spoofed": 0, "derived": 1, "host": 2, "engine": 3, "unknown": 4}
    rows.sort(key=lambda r: (order.get(r[1], 9), r[0]))
    return rows


def _short(value: object, width: int = 46) -> str:
    text = json.dumps(value) if not isinstance(value, str) else value
    text = text.replace("\n", " ")
    return text if len(text) <= width else text[: width - 1] + "…"
