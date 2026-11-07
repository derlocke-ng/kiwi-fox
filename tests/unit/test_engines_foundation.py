"""The engine-selection foundation: Profile.engine, optional fingerprint, the
shared gecko prefs, the engine registry and the validator's network split.

These are the seams the stock-Firefox and Tor-Browser engines build on, so they
are tested here before either engine exists.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from kiwi_proxy import exits
from pydantic import ValidationError

from kiwi_fox.core import store
from kiwi_fox.core.engines import gecko, get_engine
from kiwi_fox.core.fingerprint import validator
from kiwi_fox.core.models import Fingerprint, Profile


def _exit() -> str:
    """A proxy in kiwi-proxy, as `kiwi-fox new NAME ENDPOINT` would make it."""
    from kiwi_proxy.models import Endpoint

    return exits.create("work", Endpoint(host="10.64.0.1", port=1080)).id


def _set_dns(profile, mode: str) -> None:
    """What `kiwi-proxy set NAME --dns MODE` does to the profile's exit."""
    ex = exits.load(profile.exit)
    ex.dns.mode = mode
    exits.save(ex)


# ----------------------------------------------------------- model compatibility
def test_old_profile_json_loads_as_camoufox():
    """A profile.json written before the engine field had no "engine" key."""
    old = {
        "id": "x",
        "name": "legacy",
        "created": "2026-01-01T00:00:00Z",
        "endpoint": {"host": "h", "port": 1080},
    }
    p = Profile.model_validate_json(json.dumps(old))
    assert p.engine == "camoufox"
    assert p.engine_version is None


def test_fingerprint_engine_stays_camoufox(fp):
    # Every fingerprint.json on disk carries "engine":"camoufox"; the narrowed
    # literal must still accept it and reject anything else.
    assert fp.engine == "camoufox"
    dumped = fp.model_dump()
    dumped["engine"] = "firefox"
    with pytest.raises(ValidationError):
        Fingerprint.model_validate(dumped)


def test_unknown_profile_engine_rejected():
    with pytest.raises(ValidationError):
        Profile(
            id="x",
            name="n",
            created=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
            engine="chrome",  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------- store.create
def test_create_camoufox_needs_fingerprint():
    with pytest.raises(store.StoreError, match="needs a fingerprint"):
        store.create("c", _exit(), None, engine="camoufox")


def test_create_firefox_rejects_a_fingerprint(fp):
    with pytest.raises(store.StoreError, match="no fingerprint"):
        store.create("f", _exit(), fp, engine="firefox")


def test_create_firefox_writes_no_fingerprint():
    p = store.create("f", _exit(), None, engine="firefox", engine_version="159.0")
    assert p.engine == "firefox"
    assert p.engine_version == "159.0"
    from kiwi_fox.core import paths

    assert not (paths.profile_dir(p.id) / "fingerprint.json").exists()
    assert store.fingerprint_of(p) is None
    # It survives a round-trip through disk.
    assert store.load(p.id).engine == "firefox"


def test_create_camoufox_still_works(fp):
    p = store.create("c", _exit(), fp, engine="camoufox")
    assert p.engine == "camoufox"
    assert store.fingerprint_of(p) is not None
    from kiwi_fox.core import paths

    assert (paths.profile_dir(p.id) / "fingerprint.json").exists()


def test_create_positional_fingerprint_defaults_camoufox(fp):
    # The call shape — create(name, exit, fp) — with the fingerprint positional.
    p = store.create("c", _exit(), fp)
    assert p.engine == "camoufox"


# --------------------------------------------------------------- engine registry
def test_get_engine_camoufox():
    assert get_engine("camoufox").name == "camoufox"


def test_get_engine_firefox():
    assert get_engine("firefox").name == "firefox"


def test_get_engine_torbrowser():
    assert get_engine("torbrowser").name == "torbrowser"


def test_get_engine_unknown():
    with pytest.raises(ValueError, match="unknown engine"):
        get_engine("chrome")


# ------------------------------------------------------------------ gecko prefs
def test_network_prefs_follow_the_exits_dns_mode(profile):
    assert gecko.network_prefs(profile)["network.proxy.socks_remote_dns"] is False
    _set_dns(profile, "remote")
    assert gecko.network_prefs(profile)["network.proxy.socks_remote_dns"] is True


def test_network_prefs_with_no_proxy_configure_none(profile):
    profile.exit = None
    prefs = gecko.network_prefs(profile)
    assert prefs["network.proxy.type"] == 0
    assert "network.proxy.socks" not in prefs
    assert prefs["network.dns.disablePrefetch"] is True  # the quiet prefs still hold
    assert validator.check_network_prefs(prefs, direct=True) == []
    assert validator.check_network_prefs(prefs) != [], "proxied check must not pass it"


def test_network_prefs_force_remote_dns_overrides_resolver(profile):
    assert exits.load(profile.exit).dns.mode == "resolver"
    prefs = gecko.network_prefs(profile, force_remote_dns=True)
    assert prefs["network.proxy.socks_remote_dns"] is True


def test_network_prefs_pin_the_dangerous_ones(profile):
    prefs = gecko.network_prefs(profile)
    assert prefs["network.proxy.failover_direct"] is False
    assert prefs["network.proxy.allow_bypass"] is False
    assert prefs["network.trr.mode"] == 5
    assert prefs["network.proxy.socks"] == "127.0.0.1"
    assert prefs["network.proxy.socks_port"] == 1080


# ------------------------------------------------------------- validator split
def test_check_network_prefs_passes_on_camoufox_prefs(fp, profile):
    prefs = get_engine("camoufox").prefs(fp, profile)
    assert validator.check_network_prefs(prefs) == []


def test_check_network_prefs_flags_a_direct_failover(profile):
    prefs = gecko.network_prefs(profile)
    prefs["network.proxy.failover_direct"] = True
    issues = validator.check_network_prefs(prefs)
    assert any(i.code == "prefs.network" for i in issues)


def test_required_prefs_still_hold_both_sets():
    # validate()'s old contract: the five keys, unchanged.
    assert validator.REQUIRED_PREFS == {**validator.COHERENCE_PREFS, **validator.NETWORK_PREFS}
    assert set(validator.NETWORK_PREFS) == {
        "network.proxy.failover_direct",
        "network.trr.mode",
    }
    assert "privacy.resistFingerprinting" in validator.COHERENCE_PREFS
