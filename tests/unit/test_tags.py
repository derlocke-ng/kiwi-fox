"""Tags: free-form, kept as typed, for grouping and finding profiles."""

from __future__ import annotations

from kiwi_proxy import exits

from kiwi_fox.core import store
from kiwi_fox.core.models import Endpoint


def _exit(name="work") -> str:
    return exits.create(name, Endpoint(host="10.64.0.1", port=1080)).id


def test_normalize_keeps_spelling_drops_blanks_and_duplicates():
    assert store.normalize_tags(["Shop, eu", "#eu", " ", "SHOP", "work"]) == ["Shop", "eu", "work"]
    assert store.normalize_tags([]) == []


def test_cli_new_set_list_and_show(capsys):
    from kiwi_fox import cli

    _exit("work")
    assert cli.main(["new", "a", "--exit", "work", "--engine", "firefox", "--tag", "shop,eu"]) == 0
    assert cli.main(["new", "b", "--exit", "work", "--engine", "firefox", "--tag", "work"]) == 0
    assert cli.main(["new", "c", "--exit", "work", "--engine", "firefox"]) == 0
    capsys.readouterr()
    assert store.find_by_name("a").tags == ["shop", "eu"]
    assert cli.main(["set", "a", "--tag", "de", "--untag", "eu"]) == 0
    assert store.find_by_name("a").tags == ["shop", "de"]
    assert cli.main(["show", "a"]) == 0
    assert "tags      shop, de" in capsys.readouterr().out
    assert cli.main(["list", "--tag", "SHOP"]) == 0
    out = capsys.readouterr().out
    assert "a " in out and "b " not in out and "shop,de" in out
    assert cli.main(["list", "--by-tag"]) == 0
    lines = [ln.split()[0] for ln in capsys.readouterr().out.splitlines()[1:]]
    assert lines == ["a", "b", "c"], "tagged first by their first tag, untagged last"
    assert cli.main(["list", "--tag", "nope"]) == 0
    assert "no profile is tagged" in capsys.readouterr().out
    assert cli.main(["set", "a", "--no-tags"]) == 0
    assert store.find_by_name("a").tags == []


def test_the_window_groups_by_the_first_tag():
    from types import SimpleNamespace

    from kiwi_fox.core.store import grouped_by_tag

    a = SimpleNamespace(name="a", tags=["shop", "eu"])
    b = SimpleNamespace(name="b", tags=["Work"])
    c = SimpleNamespace(name="c", tags=[])
    assert grouped_by_tag([a, b, c]) == [("shop", [a]), ("Work", [b]), ("Untagged", [c])]
    assert grouped_by_tag([c]) == [("Profiles", [c])]
