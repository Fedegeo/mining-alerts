from pathlib import Path

from mining_alerts.sources import build_sources
from mining_alerts.sources.asx import parse_asx
from mining_alerts.sources.edgar import EdgarSource
from mining_alerts.sources.google_news import build_queries, google_news_url
from mining_alerts.sources.rss import parse_feed
from mining_alerts.sources.webpage import parse_links
from mining_alerts.watchlist import Watchlist

FIX = Path(__file__).parent / "fixtures"
WL = Watchlist.load(Path(__file__).resolve().parents[1] / "config" / "watchlist.yaml")


class FakeResp:
    def __init__(self, content): self.content = content
    def raise_for_status(self): pass


class FakeSession:
    def __init__(self, content): self.content = content
    def get(self, *a, **k): return FakeResp(self.content)


def test_parse_rss():
    items = parse_feed((FIX / "google_news.xml").read_bytes(), "gn")
    assert len(items) == 6
    assert items[0].summary.startswith("Heliostar reports")  # HTML stripped
    assert items[0].published.year == 2026
    # publisher pulled from <source>, " - Newsfile" suffix removed from the title
    assert items[0].publisher == "Newsfile"
    assert items[0].title.endswith("at Ana Paula")


def test_edgar_filters_ownership_forms():
    src = EdgarSource("LAC", "lithium_americas")
    items = src.fetch(FakeSession((FIX / "edgar.xml").read_bytes()))
    assert [i.title for i in items] == ["[SEC 8-K] Current report"]
    assert items[0].company_hint == "lithium_americas"
    assert items[0].publisher == "SEC EDGAR"


def test_asx_parse():
    payload = {"data": {"items": [
        {"headline": "Solaroz Lithium Project Update", "date": "2026-11-12T09:30:00+11:00",
         "documentKey": "2924-123", "isPriceSensitive": True, "announcementTypes": ["Progress Report"]}]}}
    [it] = parse_asx(payload, "LEL", "lithium_energy")
    assert it.title == "[ASX:LEL] Solaroz Lithium Project Update [price-sensitive]"
    assert it.url.endswith("announcements.lel#2924-123")


def test_webpage_links():
    html = """<a href="/news/2026/ana-paula-update">Heliostar announces Ana Paula update</a>
              <a href="/about">About us and our very long history</a>
              <a href="/news/x">short</a>"""
    items = parse_links(html, "https://heliostarmetals.com/news", r"/news/\d{4}/", "web", "heliostar")
    assert [i.url for i in items] == ["https://heliostarmetals.com/news/2026/ana-paula-update"]


def test_google_queries_avoid_bare_ambiguous_alias():
    orion = WL.get("orion")
    company_q = build_queries(orion)[0][1]
    assert '"Orion Resource Partners"' in company_q and '"Orion" ' not in company_q + " "
    url = google_news_url('"Ana Paula"', "es")
    assert "ceid=AR:es-419" in url and "when%3A14d" in url


def test_build_sources_dedupes_shared_urls():
    sources = build_sources(WL)
    urls = [getattr(s, "url", s.name) for s in sources]
    assert len(urls) == len(set(urls))
    assert any(s.name == "edgar:0001966983" for s in sources)   # Lithium Americas by CIK
    assert any(s.name.startswith("web:https://www.investegate.co.uk") for s in sources)
    assert any(s.name == "asx:LEL" for s in sources)


def test_custom_news_query():
    assert build_queries(WL.get("gold_com"))[0][1].startswith('"Gold.com" (NYSE')


def test_newsfile_feed_publisher():
    from mining_alerts.sources.rss import RSSSource
    src = RSSSource("https://feeds.newsfilecorp.com/company/7729", company_hint="heliostar")
    xml = b"""<rss><channel><title>Heliostar Metals Ltd. News Releases</title>
    <item><title>Heliostar Announces Ana Paula Permit</title><link>https://newsfile/x</link></item>
    </channel></rss>"""
    [it] = src.fetch(FakeSession(xml))
    assert it.publisher == "Newsfile" and it.company_hint == "heliostar"


def test_session_has_retries():
    from mining_alerts.sources import make_session
    adapter = make_session().get_adapter("https://news.google.com")
    assert adapter.max_retries.total == 3 and 429 in adapter.max_retries.status_forcelist


def test_investegate_rns_page():
    html = """
    <a href="/announcement/rns/cornish-metals-plc--tin/loi-from-export-import-bank-of-the-united-states/9410109">
       LOI FROM EXPORT-IMPORT BANK OF THE UNITED STATES</a>
    <a href="/announcement/rns/cornish-metals-plc--tin/roskear-exploration-drilling-update/9600001">
       ROSKEAR EXPLORATION DRILLING UPDATE</a>
    <a href="/company/TIN?page=2">Next page of announcements for this company</a>"""
    items = parse_links(html, "https://www.investegate.co.uk/company/TIN",
                        "/announcement/[a-z]+/cornish-metals", "web", "cornish_metals")
    assert items[0].title.startswith("LOI from export-import bank")
    assert items[1].title == "Roskear exploration drilling update"
    assert all(i.publisher == "RNS" for i in items) and len(items) == 2


def test_cornish_metals_rns_item_is_project_hit():
    from mining_alerts.models import Announcement
    it = Announcement(title="Roskear exploration drilling update", url="u", source="web",
                      company_hint="cornish_metals")
    assert [m.label for m in WL.match(it)] == ["Cornish Metals / South Crofty"]
