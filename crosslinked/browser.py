import os
from time import sleep
from bs4 import BeautifulSoup
from crosslinked.logger import Log
from crosslinked.search import CrossLinked

CHALLENGE_MARKERS = ('unusual traffic', 'recaptcha', 'our systems have detected', 'id="captcha-form"')


def is_challenge(url, html):
    u = (url or '').lower()
    h = (html or '').lower()
    if '/sorry/' in u:
        return True
    return any(m in h for m in CHALLENGE_MARKERS)


GOOGLE_URL = 'https://www.google.com/search?q=site:linkedin.com/in+"{}"&num=30&start={}'


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
