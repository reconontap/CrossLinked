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


def test_free_proxies_combinable_with_proxy(monkeypatch):
    monkeypatch.setattr(sys, 'argv', [
        'crosslinked', '-f', '{first}.{last}@x.com',
        '--proxy', '9.9.9.9:80', '--free-proxies', 'Acme',
    ])
    args = cli()
    assert args.proxy == ['9.9.9.9:80']
    assert args.free_proxies is True


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
