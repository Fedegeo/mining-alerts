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


def test_royalty_companies(wl):
    assert labels(wl, "Elemental Royalty reports record Q3 revenue") == ["Elemental Royalty"]
    assert labels(wl, "EMX Royalty and Elemental Altus complete merger") == ["Elemental Royalty"]
    assert labels(wl, "Altius Minerals acquires new copper royalty") == ["Altius Minerals"]
    assert labels(wl, "Altius Capital launches new tech fund") == []
    assert labels(wl, "Orion Resources closes copper stream financing") == [
        "Orion Resource Partners (Orion Mine Finance)"]


def test_gold_com(wl):
    assert labels(wl, "Gold.com reports fiscal first quarter results") == [
        "Gold.com (formerly A-Mark Precious Metals)"]
    # used as a price source in an unrelated story -> no alert
    assert labels(wl, "Gold hits record high, according to data from Gold.com") == []


def test_pmet_and_project(wl):
    assert labels(wl, "PMET Advances Shaakichiuwaanaan Development with 30,000 m Drill Program") == [
        "PMET Resources (formerly Patriot Battery Metals) / Shaakichiuwaanaan"]
    assert labels(wl, "PMET Announces up to C$130 Million Financings") == [
        "PMET Resources (formerly Patriot Battery Metals)"]
    assert labels(wl, "Patriot Battery Metals drills spodumene at CV13 pegmatite")[0].endswith("Shaakichiuwaanaan")
    assert labels(wl, "PMET levels in blood samples") == []


def test_context_words_match_word_starts(wl):
    # "royalty" context also accepts "royalties"; "drill" accepts "drilling"
    assert labels(wl, "Altius Minerals adds two royalties") == ["Altius Minerals"]


def test_exclude_vetoes_lookalike_companies(wl):
    assert labels(wl, "Minto Group buys Ottawa office tower near mine shaft memorial") == []
    assert labels(wl, "Orion Energy Systems raises funding for LED lighting") == []
    assert labels(wl, "Alpaca Markets raises funding for trading API in mining stocks") == []


def test_exclude_does_not_block_full_name(wl):
    got = labels(wl, "Orion Resource Partners invests in Orion Minerals copper project")
    assert got == ["Orion Resource Partners (Orion Mine Finance)"]


def test_lint(wl):
    issues = wl.lint()
    levels = {lvl for lvl, _ in issues}
    assert "ERROR" not in levels
    assert any(lvl == "CONFIRM" and "Access World" in msg for lvl, msg in issues)
    assert any(lvl == "INFO" and "Altius" in msg for lvl, msg in issues)


def test_lint_flags_risky_and_broken(tmp_path):
    p = tmp_path / "w.yaml"
    p.write_text("companies:\n - {id: a, name: A, aliases: [Zed]}\n"
                 " - {id: b, name: B, aliases: [Bee Co], rss: [not-a-url]}\n")
    issues = Watchlist.load(p).lint()
    assert issues[0][0] == "ERROR"
    msgs = " ".join(m for _, m in issues)
    assert "no sources configured" in msgs and "not a URL" in msgs and "one-word alias" in msgs


def test_osisko_royalties(wl):
    assert labels(wl, "OR Royalties Announces Preliminary Q3 2026 GEO Deliveries") == [
        "OR Royalties (formerly Osisko Gold Royalties)"]
    assert labels(wl, "Osisko Gold Royalties acquires stream on Canadian Copper") == [
        "OR Royalties (formerly Osisko Gold Royalties)"]
    assert labels(wl, "Osisko Development advances Cariboo Gold Project") == []
