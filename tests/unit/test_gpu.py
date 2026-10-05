"""Whether the browser reaches a GPU is planned from sysfs and then measured.

The outputs below are the engine's own probe, captured on a hybrid laptop whose
panel hangs off the NVIDIA card — the machine where "the render node exists, so
rendering is hardware" turned out to be false.
"""

import json

import pytest

from kiwi_fox.core import gpu
from kiwi_fox.core.fingerprint import webgl

AMD = ("amdgpu", "0x1002", "0x1681")
NVIDIA = ("nvidia", "0x10de", "0x28e0")
INTEL = ("i915", "0x8086", "0x3e9b")

# What the engine's probe printed in each container setup, verbatim.
PROBE_SOFTWARE = (
    "WARNING\nlibpci missing\nDRI_DRIVER\nswrast\nVENDOR\nMesa\n"
    "RENDERER\nllvmpipe (LLVM 21.1.8, 256 bits)\nVERSION\n4.5 (Compatibility Profile) Mesa 25.3.6\n"
    "TFP\nTRUE\nMESA_ACCELERATED\nFALSE\nTEST_TYPE\nEGL\n"
)
PROBE_PRIME = (
    "WARNING\nlibpci missing\nDRI_DRIVER\nradeonsi\nVENDOR\nAMD\n"
    "RENDERER\nAMD Radeon 660M (radeonsi, rembrandt, LLVM 21.1.8, DRM 3.64, 7.1.6-201.fc44.x86_64)\n"
    "VERSION\n4.6 (Compatibility Profile) Mesa 25.3.6\nTFP\nTRUE\nWARNING\nCannot find DRM device\n"
    "DRM_RENDERDEVICE\n/dev/dri/renderD128\nTEST_TYPE\nEGL\n"
)
PROBE_NVIDIA = (
    "WARNING\nlibpci missing\nVENDOR\nNVIDIA Corporation\n"
    "RENDERER\nNVIDIA GeForce RTX 4060 Laptop GPU/PCIe/SSE2\nVERSION\n4.6.0 NVIDIA 610.57.04\n"
    "TFP\nTRUE\nDRM_RENDERDEVICE\n/dev/dri/renderD129\nMESA_VENDOR_ID\n0x10de\n"
    "MESA_DEVICE_ID\n0x28e0\nTEST_TYPE\nEGL\n"
)


@pytest.fixture
def host(tmp_path, monkeypatch):
    """Build a fake /sys/class/drm and /dev/dri: host(primary_first, other, cdi=...)."""
    monkeypatch.undo()  # the suite-wide fixture pins plan(); these tests are about plan()
    for var in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME"):
        monkeypatch.setenv(var, str(tmp_path / var.lower()))
    monkeypatch.delenv("KIWI_FOX_GPU", raising=False)
    drm, dev, cdi = tmp_path / "sys", tmp_path / "dev", tmp_path / "cdi.yaml"
    dev.mkdir()
    monkeypatch.setattr(gpu, "DRM", drm)
    monkeypatch.setattr(gpu, "DEV", dev)
    monkeypatch.setattr(gpu, "CDI_SPECS", (cdi,))

    def build(*gpus, cdi_present=False, primary=0):
        for index, (driver, vendor, device) in enumerate(gpus):
            name = f"renderD{128 + index}"
            pci = drm / name / "device"
            (tmp_path / "drivers" / driver).mkdir(parents=True, exist_ok=True)
            pci.mkdir(parents=True)
            (pci / "driver").symlink_to(tmp_path / "drivers" / driver)
            (pci / "vendor").write_text(vendor + "\n")
            (pci / "device").write_text(device + "\n")
            (pci / "boot_vga").write_text("1\n" if index == primary else "0\n")
            (dev / name).touch()
        if cdi_present:
            cdi.write_text("cdiVersion: 0.5.0\n")

    return build


def test_one_gpu_mesa_can_drive(host):
    host(AMD)
    plan = gpu.plan()
    assert (plan.kind, plan.family, plan.env) == ("mesa", "amd", {})
    assert [d.rsplit("/", 1)[1] for d in plan.devices] == ["renderD128"]


