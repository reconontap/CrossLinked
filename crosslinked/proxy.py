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
