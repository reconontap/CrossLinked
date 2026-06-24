from crosslinked.browser import is_challenge, extract_google_results, BrowserSearch

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
    bs, calls = _make(monkeypatch, {0: challenge, 1: empty},
                     solved=('https://www.google.com/search?q=x', GOOGLE_RESULTS))
    results = bs.search()
    assert calls['solve'] == 1                       # paused exactly once
    assert sorted(r['name'] for r in results) == ['alice smith', 'john doe']


def test_browser_search_returns_partial_results_on_fetch_error(monkeypatch):
    bs = BrowserSearch('Acme', timeout=5, jitter=0, max_pages=5)
    state = {'n': 0}

    def fake_fetch(i):
        if state['n'] == 0:
            state['n'] += 1
            return ('https://www.google.com/search?q=x', GOOGLE_RESULTS)
        raise RuntimeError('playwright boom')

    monkeypatch.setattr(bs, '_fetch', fake_fetch)
    monkeypatch.setattr(bs, '_solve_challenge', lambda: None)
    closed = {'n': 0}
    monkeypatch.setattr(bs, '_close', lambda: closed.__setitem__('n', closed['n'] + 1))
    results = bs.search()
    # page 0 collected results; page 1 raised -> caught -> partial results returned
    assert sorted(r['name'] for r in results) == ['alice smith', 'john doe']
    assert closed['n'] == 1            # _close() ran on the error path (finally)


def test_browser_search_challenge_persists_after_solve(monkeypatch):
    challenge = ('https://www.google.com/sorry/index', SORRY_PAGE)
    bs = BrowserSearch('Acme', timeout=5, jitter=0, max_pages=5)
    calls = {'solve': 0}

    def fake_fetch(i):
        return challenge                      # still a challenge even after solving

    def fake_solve():
        calls['solve'] += 1

    monkeypatch.setattr(bs, '_fetch', fake_fetch)
    monkeypatch.setattr(bs, '_solve_challenge', fake_solve)
    monkeypatch.setattr(bs, '_close', lambda: None)
    out = bs.search()
    assert calls['solve'] == 1                # solved once; post-solve page still a challenge -> stop, no loop
    assert out == []


def test_browser_search_browser_unavailable_is_friendly(monkeypatch):
    from crosslinked.browser import BrowserUnavailable
    bs = BrowserSearch('Acme', timeout=5, jitter=0, max_pages=5)

    def boom(i):
        raise BrowserUnavailable('Install it with: playwright install chromium')

    monkeypatch.setattr(bs, '_fetch', boom)
    monkeypatch.setattr(bs, '_close', lambda: None)
    out = bs.search()
    assert out == []                          # handled gracefully, no crash
