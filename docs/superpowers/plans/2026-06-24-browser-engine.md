# Browser-Solve Google Engine Implementation Plan (Phase 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add an optional `--search google` engine that drives a real headed Chromium via Playwright, pauses for the user to solve any reCAPTCHA/`/sorry/` challenge, then scrapes rendered LinkedIn `/in/` results — reusing the existing parsing/dedup/CSV pipeline.

**Architecture:** New `crosslinked/browser.py` with (a) pure helpers `is_challenge(url, html)` and `extract_google_results(html)` (fixture-testable), and (b) a `BrowserSearch` class that launches a persistent headed context, paginates Google, detects challenges and blocks on `input()` for the user to solve, and delegates each `(href, text)` to a reused `CrossLinked('google', ...)` instance for name/title parsing, dedup, and CSV logging. `start_scrape` routes `--search google` to `BrowserSearch`. Playwright is an OPTIONAL extra; absence yields a clear install message, never a crash for non-google engines.

**Tech Stack:** Python 3, Playwright (optional extra), BeautifulSoup (already used), pytest.

## Global Constraints
- Python 3.8-compatible syntax.
- Playwright is an OPTIONAL dependency (`crosslinked[browser]`); core engines (duckduckgo/brave) must keep working with playwright absent. Import playwright lazily INSIDE `BrowserSearch`, never at module top level used by `__init__.py`.
- Reuse the existing `CrossLinked` parsing/dedup/CSV logging — do NOT duplicate `parse_linkedin_name`/`parse_linkedin_title`/`results_handler`/`log_results`.
- Persistent profile + browser cache live under `~/.crosslinked/` (profile dir `~/.crosslinked/profile`).
- Headed mode requires a display; default headed. Provide a `--headless` opt-out (challenge cannot be solved headless — document that).
- Never use `pip install --break-system-packages`; venv at `crosslinked/.venv` (playwright already installed there). System chromium is at `/usr/bin/chromium`; pass it as `executable_path` to avoid browser-version juggling.
- Work in `/home/pentester/claude/claude_osint_tools_fix/crosslinked`; tests run from repo root with `source .venv/bin/activate`.

## File Structure
- **Create** `crosslinked/browser.py` — browser navigation, challenge hand-off, Google extraction. Delegates parsing to `CrossLinked`.
- **Modify** `crosslinked/__init__.py` — route `--search google` to `BrowserSearch`; add `--headless` flag.
- **Modify** `setup.py` + `pyproject.toml` — add optional `browser` extra (`playwright`).
- **Create** `tests/test_browser.py` — fixture tests for `is_challenge`, `extract_google_results`, and the paginate/challenge loop with a mocked fetcher.

---

### Task 1: Pure helpers — challenge detection & Google result extraction

**Files:**
- Create: `crosslinked/browser.py`
- Test: `tests/test_browser.py`

