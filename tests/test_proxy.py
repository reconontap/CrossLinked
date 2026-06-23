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
