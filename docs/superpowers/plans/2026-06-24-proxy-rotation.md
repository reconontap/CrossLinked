# Free-Proxy Rotation Implementation Plan (Phase 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-fetch, validate, cache, and rotate free public proxies through CrossLinked's DuckDuckGo/Brave engines, dropping blocked proxies mid-run so a single run can gather far more results.

**Architecture:** A new `crosslinked/proxy.py` builds a validated proxy pool (parallel connectivity check, cached to `~/.crosslinked/proxies.txt` with a TTL). `crosslinked/search.py` selects one proxy per request and removes it from the pool on any non-200/timeout, continuing until the pool is exhausted, the timer expires, or a page yields no new results. `crosslinked/__init__.py` adds `--free-proxies` / `--proxy-count` / `--refresh-proxies` flags and merges the pool into the existing proxy list.

**Tech Stack:** Python 3, `requests`, `concurrent.futures` (stdlib), `pytest` (dev).

## Global Constraints
- Python `^3.8` compatible (per `pyproject.toml`).
- No new runtime dependencies (Phase 1 uses only `requests` + stdlib).
- Never use `pip install --break-system-packages`; use the project venv at `crosslinked/.venv`.
- All work happens inside the cloned repo `/home/pentester/claude/claude_osint_tools_fix/crosslinked`.
- Tests run from the repo root with the venv active: `source .venv/bin/activate`.

---

## File Structure
- **Create** `crosslinked/proxy.py` — free-proxy fetch/validate/cache/pool. Sole responsibility: produce a list of working proxy strings.
- **Modify** `crosslinked/search.py` — per-request proxy selection + drop-on-block rotation; fix a Timer startup race so the loop is deterministic.
- **Modify** `crosslinked/__init__.py` — CLI flags and pool wiring.
- **Create** `tests/test_proxy.py`, `tests/test_search_rotation.py`, `tests/test_cli.py`.

Pre-req (one-time): `source .venv/bin/activate && pip install pytest`.

---

### Task 1: Proxy candidate fetching & format validation

**Files:**
- Create: `crosslinked/proxy.py`
- Test: `tests/test_proxy.py`

**Interfaces:**
- Produces: `fetch_candidates(sources=PROXY_SOURCES, timeout=15) -> set[str]`; `_valid_format(p: str) -> bool`; `_scheme(p: str) -> str`; module constants `PROXY_SOURCES`, `IP_ECHO`, `CACHE_DIR`, `CACHE_FILE`, `CACHE_TTL`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_proxy.py
import crosslinked.proxy as P


def test_valid_format():
    assert P._valid_format('1.1.1.1:80')
    assert P._valid_format('socks5://2.2.2.2:1080')
    assert not P._valid_format('bad line')
    assert not P._valid_format('1.1.1.1')
    assert not P._valid_format('')


def test_fetch_candidates_parses_and_dedups(monkeypatch):
    class Resp:
        status_code = 200
        text = "1.1.1.1:80\n2.2.2.2:8080\nbad line\n1.1.1.1:80\n"
    monkeypatch.setattr(P.requests, 'get', lambda url, timeout=15: Resp())
    res = P.fetch_candidates(sources=['http://example'])
    assert res == {'1.1.1.1:80', '2.2.2.2:8080'}


def test_fetch_candidates_skips_dead_source(monkeypatch):
    def boom(url, timeout=15):
        raise Exception('source down')
    monkeypatch.setattr(P.requests, 'get', boom)
    assert P.fetch_candidates(sources=['http://dead']) == set()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_proxy.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'crosslinked.proxy'`

- [ ] **Step 3: Write minimal implementation**

```python
# crosslinked/proxy.py
import os
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from crosslinked.logger import Log

PROXY_SOURCES = [
    'https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt',
    'https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt',
    'https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&proxy_format=ipport&format=text&protocol=http',
]
IP_ECHO = 'https://api.ipify.org'
CACHE_DIR = os.path.expanduser('~/.crosslinked')
CACHE_FILE = os.path.join(CACHE_DIR, 'proxies.txt')
CACHE_TTL = 1800  # seconds (30 min)