**Interfaces:**
- Produces: `is_challenge(url: str, html: str) -> bool`; `extract_google_results(html: str) -> list[tuple[str, str]]` (each tuple is `(href, title_text)`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_browser.py
from crosslinked.browser import is_challenge, extract_google_results

GOOGLE_RESULTS = """
<div class="g"><a href="https://www.linkedin.com/in/jdoe"><h3>John Doe - Engineer at Acme</h3></a></div>
<div class="g"><a href="https://www.linkedin.com/in/asmith"><br><h3>Alice Smith - Acme</h3></a></div>
<div class="g"><a href="https://www.google.com/imgres?q=x">an image</a></div>
<div class="g"><a href="https://www.linkedin.com/in/jdoe"><h3>John Doe - Engineer at Acme</h3></a></div>
"""

SORRY_PAGE = '<html><head><title>https://www.google.com/sorry/index</title></head><body>Our systems have detected unusual traffic ... recaptcha</body></html>'


def test_is_challenge_detects_sorry_url():
    assert is_challenge('https://www.google.com/sorry/index?continue=x', '<html></html>') is True


def test_is_challenge_detects_body_markers():
    assert is_challenge('https://www.google.com/search?q=x', SORRY_PAGE) is True


def test_is_challenge_false_on_normal_results():
    assert is_challenge('https://www.google.com/search?q=x', GOOGLE_RESULTS) is False


def test_extract_google_results_pulls_linkedin_in_with_titles():
    res = extract_google_results(GOOGLE_RESULTS)
    assert ('https://www.linkedin.com/in/jdoe', 'John Doe - Engineer at Acme') in res
    assert ('https://www.linkedin.com/in/asmith', 'Alice Smith - Acme') in res
    # non-linkedin anchors excluded
    assert all('linkedin.com/in' in href for href, _ in res)
    # duplicate anchor still returned at extraction layer (dedup happens downstream)
    assert len(res) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_browser.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'crosslinked.browser'`

- [ ] **Step 3: Write minimal implementation**

```python
# crosslinked/browser.py
from bs4 import BeautifulSoup

CHALLENGE_MARKERS = ('unusual traffic', 'recaptcha', 'our systems have detected', 'id="captcha-form"')


def is_challenge(url, html):
    u = (url or '').lower()
    h = (html or '').lower()
    if '/sorry/' in u:
        return True
    return any(m in h for m in CHALLENGE_MARKERS)


def extract_google_results(html):
    soup = BeautifulSoup(html or '', 'lxml')
    out = []
    for a in soup.find_all('a'):
        href = a.get('href') or ''
        if 'linkedin.com/in' not in href:
            continue
        h3 = a.find('h3')
        text = h3.get_text(' ', strip=True) if h3 else a.get_text(' ', strip=True)
        out.append((href, text))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_browser.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add crosslinked/browser.py tests/test_browser.py
git commit -m "feat(browser): Google challenge detection + result extraction

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `BrowserSearch` — paginate, challenge hand-off, parse-delegation

**Files:**
- Modify: `crosslinked/browser.py`
- Test: `tests/test_browser.py`

**Interfaces:**
- Consumes: `is_challenge`, `extract_google_results`; `crosslinked.search.CrossLinked` (reused as parser — call `results_handler(href, text)`, read `.results`); `crosslinked.logger.Log`.
- Produces: `BrowserSearch(target, timeout, jitter=0, headless=False, profile_dir=None, max_pages=5)`; methods `search() -> list[dict]`, `_fetch(page_index) -> tuple[str, str]` (returns `(url, html)`; the seam tests mock), `_solve_challenge()` (blocks on input()), `_extract_into_parser(html) -> int` (returns new-result count).

Design notes for the implementer:
- `search()` loops page indices `0..max_pages-1`. For each: `url, html = self._fetch(i)`. If `is_challenge(url, html)`: call `self._solve_challenge()` then re-`_fetch(i)` once. Then `found = self._extract_into_parser(html)`; if `found == 0` after a non-challenge page, break (end of results). Sleep `jitter` between pages. Return `self.parser.results`.
- `self.parser = CrossLinked('google', target, timeout, jitter=jitter)` — used ONLY for `results_handler`/`log_results`/`.results`; `_extract_into_parser` calls `self.parser.results_handler(href, text)` for each `(href, text)` from `extract_google_results(html)` and counts the `True` returns.
- `_solve_challenge()` prints a clear instruction and calls `input()` (blocking pause). Keep it tiny so it can be monkeypatched.
- `_fetch` is the ONLY method that touches Playwright (added in Task... here). For THIS task, implement `_fetch` to drive Playwright (lazy import inside the method), but design `search()`/`_extract_into_parser`/`_solve_challenge` so tests inject fakes by monkeypatching `_fetch` and `_solve_challenge`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_browser.py
from crosslinked.browser import BrowserSearch


def _make(monkeypatch, pages, solved=None):
    bs = BrowserSearch('Acme', timeout=5, jitter=0, max_pages=5)
    calls = {'fetch': [], 'solve': 0}

    def fake_fetch(i):
        calls['fetch'].append(i)
        return pages[i]

    def fake_solve():
        calls['solve'] += 1
        if solved is not None:
            pages[calls['fetch'][-1]] = solved  # next refetch returns solved page

    monkeypatch.setattr(bs, '_fetch', fake_fetch)
    monkeypatch.setattr(bs, '_solve_challenge', fake_solve)
    return bs, calls


def test_browser_search_collects_and_dedups(monkeypatch):
    page0 = ('https://www.google.com/search?q=x', GOOGLE_RESULTS)   # 3 anchors, 2 unique people
    empty = ('https://www.google.com/search?q=x&start=10', '<html></html>')
    bs, calls = _make(monkeypatch, {0: page0, 1: empty})
    results = bs.search()
    names = sorted(r['name'] for r in results)
    assert names == ['alice smith', 'john doe']     # deduped via reused CrossLinked
    assert calls['fetch'] == [0, 1]                  # stopped after the empty page


def test_browser_search_pauses_on_challenge_then_resumes(monkeypatch):
    challenge = ('https://www.google.com/sorry/index', SORRY_PAGE)
    empty = ('https://www.google.com/search?q=x&start=10', '<html></html>')
    bs, calls = _make(monkeypatch, {0: challenge, 1: empty}, solved=GOOGLE_RESULTS)
    results = bs.search()
    assert calls['solve'] == 1                       # paused exactly once
    assert sorted(r['name'] for r in results) == ['alice smith', 'john doe']
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_browser.py -k browser_search -v`
Expected: FAIL with `AttributeError`/`ImportError` (BrowserSearch not defined).

- [ ] **Step 3: Write minimal implementation**

```python
# add to crosslinked/browser.py
import os
from time import sleep
from crosslinked.logger import Log
from crosslinked.search import CrossLinked

GOOGLE_URL = 'https://www.google.com/search?q=site:linkedin.com/in+"{}"&num=30&start={}'


class BrowserSearch:
    def __init__(self, target, timeout, jitter=0, headless=False, profile_dir=None, max_pages=5):
        self.target = target
        self.timeout = timeout
        self.jitter = jitter
        self.headless = headless
        self.max_pages = max_pages
        self.profile_dir = profile_dir or os.path.expanduser('~/.crosslinked/profile')
        self.parser = CrossLinked('google', target, timeout, jitter=jitter)
        self._ctx = None

    def search(self):
        try:
            for i in range(self.max_pages):
                url, html = self._fetch(i)
                if is_challenge(url, html):
                    self._solve_challenge()
                    url, html = self._fetch(i)
                found = self._extract_into_parser(html)
                Log.info("{:<3} google (browser) page {}".format(len(self.parser.results), i))
                if found == 0:
                    break
                sleep(self.jitter)
        except KeyboardInterrupt:
            Log.warn("Key event detected, exiting search...")
        finally:
            self._close()
        return self.parser.results

    def _extract_into_parser(self, html):
        new = 0
        for href, text in extract_google_results(html):
            try:
                if self.parser.results_handler(href, text):
                    new += 1
            except Exception as e:
                Log.warn('Failed Parsing: {} - {}'.format(href, e))
        return new

    def _solve_challenge(self):
        Log.warn('Google challenge detected. Solve it in the browser window, then press [Enter] to continue...')
        try:
            input()
        except EOFError:
            pass

    def _fetch(self, page_index):
        page = self._page()
        url = GOOGLE_URL.format(self.target, page_index * 30)
        page.goto(url, wait_until='domcontentloaded', timeout=int(self.timeout * 1000))
        page.wait_for_timeout(1200)
        return page.url, page.content()

    def _page(self):
        if self._ctx is None:
            from playwright.sync_api import sync_playwright
            self._pw = sync_playwright().start()
            os.makedirs(self.profile_dir, exist_ok=True)
            self._ctx = self._pw.chromium.launch_persistent_context(
                self.profile_dir, headless=self.headless, executable_path='/usr/bin/chromium',
                args=['--disable-blink-features=AutomationControlled'],
                user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
            self._page_obj = self._ctx.new_page()
        return self._page_obj

    def _close(self):
        try:
            if self._ctx is not None:
                self._ctx.close()
                self._pw.stop()
        except Exception:
            pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_browser.py -v`
Expected: PASS (6 tests). The browser-driving methods (`_fetch`/`_page`/`_close`) are monkeypatched out in tests, so no real browser launches.

- [ ] **Step 5: Commit**

```bash
git add crosslinked/browser.py tests/test_browser.py
git commit -m "feat(browser): BrowserSearch with challenge pause and parse reuse

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: CLI routing, optional extra, friendly missing-dep error

**Files:**
- Modify: `crosslinked/__init__.py` (route `google` → `BrowserSearch`; add `--headless`)
- Modify: `setup.py`, `pyproject.toml` (add `browser` extra)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `BrowserSearch` (lazy import inside `start_scrape`'s google branch so non-google runs don't require playwright).
- Produces: parsed arg `headless: bool`; `start_scrape` routes `google` to the browser engine.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_cli.py
def test_headless_flag_parses(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['crosslinked', '-f', '{first}.{last}@x.com', '--headless', '--search', 'google', 'Acme'])
    args = cli()
    assert args.headless is True
    assert args.engine == ['google']


def test_google_routes_to_browser_search(monkeypatch):
    import crosslinked as cl

    class FakeBrowser:
        def __init__(self, *a, **k):
            self.args = a
        def search(self):
            return [{'name': 'jane doe', 'title': 'x', 'url': 'u', 'text': 't'}]

    monkeypatch.setattr('crosslinked.browser.BrowserSearch', FakeBrowser)

    class A:
        engine = ['google']; company_name = 'Acme'; timeout = 15; jitter = 1
        proxy = []; headless = False
    out = cl.start_scrape(A())
    assert out == [{'name': 'jane doe', 'title': 'x', 'url': 'u', 'text': 't'}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_cli.py -k "headless or google_routes" -v`
Expected: FAIL (`AttributeError: 'Namespace' object has no attribute 'headless'`, and `start_scrape` does not route google).

- [ ] **Step 3: Write minimal implementation**

In `crosslinked/__init__.py` `cli()`, add to the Search group `s`:

```python
    s.add_argument('--headless', dest='headless', action='store_true', help='Run the google browser engine headless (cannot solve challenges)')
```

Replace the `start_scrape` loop body to route google to the browser engine:

```python
def start_scrape(args):
    tmp = []
    Log.info("Searching {} for valid employee names at \"{}\"".format(', '.join(args.engine), args.company_name))

    for search_engine in args.engine:
        if search_engine == 'google':
            try:
                from crosslinked.browser import BrowserSearch
            except ImportError:
                Log.fail("google engine needs the browser extra: pip install crosslinked[browser] && playwright install chromium")
                continue
            bs = BrowserSearch(args.company_name, args.timeout, args.jitter, headless=getattr(args, 'headless', False))
            tmp += bs.search()
            continue
        c = CrossLinked(search_engine, args.company_name, args.timeout, 3, args.proxy, args.jitter)
        if search_engine in c.url.keys():
            tmp += c.search()
    return tmp
```

In `setup.py`, add to the `setup(...)` call:

```python
    extras_require={'browser': ['playwright']},
```

In `pyproject.toml`, under `[tool.poetry.dependencies]` add an optional dep + an extra:

```toml
playwright = {version = "^1.40", optional = true}

[tool.poetry.extras]
browser = ["playwright"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/test_cli.py -v`
Expected: PASS (all CLI tests).

- [ ] **Step 5: Full suite + import-guard regression**

Run: `source .venv/bin/activate && python -m pytest -q`
Expected: PASS (all tests).

Run (proves non-google path doesn't need playwright at import time):
`source .venv/bin/activate && python -W error::SyntaxWarning -c "import crosslinked, crosslinked.browser; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 6: Manual live smoke (interactive — for the human; NON-GATING)**

Run: `source .venv/bin/activate && python crosslinked.py --search google -f '{first}.{last}@tesla.com' -t 30 -j 3 "Tesla"`
Expected: a Chromium window opens; if Google shows a challenge, the console prints the solve prompt and waits for Enter; after solving, results are scraped and `names.txt` is written. (Cannot be automated — requires a human to solve the challenge.)

- [ ] **Step 7: Commit**

```bash
git add crosslinked/__init__.py setup.py pyproject.toml tests/test_cli.py
git commit -m "feat(cli): route --search google to the browser engine; browser extra

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review Notes
- **Spec coverage (Subsystem 3):** persistent headed context (Task 2 `_page`) ✓; pause-on-challenge via input() (Task 2 `_solve_challenge`) ✓; reuse parsing/CSV via CrossLinked (Task 2) ✓; `--search google` routing + optional extra + missing-dep guard (Task 3) ✓; `--headless` opt-out documented ✓.
- **Type consistency:** `_fetch(i) -> (url, html)`, `extract_google_results -> list[(href,text)]`, `BrowserSearch.search() -> list[dict]` consistent across tasks; `results_handler(href, text) -> bool` matches the Phase 1 signature in `search.py`.
- **Testability:** browser-driving methods are isolated behind `_fetch`/`_page`/`_close` and monkeypatched in tests; the only un-automatable path is the human solve, covered by the Task 3 manual smoke.
- **Known limitation (documented):** automated Chromium may be re-challenged repeatedly even after solving; persistent profile + realistic UA mitigate but do not eliminate this. Headless cannot solve challenges.