def test_desktop_on_nvidia_uses_the_hosts_driver_when_it_can_be_injected(host):
    # The laptop this was found on: integrated AMD first, panel on the NVIDIA card.
    host(AMD, NVIDIA, cdi_present=True, primary=1)
    plan = gpu.plan()
    assert (plan.kind, plan.family) == ("nvidia", "nvidia")
    assert plan.devices == ("nvidia.com/gpu=all",)


def test_desktop_on_nvidia_without_container_support_offloads_to_the_other_gpu(host):
    host(AMD, NVIDIA, primary=1)
    plan = gpu.plan()
    assert (plan.kind, plan.family) == ("mesa-prime", "amd")
    # Mesa has to be able to open the GPU the desktop names, then move elsewhere.
    assert [d.rsplit("/", 1)[1] for d in plan.devices] == ["renderD128", "renderD129"]
    assert plan.env == {"DRI_PRIME": "1002:1681"}
    assert "NVIDIA" in plan.note


def test_desktop_on_the_integrated_gpu_ignores_an_idle_nvidia_card(host):
    host(INTEL, NVIDIA, cdi_present=True, primary=0)
    plan = gpu.plan()
    assert (plan.kind, plan.family) == ("mesa", "intel")
    assert len(plan.devices) == 1


def test_nvidia_only(host):
    host(NVIDIA, cdi_present=True)
    assert gpu.plan().kind == "nvidia"


def test_nvidia_only_without_container_support_is_software_and_says_why(host):
    host(NVIDIA)
    plan = gpu.plan()
    assert (plan.kind, plan.devices, plan.family) == ("software", (), None)
    assert "nvidia-container-toolkit" in plan.note
    assert not gpu.accelerated()
    assert "SOFTWARE" in gpu.describe() and "virtual machine" in gpu.describe()


def test_no_gpu_at_all(host):
    host()
    assert gpu.plan().kind == "software"


def test_the_choice_can_be_forced(host, monkeypatch):
    host(AMD, NVIDIA, cdi_present=True, primary=1)
    assert gpu.plan("mesa").kind == "mesa-prime"
    assert gpu.plan("software").kind == "software"
    monkeypatch.setenv("KIWI_FOX_GPU", "mesa")
    assert gpu.plan().kind == "mesa-prime"
    monkeypatch.setenv("KIWI_FOX_GPU", "software")
    assert gpu.plan().devices == ()


@pytest.mark.parametrize(
    "text,accelerated,series",
    [
        (PROBE_SOFTWARE, False, None),
        (PROBE_PRIME, True, "radeon-r9-200"),
        (PROBE_NVIDIA, True, "geforce-gtx-980"),
        ("", False, None),
    ],
)
def test_probe_output_is_read_for_what_it_says(text, accelerated, series):
    seen = gpu.parse_probe(text)
    assert seen["accelerated"] is accelerated
    hit = webgl.series_for(seen["renderer"])
    assert (hit.key if hit else None) == series


def test_probe_warnings_are_kept():
    assert gpu.parse_probe(PROBE_PRIME)["warnings"] == ["libpci missing", "Cannot find DRM device"]
    assert gpu.parse_probe(PROBE_PRIME)["device"] == "/dev/dri/renderD128"


class FakeRun:
    def __init__(self, stdout):
        self.stdout, self.stderr, self.cmd = stdout, "", None

    def __call__(self, cmd, **_kwargs):
        self.cmd = cmd
        return self


def test_measure_runs_the_engines_own_helper_with_the_planned_devices(host, tmp_path, monkeypatch):
    host(AMD, NVIDIA, primary=1)
    engine = tmp_path / "engine"
    engine.mkdir()
    (engine / "gfxtest").touch()
    run = FakeRun(PROBE_PRIME)
    monkeypatch.setattr(gpu.subprocess, "run", run)
    seen = gpu.measure(engine)
    cmd = " ".join(run.cmd)
    assert "--entrypoint /opt/camoufox/gfxtest" in cmd and cmd.endswith("glx -f 1 -w")
    assert "--network none" in cmd and "--cap-drop all" in cmd
    assert cmd.count("--device") == 2 and "-e DRI_PRIME=1002:1681" in cmd
    assert seen["accelerated"] and seen["kind"] == "mesa-prime"
    # and it is remembered, for prefs and for the host's GPU series
    assert gpu.measurement()["renderer"].startswith("AMD Radeon 660M")
    assert gpu.accelerated()
    assert webgl.host_series() == (webgl.BY_KEY["radeon-r9-200"], "measured")
    assert gpu.describe().startswith("hardware — AMD Radeon 660M")