def _valid_format(p):
    if not p or ' ' in p:
        return False
    host_port = p.split('://')[-1]
    host, sep, port = host_port.rpartition(':')
    return bool(host) and bool(sep) and port.isdigit()


def _scheme(proxy):
    return proxy if '://' in proxy else 'http://' + proxy


def fetch_candidates(sources=PROXY_SOURCES, timeout=15):
    proxies = set()
    for url in sources:
        try:
            r = requests.get(url, timeout=timeout)
            if r.status_code == 200:
                for line in r.text.splitlines():
                    line = line.strip()
                    if _valid_format(line):
                        proxies.add(line)
        except Exception as e:
            Log.warn('Proxy source failed: {} ({})'.format(url, e))
    return proxies
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_proxy.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add crosslinked/proxy.py tests/test_proxy.py
git commit -m "feat(proxy): fetch & format-validate free proxy candidates"
```

---

### Task 2: Per-proxy connectivity validation

**Files:**
- Modify: `crosslinked/proxy.py`
- Test: `tests/test_proxy.py`

**Interfaces:**
- Consumes: `_scheme`, `IP_ECHO`.
- Produces: `validate(proxy: str, timeout=5, test_url=IP_ECHO) -> bool`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_proxy.py
def test_validate_true_on_200(monkeypatch):
    class Resp:
        status_code = 200
    monkeypatch.setattr(P.requests, 'get', lambda url, proxies=None, timeout=5: Resp())
    assert P.validate('1.1.1.1:80') is True


def test_validate_false_on_exception(monkeypatch):
    def boom(url, proxies=None, timeout=5):
        raise Exception('no route to host')
    monkeypatch.setattr(P.requests, 'get', boom)
    assert P.validate('1.1.1.1:80') is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_proxy.py -k validate -v`
Expected: FAIL with `AttributeError: module 'crosslinked.proxy' has no attribute 'validate'`

- [ ] **Step 3: Write minimal implementation**

```python
# add to crosslinked/proxy.py
def validate(proxy, timeout=5, test_url=IP_ECHO):
    scheme = _scheme(proxy)
    try:
        r = requests.get(test_url, proxies={'http': scheme, 'https': scheme}, timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_proxy.py -k validate -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add crosslinked/proxy.py tests/test_proxy.py
git commit -m "feat(proxy): add connectivity validation"
```

---

### Task 3: Pool builder with parallel validation & TTL cache

**Files:**
- Modify: `crosslinked/proxy.py`
- Test: `tests/test_proxy.py`

**Interfaces:**
- Consumes: `fetch_candidates`, `validate`, `CACHE_FILE`, `CACHE_DIR`, `CACHE_TTL`.
- Produces: `build_pool(limit=30, timeout=5, threads=50, refresh=False) -> list[str]`; `_load_cache() -> list[str] | None`; `_save_cache(proxies: list[str]) -> None`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_proxy.py
def test_build_pool_keeps_only_validated(monkeypatch, tmp_path):
    monkeypatch.setattr(P, 'CACHE_DIR', str(tmp_path))
    monkeypatch.setattr(P, 'CACHE_FILE', str(tmp_path / 'p.txt'))
    monkeypatch.setattr(P, 'fetch_candidates', lambda: {'1.1.1.1:80', '2.2.2.2:80', '3.3.3.3:80'})
    good = {'1.1.1.1:80', '3.3.3.3:80'}
    monkeypatch.setattr(P, 'validate', lambda p, timeout=5, test_url=P.IP_ECHO: p in good)
    pool = P.build_pool(limit=10, refresh=True)
    assert set(pool) == good


