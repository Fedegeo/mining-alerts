from datetime import datetime, timezone
from pathlib import Path

from mining_alerts import pipeline
from mining_alerts.notifiers.email import EmailNotifier
from mining_alerts.notifiers.slack import SlackNotifier
from mining_alerts.notifiers.telegram import TelegramNotifier
from mining_alerts.notifiers import configured_notifiers
from mining_alerts.sources.rss import parse_feed
from mining_alerts.storage import Store
from mining_alerts.watchlist import Watchlist

FIX = Path(__file__).parent / "fixtures"
WL = Watchlist.load(Path(__file__).resolve().parents[1] / "config" / "watchlist.yaml")
NOW = datetime(2026, 11, 13, tzinfo=timezone.utc)


class FixtureSource:
    def __init__(self, name="gn", path="google_news.xml"):
        self.name, self.path = name, path
    def fetch(self, session):
        return parse_feed((FIX / self.path).read_bytes(), self.name)


class Broken:
    name = "broken"
    def fetch(self, session):
        raise ConnectionError("boom")


class Recorder:
    def __init__(self, name="slack", fail=False):
        self.name, self.fail, self.calls = name, fail, []
    def send(self, items):
        if self.fail:
            raise RuntimeError("down")
        self.calls.append(items)


def run(store, notifiers, sources=None, **kw):
    return pipeline.run(WL, sources or [FixtureSource()], store, notifiers, None, now=NOW, **kw)


def test_first_run_is_silent_baseline(tmp_path):
    store, rec = Store(tmp_path / "db.sqlite"), Recorder()
    res = run(store, [rec])
    assert res.baselined_sources == ["gn"] and res.new == [] and rec.calls == []
    # second run: nothing new
    assert run(store, [rec]).new == []


def test_alerts_relevant_new_recent_items_only(tmp_path):
    store, rec = Store(tmp_path / "db.sqlite"), Recorder()
    res = run(store, [rec], baseline=False)
    titles = [i.title for i in res.new]
    # project hits first; singer/NASA filtered out; June item too old
    assert len(titles) == 2
    assert titles[0].startswith("Heliostar Drills")
    assert titles[1].startswith("Lithium Americas")
    assert len(rec.calls) == 1
    assert run(store, [rec], baseline=False).new == []  # deduped on rerun


def test_failed_channel_retries_next_run(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    res = run(store, [Recorder(fail=True)], baseline=False)
    assert "notify:slack" in res.errors
    ok = Recorder()
    assert len(run(store, [ok], baseline=False).new) == 2  # retried


def test_broken_source_does_not_stop_run(tmp_path):
    store, rec = Store(tmp_path / "db.sqlite"), Recorder()
    res = run(store, [rec], sources=[Broken(), FixtureSource()], baseline=False)
    assert "broken" in res.errors and len(res.new) == 2


def test_dry_run_changes_nothing(tmp_path):
    store, rec = Store(tmp_path / "db.sqlite"), Recorder()
    assert len(run(store, [rec], baseline=False, dry_run=True).new) == 2
    assert rec.calls == [] and not store.source_known("gn")


def test_title_dedupe_across_sources(tmp_path):
    store, rec = Store(tmp_path / "db.sqlite"), Recorder()
    res = run(store, [rec], sources=[FixtureSource("a"), FixtureSource("b")], baseline=False)
    assert len(res.new) == 2


def test_notifier_formatting(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    items = run(store, [], baseline=False, dry_run=True).new
    msg = EmailNotifier("h", 587, "u", "p", "from@x", ["to@x"]).build_message(items)
    assert msg["Subject"].startswith("[Mining alerts] 2 new: Heliostar Metals / Ana Paula")
    html = msg.get_body(("html",)).get_content()
    assert "&#9733; PROJECT" in html and "news.google.com" in html
    assert ":star: *Heliostar Metals / Ana Paula*" in SlackNotifier("x").build_text(items)
    assert TelegramNotifier("t", "c").build_messages(items)[0].startswith("<b>2 new")


def test_configured_notifiers_from_env():
    names = [n.name for n in configured_notifiers({"SMTP_HOST": "h", "ALERT_EMAIL_TO": "a@b",
                                                   "SLACK_WEBHOOK_URL": "https://x"})]
    assert names == ["console", "email", "slack"]
