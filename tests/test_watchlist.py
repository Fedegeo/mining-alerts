from pathlib import Path

import pytest

from mining_alerts.models import Announcement
from mining_alerts.watchlist import Watchlist

WATCHLIST = Path(__file__).resolve().parents[1] / "config" / "watchlist.yaml"


@pytest.fixture(scope="module")
def wl():
    return Watchlist.load(WATCHLIST)


def labels(wl, title, summary="", hint=None):
    a = Announcement(title=title, url="u", source="t", summary=summary, company_hint=hint)
    return sorted(m.label for m in wl.match(a))


def test_real_watchlist_loads(wl):
    ids = {c.id for c in wl.companies}
    assert {"heliostar", "orion", "lithium_americas", "cornish_metals", "argentina_potash"} <= ids


def test_project_hit_with_company(wl):
    assert labels(wl, "Heliostar drills 10 g/t gold at Ana Paula") == ["Heliostar Metals / Ana Paula"]


def test_ambiguous_project_name_needs_context(wl):
    assert labels(wl, "Ana Paula wins singing contest") == []
    assert labels(wl, "Mina Ana Paula: avanza el permiso ambiental en Guerrero") == ["Heliostar Metals / Ana Paula"]


def test_bare_orion_needs_mining_context(wl):
    assert labels(wl, "Orion spacecraft completes test") == []
    assert labels(wl, "Orion provides $200M royalty financing for copper mine") == [
        "Orion Resource Partners (Orion Mine Finance)"]


def test_shared_project_tags_both_companies(wl):
    got = labels(wl, "Thacker Pass construction update")
    assert got == ["Lithium Americas / Thacker Pass", "Orion Resource Partners (Orion Mine Finance) / Thacker Pass"]


def test_company_hint_always_matches(wl):
    assert labels(wl, "Quarterly activities report", hint="lithium_energy") == ["Lithium Energy Limited"]


def test_spanish_accents_and_case(wl):
    assert labels(wl, "SOUTH CROFTY tin mine restart") == ["Cornish Metals / South Crofty"]
    assert labels(wl, "Argentina Potash avanza en El Ceibo, Neuquén") == ["Argentina Potash / El Ceibo"]


def test_word_boundaries(wl):
    # "Minto" must not match inside another word, and needs Yukon/copper context.
    assert labels(wl, "Mintonville bakery opens") == []
    assert labels(wl, "Yukon government update on Minto copper site") == ["Minto Mine (Yukon, Canada) / Minto"]


def test_duplicate_ids_rejected(tmp_path):
    p = tmp_path / "w.yaml"
    p.write_text("companies:\n - {id: a, name: A, aliases: [A]}\n - {id: a, name: B, aliases: [B]}\n")
    with pytest.raises(ValueError):
        Watchlist.load(p)
