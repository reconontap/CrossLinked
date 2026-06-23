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
