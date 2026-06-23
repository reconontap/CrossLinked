# CrossLinked — Free-Proxy Rotation + Browser-Solve Google Engine

**Date:** 2026-06-24
**Status:** Approved (design), pending implementation plan
**Context:** CrossLinked was already repaired to scrape DuckDuckGo (HTML POST) and Brave instead of the now-dead Google/Bing HTML endpoints. Both working engines IP-throttle aggressively (HTTP 429/202), so a single IP yields only ~1 page per engine before a multi-minute cooldown. This spec adds two independent capabilities to get more results despite anti-bot defenses.

## Goals
- Auto-fetch, validate, and rotate **free public proxies** to spread requests-engine traffic across many IPs.
- Add an optional **browser-driven Google engine** that renders results and, when challenged (reCAPTCHA / `/sorry/`), **pauses for the user to solve in a visible browser**, then continues in the same cookie context.

## Non-Goals
- No paid/captcha-solving services (2captcha, etc.).
- No proxy rotation for the browser engine (a solved challenge cookie is IP+UA-bound; rotating would invalidate it).
- Not re-enabling plain-`requests` Google/Bing (dead); Google works only via the browser engine.

## How the two features divide the work
- **Requests engines (DuckDuckGo, Brave)** → rotating free-proxy pool; drop-on-block, continue.
- **Browser engine (Google)** → single connection, persistent browser profile so a solved challenge sticks.
- Typical use: `--search duckduckgo,brave --free-proxies` for volume; `--search google` for the browser-solve flow.

## Subsystem 1 — Free-proxy pool (`crosslinked/proxy.py`)
**Responsibility:** produce a list of working `ip:port` (and `socks4://`/`socks5://`) proxy strings.

- **Sources** (public, no API key), each fetched independently; a dead source is skipped, not fatal:
  - `https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt`
  - `https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt`
  - ProxyScrape API (`api.proxyscrape.com`, text format, http protocol)
  - (URLs verified live during implementation; swap any that 404.)
- **Parse/dedup** to a set of `ip:port`.
- **Validate** in parallel (`concurrent.futures.ThreadPoolExecutor`) against a lightweight IP-echo endpoint (e.g. `https://api.ipify.org`) with a short per-proxy timeout (~5s). Keep successes up to `--proxy-count` (default 30).
- **Cache** validated pool at `~/.crosslinked/proxies.txt` with a header timestamp; reuse if younger than TTL (~30 min). `--refresh-proxies` forces refetch.
- **Public interface:**
  - `build_pool(limit=30, timeout=5, threads=50, refresh=False) -> list[str]`
  - `fetch_candidates() -> set[str]`, `validate(proxy, timeout) -> bool` (unit-testable).
- **Failure mode:** empty pool after validation → warn, caller falls back to direct.

## Subsystem 2 — `search.py` drop-on-block rotation
**Change `CrossLinked.search()`:** when a proxy pool is active, a non-200/exception **drops that proxy** from the pool and rotates to the next, ending only when the pool is exhausted, the timer expires, or a page yields no new results. Without proxies, current behavior is unchanged (stop on non-200).

- Caller selects the proxy per request (so it knows which to drop): `proxy = choice(self.proxies)`, pass a single proxy to `web_request`, remove it from `self.proxies` on failure.
- `web_request` keeps real browser headers (already added); signature already supports `method`/`data` for the DuckDuckGo POST.

## Subsystem 3 — Browser Google engine (`crosslinked/browser.py`, optional extra)
**Optional dependency:** `crosslinked[browser]` → `playwright`; user also runs `playwright install chromium`.

- Launch Chromium **headed** with a **persistent context** at `~/.crosslinked/profile` (cookies/solves persist across runs), realistic UA.
- Per page: `goto` `https://www.google.com/search?q=site:linkedin.com/in "<company>"&start=<n>`, wait for results, read `page.content()`, extract `<a>` with `linkedin.com/in` href + title text from the result's `<h3>`; paginate by `start += 10`; jitter between pages. Return the same `{name,title,url,text}` dicts.
- **Challenge hand-off (the pause):** detect `/sorry/` URL or reCAPTCHA / "unusual traffic" markers; print `[!] Solve the challenge in the browser window, then press Enter…`; **block on `input()`** while the user solves in the visible window; then re-navigate and continue in the same context.
- Reuse `parse_linkedin_name` / `parse_linkedin_title` from `search.py` (extract shared helpers if needed).
- **Guards:** missing extra/Chromium or no display → clear, actionable error.
- **Known risk (documented):** automated Chromium may be re-challenged even after solving; best-effort, mitigated by persistent profile + realistic UA.

## CLI changes (`crosslinked/__init__.py`)
- `--free-proxies` (flag; combinable with `--proxy`/`--proxy-file`).
- `--proxy-count N` (default 30), `--refresh-proxies`.
- `--search google` routes to the browser engine; `duckduckgo,brave` stays the default and uses requests.
- Build the proxy pool before scraping when `--free-proxies` is set; pass the pool into the requests engines only.

## Error handling
- Source fetch error → skip source. All sources fail → warn, continue direct.
- No valid proxies → warn, fall back to direct.
- Browser extra/Chromium absent or headless host → explicit install/usage message, do not crash the whole run.
- User aborts a challenge (Ctrl-C / 'q') → end the Google engine cleanly, keep collected results.

## Testing
- `proxy.py`: unit tests for source parsing, `validate` (mocked requests), and cache-TTL reuse; one live smoke `build_pool`.
- `search.py`: unit test that a simulated 429 drops a proxy and continues to the next (no real network).
- `browser.py`: first confirm current Google result selectors + challenge flow empirically via the Playwright MCP, then a live `--search google` smoke run.
- Integration: `--search duckduckgo,brave --free-proxies` end-to-end producing names.txt.

## File layout
- New: `crosslinked/proxy.py`, `crosslinked/browser.py`.
- Modified: `crosslinked/search.py`, `crosslinked/__init__.py`, `pyproject.toml` + `setup.py` (add `browser` extra; proxy side needs no new deps).

## Phasing
1. Proxy pool + drop-on-block rotation + CLI wiring + tests (immediately useful).
2. Browser Google engine + optional extra + tests.
