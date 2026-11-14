# mining-alerts

Get alerts when the mining companies and projects we follow put out new
announcements. Alerts can go by email, Slack or Telegram.

The tool polls news feeds and filings every 30 minutes and works out which
company or project each item is about. It skips anything it has already sent,
then sends one digest message. Project hits (Ana Paula, Thacker Pass, South
Crofty, ...) are starred and listed first.

## What it watches

The watchlist is in `config/watchlist.yaml`, and you can edit it without touching
any code. Run `python -m mining_alerts watchlist` to see the current list.

| Source | Covers | Config key |
|---|---|---|
| Google News RSS (English and Spanish editions) | Press releases (Newsfile, GlobeNewswire...), trade press, Argentine/Mexican local news | `google_news: true`, `languages: [en, es]` |
| SEC EDGAR | 8-K / 6-K / 40-F filings of US-listed names (Lithium Americas, OR Royalties) | `edgar: "LAC"` |
| ASX announcements | Lithium Energy (ASX:LEL) | `asx: "LEL"` |
| Any RSS/Atom feed | Official company feeds, e.g. Newsfile for Heliostar and Elemental Royalty | `rss: [url]` |
| Newsroom web page | Companies with no feed | `webpages: [{url, link_pattern}]` |

### How it avoids false alerts
Names like "Orion", "Minto" or "Ana Paula" turn up all the time in unrelated news.
For names like these, a match also needs one of the entry's `context` words, such as
`mine`, `royalty`, `Guerrero` or `Yukon`. You can check how a headline would be
handled:

```bash
python -m mining_alerts check "Heliostar drills 10 g/t gold at Ana Paula"
# PROJECT  Heliostar Metals / Ana Paula
python -m mining_alerts check "Orion spacecraft completes test"
# no match
```

### What each alert shows
Each item gets a type tag based on keywords, in English and Spanish: **M&A,
Royalty/Stream, Financing, Resource/Study, Permits, Legal**, Drilling, Production,
Results, Management or Filing. The first six count as high priority. They go first
in the digest, are coloured red in the email, and are named in the email subject:

```
[Mining alerts] 3 new (Financing, M&A): Heliostar Metals / Ana Paula, Elemental Royalty, ...
```

Each item also shows the publisher and date. Usually the same story is carried by
several outlets. Those copies are merged into one alert, with the company's own
release or the press-release wire chosen as the original, plus a line like
`also: Mining.com, Reuters`. A reworded copy of a story already sent in the last
7 days is not sent again.

`python -m mining_alerts check "<headline>"` shows both the match and the type tags.

### Broken-feed warnings
If a source fails 3 runs in a row (a feed address changed, a site blocking us),
you get one "Source health" warning in your alert channel. Run
`python -m mining_alerts health` to see the status of every source. Requests are
retried on temporary errors, and Google News and SEC requests are spaced out to
avoid rate limits.

### No flood on the first run
The first time a source is polled, everything it returns is recorded silently.
After that you only get items that are actually new. Items older than
`max_age_days` (default 10) are never sent.

## Setup

```bash
pip install -e ".[dev]"
cp .env.example .env        # fill in email / Slack / Telegram
python -m mining_alerts test-notify   # check your alert channels
python -m mining_alerts run --dry-run # see what would be alerted, change nothing
python -m mining_alerts run           # the real run
```

Other commands: `sources` (every URL polled), `history` (recent alerts),
`health` (feed status), `-v` (debug logs).

### Run it on a schedule

Pick one:

- **GitHub Actions (recommended, no server needed):** push this folder to a
  private GitHub repo and add the `.env` values as repository secrets
  (Settings → Secrets → Actions). `.github/workflows/alerts.yml` runs every
  30 minutes and keeps its "already seen" database in the Actions cache.
- **cron on any machine:**
  ```
  */30 * * * * cd /path/to/mining-alerts && .venv/bin/python -m mining_alerts run >> data/run.log 2>&1
  ```

### Email via Gmail
Gmail needs an **App Password**, not your normal password. Create one in Google
Account → Security → 2-Step Verification → App passwords, then set
`SMTP_HOST=smtp.gmail.com` and `SMTP_PORT=587`.

## Adding a company or project

```yaml
  - id: new_co
    name: New Co Resources
    aliases: ["New Co Resources"]
    google_news: true
    languages: [en, es]
    rss: ["https://newco.com/news/feed"]   # if they have one
    projects:
      - name: Big Hill
        aliases: ["Big Hill"]
        context: [copper, mine, Chile]      # needed when the name is generic
```

If the automatic Google News search for a company is too broad, set your own with
`news_query: '"Gold.com" (NYSE OR results)'`.

Run `pytest` afterwards. Entries marked `status: needs_confirmation` are guesses
that still need checking.

## Layout

```
config/watchlist.yaml        companies, projects, sources
src/mining_alerts/
  watchlist.py               YAML loading and company/project matching
  sources/                   google_news, rss, edgar, asx, webpage
  notifiers/                 console, email, slack, telegram
  classify.py                type tags (M&A, Financing, Permits, ...)
  dedupe.py                  merge the same story from several outlets
  storage.py                 SQLite store: items already seen, source health
  pipeline.py                fetch -> match -> dedupe -> notify -> remember
  cli.py                     command line
tests/                       offline tests with fixture feeds
```

## Possible next steps
- Add official feeds for the remaining companies. Altius uses Business Wire,
  OR Royalties uses GlobeNewswire and Cornish Metals uses London RNS; none of
  these has a simple per-company feed, so this probably means scraping each
  company's newsroom page with `webpages:`.
- SEDAR+ filings for Canadian issuers (Heliostar, Cornish Metals).
- Use an LLM to summarise each alert in a sentence and score how much it
  matters (financing, resource update, permit, M&A).
- Fill in the rest of Orion's portfolio, so news about its investee projects
  comes through.
