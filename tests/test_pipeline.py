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
    def send(self, items, warnings=(), digest=False):
        if self.fail:
            raise RuntimeError("down")
        self.calls.append((items, list(warnings)))
        self.digests = getattr(self, "digests", []) + [digest]


def run(store, notifiers, sources=None, **kw):
    kw.setdefault("now", NOW)
    return pipeline.run(WL, sources or [FixtureSource()], store, notifiers, None,
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


# ---------------------------------------------------------------- delivery modes
from datetime import timedelta

from mining_alerts.models import Announcement, Match
from mining_alerts.pipeline import Delivery


class Items:
    """Source returning fixed items: one project/drilling (urgent in smart mode only if
    project) and one routine company item."""
    name = "items"

    def __init__(self, items):
        self.items = items

    def fetch(self, session):
        return list(self.items)


ROUTINE = ["Altius Minerals to present at investor conference in Toronto",
           "Altius Minerals files annual information form",
           "Altius Minerals renews normal course issuer bid"]


def _routine(n=1):
    return Announcement(title=ROUTINE[n - 1],
                        url=f"https://x/altius{n}", source="items", publisher="Wire",
                        published=NOW - timedelta(hours=1))


def _urgent():
    return Announcement(title="Elemental Royalty to acquire royalty portfolio", url="https://x/ele",
                        source="items", publisher="Wire", published=NOW - timedelta(hours=1))


def test_smart_mode_sends_urgent_now_and_queues_routine(tmp_path):
    store, rec = Store(tmp_path / "db.sqlite"), Recorder()
    smart = Delivery(mode="smart", digest_hour=7, tz="UTC")
    early = NOW.replace(hour=3)
    res = run(store, [rec], sources=[Items([_urgent(), _routine()])], baseline=False,
              delivery=smart, now=early)
    assert [i.title for i in res.new] == ["Elemental Royalty to acquire royalty portfolio"]
    assert [i.title for i in res.queued] == [_routine().title]
    assert len(rec.calls) == 1 and rec.digests == [False]

    # Later the same day, after the digest hour: the queued item goes out once.
    res = run(store, [rec], sources=[Items([_routine(2)])], baseline=False,
              delivery=smart, now=NOW.replace(hour=8))
    assert res.digest_sent == 2 and rec.digests[-1] is True
    assert {i.url for i in rec.calls[-1][0]} == {"https://x/altius1", "https://x/altius2"}
    assert store.queued() == []

    # Same day again: digest already sent, new routine item waits for tomorrow.
    res = run(store, [rec], sources=[Items([_routine(3)])], baseline=False,
              delivery=smart, now=NOW.replace(hour=9))
    assert res.digest_sent == 0 and len(store.queued()) == 1 and len(rec.calls) == 2


def test_daily_mode_queues_everything_and_digest_survives_failure(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    daily = Delivery(mode="daily", digest_hour=7)
    res = run(store, [Recorder(fail=True)], sources=[Items([_urgent()])], baseline=False,
              delivery=daily, now=NOW.replace(hour=8))
    assert res.new == [] and "notify:slack" in res.errors
    assert len(store.queued()) == 1                 # kept for retry
    ok = Recorder()
    res = run(store, [ok], sources=[Items([])], baseline=False, delivery=daily, now=NOW.replace(hour=8, minute=30))
    assert res.digest_sent == 1 and store.queued() == []


def test_force_digest_and_queue_roundtrip(tmp_path):
    store, rec = Store(tmp_path / "db.sqlite"), Recorder()
    item = _routine()
    item.matches = [Match("altius", "Altius Minerals")]
    item.categories = ["Results"]
    item.also_reported_by = ["Reuters"]
    store.enqueue([item])
    back = store.queued()[0]
    assert back == item and back.published == item.published
    res = run(store, [rec], sources=[Items([])], baseline=False,
              delivery=Delivery(mode="daily", digest_hour=23), now=NOW.replace(hour=1), force_digest=True)
    assert res.digest_sent == 1


def test_delivery_env_and_timezone():
    d = Delivery.from_env({"ALERT_MODE": "Smart", "DIGEST_HOUR": "8",
                           "DIGEST_TZ": "America/Argentina/Buenos_Aires"})
    # 10:30 UTC = 07:30 in Buenos Aires -> not yet 8am there
    assert not d.digest_due(NOW.replace(hour=10, minute=30), None)
    assert d.digest_due(NOW.replace(hour=11, minute=30), None)
    assert not d.digest_due(NOW.replace(hour=11, minute=30), "2026-11-13")
    import pytest
    with pytest.raises(ValueError):
        Delivery(mode="hourly")


def test_email_subject_for_digest(tmp_path):
    item = _routine()
    item.matches = [Match("altius", "Altius Minerals")]
    msg = EmailNotifier("h", 587, "u", "p", "f@x", ["t@x"]).build_message([item], digest=True)
    assert msg["Subject"].startswith("[Mining digest] 1 new")


def test_uk_default_handles_bst():
    d = Delivery.from_env({"ALERT_MODE": "smart"})
    assert d.tz == "Europe/London" and d.digest_hour == 7
    summer, winter = datetime(2026, 7, 1, tzinfo=timezone.utc), datetime(2026, 12, 1, tzinfo=timezone.utc)
    # BST (UTC+1): 06:30 UTC is already 07:30 in London
    assert d.digest_due(summer.replace(hour=6, minute=30), None)
    # GMT (UTC+0): 06:30 UTC is still 06:30 in London
    assert not d.digest_due(winter.replace(hour=6, minute=30), None)
    assert d.digest_due(winter.replace(hour=7, minute=5), None)
