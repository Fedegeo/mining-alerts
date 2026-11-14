"""Command line entry point:  python -m mining_alerts <command>"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from . import pipeline
from .classify import categorize
from .models import Announcement
from .notifiers import configured_notifiers
from .sources import build_sources, make_session
from .storage import Store
from .watchlist import Watchlist

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WATCHLIST = Path(os.environ.get("WATCHLIST", ROOT / "config" / "watchlist.yaml"))
DEFAULT_DB = Path(os.environ.get("ALERTS_DB", ROOT / "data" / "alerts.sqlite"))


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (KEY=VALUE lines); real env vars take precedence."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def cmd_run(args) -> int:
    wl = Watchlist.load(args.watchlist)
    store = Store(args.db)
    notifiers = configured_notifiers()
    delivery = pipeline.Delivery.from_env(dict(os.environ))
    res = pipeline.run(wl, build_sources(wl), store, notifiers, make_session(),
                       dry_run=args.dry_run, baseline=not args.no_baseline,
                       delivery=delivery, force_digest=args.send_digest)
    if args.dry_run and res.new:
        from .notifiers.base import plain_digest
        print(plain_digest(res.new))
    print(f"fetched={res.fetched} relevant={res.relevant} new_alerts={len(res.new)} "
          f"duplicates_merged={res.collapsed} queued_for_digest={len(res.queued)} "
          f"digest_sent={res.digest_sent} mode={delivery.mode} "
          f"baselined_sources={len(res.baselined_sources)} errors={len(res.errors)}",
          file=sys.stderr)
    for name, err in res.errors.items():
        print(f"  ! {name}: {err[:200]}", file=sys.stderr)
    store.close()
    # Non-zero only when everything failed, so a single flaky feed doesn't page anyone.
    return 1 if res.errors and res.fetched == 0 else 0


def cmd_sources(args) -> int:
    wl = Watchlist.load(args.watchlist)
    for s in build_sources(wl):
        print(f"{s.name}\n    {getattr(s, 'url', '')}")
    return 0


def cmd_watchlist(args) -> int:
    wl = Watchlist.load(args.watchlist)
    for c in wl.companies:
        flag = "  (needs confirmation)" if c.status != "confirmed" else ""
        print(f"- {c.name} [{c.id}]{flag}")
        for p in c.projects:
            pflag = "  (needs confirmation)" if p.status != "confirmed" else ""
            print(f"    * {p.name}{pflag}")
    return 0


def cmd_check(args) -> int:
    """Test the matcher on a headline, e.g. check "Heliostar drills 10 g/t at Ana Paula"."""
    wl = Watchlist.load(args.watchlist)
    item = Announcement(title=args.text, url="about:blank", source="cli")
    matches = wl.match(item)
    if not matches:
        print("no match")
    for m in matches:
        print(("PROJECT  " if m.project else "COMPANY  ") + m.label)
    cats = categorize(item)
    print("TYPE     " + (", ".join(cats) if cats else "(uncategorized)"))
    return 0


def cmd_history(args) -> int:
    store = Store(args.db)
    for first_seen, labels, title, url in store.recent_alerts(args.limit):
        print(f"{first_seen[:16]}  [{labels}]  {title}\n    {url}")
    return 0


def cmd_validate(args) -> int:
    """Check the watchlist for likely problems."""
    wl = Watchlist.load(args.watchlist)
    issues = wl.lint()
    for level, msg in issues:
        print(f"{level:8} {msg}")
    errors = sum(1 for lvl, _ in issues if lvl == "ERROR")
    print(f"\n{len(wl.companies)} companies, "
          f"{sum(len(c.projects) for c in wl.companies)} projects, "
          f"{len(build_sources(wl))} sources; {errors} error(s)")
    try:
        pipeline.Delivery.from_env(dict(os.environ))
    except Exception as exc:
        print(f"ERROR    delivery settings: {exc}")
        return 1
    return 1 if errors else 0


def cmd_health(args) -> int:
    """Show each source's last success/failure, worst first."""
    store = Store(args.db)
    rows = store.source_health()
    if not rows:
        print("no runs recorded yet")
    for name, fails, last_ok, last_fail, err in rows:
        status = "OK  " if fails == 0 else f"FAIL x{fails}"
        print(f"{status:9} {name}\n          last ok: {(last_ok or 'never')[:16]}"
              + (f"  last error: {(err or '')[:120]}" if fails else ""))
    store.close()
    return 0


def cmd_test_notify(args) -> int:
    from .models import Match
    demo = Announcement(title="TEST - mining-alerts is configured correctly",
                        url="https://example.com/test", source="test", publisher="mining-alerts",
                        matches=[Match("test", "Test Company", "Test Project")],
                        categories=["Financing"], also_reported_by=["Example Wire"])
    for n in configured_notifiers():
        n.send([demo])
        print(f"sent via {n.name}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    _load_dotenv(ROOT / ".env")
    p = argparse.ArgumentParser(prog="mining_alerts", description=__doc__)
    p.add_argument("--watchlist", type=Path, default=DEFAULT_WATCHLIST)
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="fetch all sources and send alerts for new items")
    r.add_argument("--dry-run", action="store_true", help="print what would be alerted; change nothing")
    r.add_argument("--no-baseline", action="store_true",
                   help="alert on everything on a source's first run (default: first run is silent)")
    r.add_argument("--send-digest", action="store_true",
                   help="send the queued daily digest now (smart/daily modes)")
    r.set_defaults(func=cmd_run)

    sub.add_parser("sources", help="list every feed/URL that will be polled").set_defaults(func=cmd_sources)
    sub.add_parser("watchlist", help="show companies/projects followed").set_defaults(func=cmd_watchlist)
    c = sub.add_parser("check", help="test the matcher against a headline")
    c.add_argument("text")
    c.set_defaults(func=cmd_check)
    h = sub.add_parser("history", help="show recently alerted items")
    h.add_argument("--limit", type=int, default=30)
    h.set_defaults(func=cmd_history)
    sub.add_parser("validate", help="check the watchlist for problems").set_defaults(func=cmd_validate)
    sub.add_parser("health", help="show which sources are working / failing").set_defaults(func=cmd_health)
    sub.add_parser("test-notify", help="send a test alert to all channels").set_defaults(func=cmd_test_notify)

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    return args.func(args)
