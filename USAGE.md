# CrossLinked — Usage (2026 refresh)

LinkedIn employee-name enumeration via search-engine scraping. This refresh replaces the
now-dead Google/Bing HTML scraping (Google → 429/CAPTCHA, Bing → empty bot-shells) with
working engines, adds free-proxy rotation, and adds an optional browser engine that lets
**you** solve Google's CAPTCHA so scraping can continue.

## Install
```bash
git clone <this repo> && cd crosslinked
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # core (DuckDuckGo + Brave + proxies)
pip install -e '.[browser]'              # optional: the --search google browser engine
playwright install chromium              # optional: only needed for the browser engine
```

## Engines
| Engine | How | Notes |
|--------|-----|-------|
| `duckduckgo` | HTML POST endpoint | default; rate-limits after a few requests |
| `brave` | GET, paginated | default; ~45 results/page, also rate-limits |
| `google` | **browser** (Playwright) | pauses for you to solve the CAPTCHA, then continues |
| `bing` | legacy requests | mostly dead (empty bot-shell); kept selectable |

Default is `duckduckgo,brave`.

## Common usage

**Basic (default engines):**
```bash
python3 crosslinked.py -f '{first}.{last}@domain.com' "Target Company"
```

**Requests engines + free-proxy rotation** (more results before rate-limits bite):
```bash
python3 crosslinked.py --search duckduckgo,brave --free-proxies \
    -f '{first}.{last}@acme.com' -t 25 -j 3 "Acme Corp"
```

**Browser engine** (Chromium opens; solve the CAPTCHA when prompted, then press Enter):
```bash
pip install -e '.[browser]' && playwright install chromium
python3 crosslinked.py --search google -f '{first}.{last}@acme.com' "Acme Corp"
```

**Parse a previous `names.csv` into a new format** (no scraping):
```bash
python3 crosslinked.py -f '{f}{last}@acme.com' names.csv
```

## New / changed flags
| Flag | Meaning |
|------|---------|
| `--search ENGINES` | comma list; default `duckduckgo,brave` (also `google`, `bing`) |
| `--free-proxies` | auto-fetch + validate + rotate free proxies (combinable with `--proxy`/`--proxy-file`) |
| `--proxy-count N` | max validated free proxies to keep (default 30) |
| `--refresh-proxies` | ignore the cached pool and refetch |
| `--headless` | run the `google` browser engine headless (cannot solve CAPTCHAs) |

Proxy pool is cached at `~/.crosslinked/proxies.txt` (30-min TTL). The browser profile lives at
`~/.crosslinked/profile` (a solved challenge's cookies persist across runs).

## Output
- `names.txt` — unique accounts in your `-f` format
- `names.csv` — raw rows: datetime, engine, name, title, URL, raw text

## Notes / limits
- DuckDuckGo and Brave **IP-throttle aggressively** — expect ~1 page/engine per IP before a
  multi-minute cooldown. Use `--free-proxies` (or `--proxy-file`) for volume.
- The `google` browser engine is **best-effort**: automated Chromium may be re-challenged even
  after solving. Headless cannot solve challenges. Requires a display for the solve step.