def test_build_pool_reuses_fresh_cache(monkeypatch, tmp_path):
    cache = tmp_path / 'p.txt'
    cache.write_text('# crosslinked validated proxies\n9.9.9.9:80\n')
    monkeypatch.setattr(P, 'CACHE_DIR', str(tmp_path))
    monkeypatch.setattr(P, 'CACHE_FILE', str(cache))
    monkeypatch.setattr(P, 'CACHE_TTL', 9999)
    fetched = {'flag': False}
    def boom():
        fetched['flag'] = True
        return set()
    monkeypatch.setattr(P, 'fetch_candidates', boom)
    pool = P.build_pool(limit=10, refresh=False)
    assert pool == ['9.9.9.9:80']
    assert fetched['flag'] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_proxy.py -k build_pool -v`
Expected: FAIL with `AttributeError: module 'crosslinked.proxy' has no attribute 'build_pool'`

- [ ] **Step 3: Write minimal implementation**

```python
# add to crosslinked/proxy.py
def _load_cache():
    try:
        if not os.path.exists(CACHE_FILE):
            return None
        if (time.time() - os.path.getmtime(CACHE_FILE)) > CACHE_TTL:
            return None
        with open(CACHE_FILE) as f:
            lines = [l.strip() for l in f if l.strip() and not l.startswith('#')]
        return lines or None
    except Exception:
        return None


def _save_cache(proxies):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(CACHE_FILE, 'w') as f:
            f.write('# crosslinked validated proxies\n')
            for p in proxies:
                f.write(p + '\n')
    except Exception as e:
        Log.warn('Could not cache proxies: {}'.format(e))


def build_pool(limit=30, timeout=5, threads=50, refresh=False):
    if not refresh:
        cached = _load_cache()
        if cached is not None:
            Log.info('Loaded {} cached proxies'.format(len(cached)))
            return cached[:limit]

    candidates = fetch_candidates()
    Log.info('Validating {} candidate proxies (this can take a moment)...'.format(len(candidates)))
    working = []
    with ThreadPoolExecutor(max_workers=threads) as ex:
        futures = {ex.submit(validate, p, timeout): p for p in candidates}
        for fut in as_completed(futures):
            try:
                if fut.result():
                    working.append(futures[fut])
                    if len(working) >= limit:
                        break
            except Exception:
                pass
        for f in futures:
            f.cancel()
    Log.success('{} working proxies ready'.format(len(working)))
    _save_cache(working)
    return working
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_proxy.py -v`
Expected: PASS (all proxy tests)

- [ ] **Step 5: Live smoke check (manual, non-gating)**

Run: `source .venv/bin/activate && python -c "from crosslinked.proxy import build_pool; print(len(build_pool(limit=5, refresh=True)), 'proxies')"`
Expected: prints a small non-negative count (free proxies are flaky; 0 is possible but usually >0).

- [ ] **Step 6: Commit**

```bash
git add crosslinked/proxy.py tests/test_proxy.py
git commit -m "feat(proxy): parallel pool builder with TTL cache"
```

---

### Task 4: Drop-on-block proxy rotation in `search.py`

**Files:**
- Modify: `crosslinked/search.py` (the `Timer.__init__`, `CrossLinked.search`, `CrossLinked.get_page`; add `CrossLinked.drop_proxy`)
- Test: `tests/test_search_rotation.py`

**Interfaces:**
- Consumes: existing `CrossLinked(search_engine, target, timeout, conn_timeout=3, proxies=[], jitter=0)`, `web_request`, `get_statuscode`.
- Produces: `CrossLinked.get_page(self, page, proxy=None)`; `CrossLinked.drop_proxy(self, proxy)`; `search()` continues past a blocked proxy instead of stopping.

**Current code to replace** (`crosslinked/search.py`): `Timer.__init__` sets `self.running = None`; `search()` calls `self.get_page(page)`; `get_page(self, page)` passes `self.proxies` to `web_request`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_search_rotation.py
from crosslinked.search import CrossLinked


class FakeResp:
    def __init__(self, code, content=b'<html></html>'):
        self.status_code = code
        self.content = content


def test_blocked_proxy_dropped_and_search_continues(monkeypatch):
    c = CrossLinked('brave', 'Acme', timeout=5, proxies=['1.1.1.1:80', '2.2.2.2:80'])
    seq = [FakeResp(429), FakeResp(200)]   # first proxy blocked, second returns empty page
    calls = []

    def fake_get_page(page, proxy=None):
        calls.append(proxy)
        return seq.pop(0)

    monkeypatch.setattr(c, 'get_page', fake_get_page)
    c.search()
    assert len(calls) == 2            # retried after the block instead of stopping
    assert len(c.proxies) == 1        # exactly one proxy dropped


def test_no_proxies_stops_on_non_200(monkeypatch):
    c = CrossLinked('brave', 'Acme', timeout=5, proxies=[])
    calls = []

    def fake_get_page(page, proxy=None):
        calls.append(proxy)
        return FakeResp(429)

    monkeypatch.setattr(c, 'get_page', fake_get_page)
    c.search()
    assert len(calls) == 1            # no pool -> stop immediately on non-200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_search_rotation.py -v`
