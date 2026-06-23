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


def validate(proxy, timeout=5, test_url=IP_ECHO):
    scheme = _scheme(proxy)
    try:
        r = requests.get(test_url, proxies={'http': scheme, 'https': scheme}, timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


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
