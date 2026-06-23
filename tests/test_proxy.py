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