Expected: FAIL (either `get_page() takes 2 positional arguments` or the rotation assertion) — confirming current `search()` stops on the 429 and never retries.

- [ ] **Step 3: Write minimal implementation**

In `crosslinked/search.py`, change `Timer.__init__` to remove the startup race:

```python
    def __init__(self, timeout):
        threading.Thread.__init__(self)
        self.start_time = None
        self.running = True
        self.timeout = timeout
```

Replace `CrossLinked.search` with:

```python
    def search(self):
        search_timer = Timer(self.timeout)
        search_timer.start()

        page = 0
        while search_timer.running:
            try:
                proxy = choice(self.proxies) if self.proxies else None
                resp = self.get_page(page, proxy)
                http_code = get_statuscode(resp)

                if http_code != 200:
                    Log.info("{:<3} {} ({})".format(len(self.results), self.search_engine, http_code))
                    if proxy:
                        self.drop_proxy(proxy)
                        Log.warn('Proxy blocked ({}), {} proxies left'.format(http_code, len(self.proxies)))
                        if not self.proxies:
                            Log.warn('Proxy pool exhausted, exiting search')
                            break
                        continue
                    Log.warn('Non-200 response, exiting search ({}) - rate-limited or blocked'.format(http_code))
                    break

                found = self.page_parser(resp)
                Log.info("{:<3} {} (200) page {}".format(len(self.results), self.search_engine, page))

                if found == 0:
                    break

                page += 1
                sleep(self.jitter)
            except KeyboardInterrupt:
                Log.warn("Key event detected, exiting search...")
                break

        search_timer.stop()
        return self.results

    def drop_proxy(self, proxy):
        try:
            self.proxies.remove(proxy)
        except ValueError:
            pass
```

Replace `CrossLinked.get_page` to accept and forward a single proxy:

