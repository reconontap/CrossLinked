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


def test_proxies_isolated_per_engine_instance():
    # A shared pool passed to two engines must not be drained across them:
    # each CrossLinked gets its own copy, and the caller's list is untouched.
    shared = ['1.1.1.1:80', '2.2.2.2:80', '3.3.3.3:80']
    a = CrossLinked('duckduckgo', 'Acme', timeout=5, proxies=shared)
    b = CrossLinked('brave', 'Acme', timeout=5, proxies=shared)
    a.drop_proxy('1.1.1.1:80')
    a.drop_proxy('2.2.2.2:80')
    assert len(a.proxies) == 1
    assert len(b.proxies) == 3
    assert len(shared) == 3