def test_older_engines_use_the_older_helper(host, tmp_path, monkeypatch):
    host(AMD)
    engine = tmp_path / "engine"
    engine.mkdir()
    (engine / "glxtest").touch()
    run = FakeRun(PROBE_PRIME)
    monkeypatch.setattr(gpu.subprocess, "run", run)
    gpu.measure(engine)
    assert "--entrypoint /opt/camoufox/glxtest" in " ".join(run.cmd)
    assert run.cmd[-3:] == ["-f", "1", "-w"]


def test_a_software_measurement_overrules_an_optimistic_plan(host, tmp_path, monkeypatch):
    # The original bug in one test: a render node exists, the plan says "mesa",
    # and the probe says llvmpipe. Believe the probe.
    host(AMD)
    engine = tmp_path / "engine"
    engine.mkdir()
    (engine / "gfxtest").touch()
    monkeypatch.setattr(gpu.subprocess, "run", FakeRun(PROBE_SOFTWARE))
    assert gpu.accelerated(), "unmeasured: go by the plan"
    gpu.measure(engine)
    assert gpu.plan().kind == "mesa"
    assert not gpu.accelerated()
    assert "SOFTWARE" in gpu.describe()
    assert webgl.host_series()[1] != "measured", "llvmpipe is not a card to report"


def test_a_measurement_taken_for_another_setup_is_not_trusted(host, tmp_path, monkeypatch):
    host(AMD, NVIDIA, cdi_present=True, primary=1)
    engine = tmp_path / "engine"
    engine.mkdir()
    (engine / "gfxtest").touch()
    monkeypatch.setattr(gpu.subprocess, "run", FakeRun(PROBE_NVIDIA))
    gpu.measure(engine)
    assert gpu.measurement()["kind"] == "nvidia"
    monkeypatch.setenv("KIWI_FOX_GPU", "mesa")
    assert gpu.measurement() is None


def test_an_engine_without_a_helper_cannot_be_hardware(host, tmp_path):
    host(AMD)
    engine = tmp_path / "engine"
    engine.mkdir()
    seen = gpu.measure(engine)
    assert not seen["accelerated"] and "no GPU probe helper" in seen["warnings"][0]
    assert json.loads((gpu._file()).read_text())["kind"] == "mesa"


# ------------------------------------------------- which helper an engine wants
def _libxul(tmp_path, *chunks: bytes):
    (tmp_path / "libxul.so").write_bytes(b"\x7fELF" + b"\x00".join(chunks) + b"\x00")
    return tmp_path


def test_156_wants_gfxtest_although_the_old_names_are_still_in_the_binary(tmp_path):
    from kiwi_fox.core.engines import fetch

    # 156 names the binary in a UTF-16 literal and keeps "glxtest"/"vaapitest" as
    # log labels. A byte search for the labels called a complete engine incapable.
    engine = _libxul(tmp_path, b"junk", b"glxtest", b"vaapitest", "gfxtest".encode("utf-16-le"))
    assert fetch.expected_gl_helpers(engine) == ["gfxtest"]
    assert not fetch.can_render_in_hardware(engine)
    (engine / "gfxtest").touch()
    assert fetch.can_render_in_hardware(engine)


def test_before_156_the_two_separate_helpers_are_wanted(tmp_path):
    from kiwi_fox.core.engines import fetch

    engine = _libxul(tmp_path, b"junk", b"glxtest", b"vaapitest")
    assert fetch.expected_gl_helpers(engine) == ["glxtest", "vaapitest"]