```python
    def get_page(self, page, proxy=None):
        plist = [proxy] if proxy else []
        if self.search_engine == 'duckduckgo':
            data = {'q': 'site:linkedin.com/in "{}"'.format(self.target),
                    's': len(self.results), 'kl': 'us-en'}
            return web_request(self.url['duckduckgo'], self.conn_timeout, plist, method='POST', data=data)
        elif self.search_engine == 'brave':
            url = self.url['brave'].format(self.target, page)
            return web_request(url, self.conn_timeout, plist)
        url = self.url[self.search_engine].format(self.target, len(self.results))
        return web_request(url, self.conn_timeout, plist)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_search_rotation.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Regression — confirm existing import & no SyntaxWarnings**

Run: `source .venv/bin/activate && python -W error::SyntaxWarning -c "import crosslinked, crosslinked.search; print('ok')"`
Expected: prints `ok`

- [ ] **Step 6: Commit**

```bash
git add crosslinked/search.py tests/test_search_rotation.py
git commit -m "feat(search): drop blocked proxies and keep searching"
```

---

### Task 5: CLI flags & pool wiring

**Files:**
- Modify: `crosslinked/__init__.py` (`cli()` args; `main()` wiring)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `crosslinked.proxy.build_pool`.
- Produces: parsed args `free_proxies: bool`, `proxy_count: int`, `refresh_proxies: bool`; `main()` merges the validated pool into `args.proxy` before scraping.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli.py
import sys
from crosslinked import cli


def test_free_proxy_flags_parse(monkeypatch):
    monkeypatch.setattr(sys, 'argv', [
        'crosslinked', '-f', '{first}.{last}@x.com',
        '--free-proxies', '--proxy-count', '7', '--refresh-proxies', 'Acme Corp',
    ])
    args = cli()
    assert args.free_proxies is True
    assert args.proxy_count == 7
    assert args.refresh_proxies is True
    assert args.company_name == 'Acme Corp'


def test_free_proxy_defaults(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['crosslinked', '-f', '{first}.{last}@x.com', 'Acme'])
    args = cli()
    assert args.free_proxies is False
    assert args.proxy_count == 30
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_cli.py -v`
Expected: FAIL with `AttributeError: 'Namespace' object has no attribute 'free_proxies'`

- [ ] **Step 3: Write minimal implementation**

In `crosslinked/__init__.py`, add to the proxy argument group `p` (after the existing `pr` mutually-exclusive group), so it is combinable with `--proxy`/`--proxy-file`:

```python
    p.add_argument('--free-proxies', dest='free_proxies', action='store_true', help='Auto-fetch & validate free proxies for rotation')
    p.add_argument('--proxy-count', dest='proxy_count', type=int, default=30, help='Max validated free proxies to keep (Default=30)')
    p.add_argument('--refresh-proxies', dest='refresh_proxies', action='store_true', help='Force refetch of free proxies (ignore cache)')
```

Add the import near the top of `crosslinked/__init__.py`:

```python
from crosslinked.proxy import build_pool
```

In `main()`, right after the loggers are set up and before the `data = ...` line, insert:

```python
        if args.free_proxies:
            pool = build_pool(limit=args.proxy_count, refresh=args.refresh_proxies)
            if pool:
                manual = args.proxy if isinstance(args.proxy, list) else []
                args.proxy = manual + pool
            else:
                Log.warn('No working free proxies found; continuing without proxies')
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_cli.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Full suite + integration smoke**

Run: `source .venv/bin/activate && python -m pytest -v`
Expected: PASS (all tests)

Run (integration; network-dependent, non-gating):
`source .venv/bin/activate && python crosslinked.py --search duckduckgo,brave --free-proxies --proxy-count 10 -f '{first}.{last}@github.com' -t 25 -j 3 "GitHub"`
Expected: logs `Validating N candidate proxies...`, then per-page lines; on a blocked proxy logs `Proxy blocked (...), K proxies left` and continues; ends `... unique names added to names.txt!` with a non-empty `names.txt` (exact count varies with proxy health).

- [ ] **Step 6: Commit**

```bash
git add crosslinked/__init__.py tests/test_cli.py
git commit -m "feat(cli): --free-proxies flag wiring with pool rotation"
```

---

## Self-Review Notes
- **Spec coverage:** sources/parse/dedup (Task 1) ✓; parallel validation (Task 2/3) ✓; TTL cache + `--refresh-proxies` (Task 3/5) ✓; drop-on-block rotation (Task 4) ✓; `--free-proxies`/`--proxy-count` + fall-back-to-direct (Task 5) ✓; no new deps ✓. Browser engine + `setup.py` extra are **Phase 2** (separate plan), intentionally out of scope here.
- **Types:** `build_pool(...) -> list[str]` consumed in Task 5; `get_page(self, page, proxy=None)` and `drop_proxy` consistent across Task 4 and the search loop.
- **Note:** `args.proxy` may be `False` (argparse shared-dest default) when no manual proxy is given; Task 5 guards with `isinstance(args.proxy, list)`.
