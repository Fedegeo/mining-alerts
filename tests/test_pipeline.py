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
    def send(self, items, warnings=()):
        if self.fail:
            raise RuntimeError("down")
        self.calls.append((items, list(warnings)))


def run(store, notifiers, sources=None, **kw):
    return pipeline.run(WL, sources or [FixtureSource()], store, notifiers, None, now=NOW,
                        host_delay={}, **kw)


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
    assert msg["Subject"] == "[Mining alerts] 2 new: Heliostar Metals / Ana Paula, Lithium Americas / Thacker Pass, Orion Resource Partners (Orion Mine Finance) / Thacker Pass"
    html = msg.get_body(("html",)).get_content()
    assert "&#9733; PROJECT" in html and "news.google.com" in html
    assert "Drilling</span>" in html and "Newsfile, 2026-11-11 · also: Mining.com" in html
    slack = SlackNotifier("x").build_text(items)
    assert ":star: *Heliostar Metals / Ana Paula*" in slack and "`Drilling`" in slack
    assert TelegramNotifier("t", "c").build_messages(items)[0].startswith("<b>2 new announcement(s) (")


def test_configured_notifiers_from_env():
    names = [n.name for n in configured_notifiers({"SMTP_HOST": "h", "ALERT_EMAIL_TO": "a@b",
                                                   "SLACK_WEBHOOK_URL": "https://x"})]
    assert names == ["console", "email", "slack"]


def test_syndicated_copies_collapse_to_wire_original(tmp_path):
    store, rec = Store(tmp_path / "db.sqlite"), Recorder()
    res = run(store, [rec], baseline=False)
    helio = res.new[0]
    assert helio.publisher == "Newsfile" and helio.also_reported_by == ["Mining.com"]
    assert res.collapsed == 1


def test_same_story_new_headline_next_day_not_resent(tmp_path):
    store, rec = Store(tmp_path / "db.sqlite"), Recorder()
    run(store, [rec], baseline=False)

    class Rewrite:
        name = "late"
        def fetch(self, session):
            from mining_alerts.models import Announcement
            return [Announcement(title="Heliostar drills 69 metres of 10.1 g/t gold at Ana Paula High Grade Panel",
                                 url="https://other.example/x", source="late", publisher="Other")]
    res = run(store, [rec], sources=[Rewrite()], baseline=False)
    assert res.new == []


def test_failing_source_warns_once_at_threshold(tmp_path):
    store, rec = Store(tmp_path / "db.sqlite"), Recorder()
    warned = []
    for _ in range(pipeline.FAILURE_ALERT_THRESHOLD + 2):
        warned.append(run(store, [rec], sources=[Broken()], baseline=False).warnings)
    assert [len(w) for w in warned] == [0, 0, 1, 0, 0]
    assert rec.calls == [([], warned[2])]          # warning delivered on its own
    assert store.source_health()[0][1] == 5
    run(store, [rec], sources=[FixtureSource("broken")], baseline=False)   # recovers
    assert dict((r[0], r[1]) for r in store.source_health())["broken"] == 0


def test_categories_tagged(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    items = run(store, [], baseline=False, dry_run=True).new
    assert items[0].categories[0] == "Drilling"
