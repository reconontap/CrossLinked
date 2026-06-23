import logging
import requests
import threading
from time import sleep
from random import choice
from bs4 import BeautifulSoup
from unidecode import unidecode
from urllib.parse import urlparse
from crosslinked.logger import Log
from datetime import datetime, timedelta
from urllib3 import disable_warnings, exceptions

disable_warnings(exceptions.InsecureRequestWarning)
logging.getLogger("urllib3").setLevel(logging.WARNING)
csv = logging.getLogger('cLinked_csv')


class Timer(threading.Thread):
    def __init__(self, timeout):
        threading.Thread.__init__(self)
        self.start_time = None
        self.running = True
        self.timeout = timeout

    def run(self):
        self.running = True
        self.start_time = datetime.now()
        logging.debug("Thread Timer: Started")

        while self.running:
            if (datetime.now() - self.start_time) > timedelta(seconds=self.timeout):
                self.stop()
            sleep(0.05)

    def stop(self):
        logging.debug("Thread Timer: Stopped")
        self.running = False


class CrossLinked:
    def __init__(self, search_engine, target, timeout, conn_timeout=3, proxies=[], jitter=0):
        self.results = []
        # Google & Bing now block/deflect unauthenticated scraping (429/CAPTCHA & empty
        # bot-shells respectively). They are kept selectable (may work through proxies) but
        # 'duckduckgo,brave' are the working defaults. See start_scrape() in __init__.py.
        self.url = {'google': 'https://www.google.com/search?q=site:linkedin.com/in+"{}"&num=100&start={}',
                    'bing': 'https://www.bing.com/search?q="{}"+site:linkedin.com/in&first={}',
                    'duckduckgo': 'https://html.duckduckgo.com/html/',
                    'brave': 'https://search.brave.com/search?q="{}"+site:linkedin.com/in&offset={}'}

        self.runtime = datetime.now().strftime('%m-%d-%Y %H:%M:%S')
        self.search_engine = search_engine
        self.conn_timeout = conn_timeout
        self.timeout = timeout
        self.proxies = list(proxies)
        self.target = target
        self.jitter = jitter

    def search(self):
        search_timer = Timer(self.timeout)
        search_timer.start()

        page = 0
        while search_timer.running:
            try:
                proxy = choice(self.proxies) if self.proxies else None
                resp = self.get_page(page, proxy)
                http_code = get_statuscode(resp)

                if http_code != 200:
                    Log.info("{:<3} {} ({})".format(len(self.results), self.search_engine, http_code))
                    if proxy:
                        self.drop_proxy(proxy)
                        Log.warn('Proxy blocked ({}), {} proxies left'.format(http_code, len(self.proxies)))
                        if not self.proxies:
                            Log.warn('Proxy pool exhausted, exiting search')
                            break
                        sleep(self.jitter)
                        continue
                    Log.warn('Non-200 response, exiting search ({}) - rate-limited or blocked'.format(http_code))
                    break

                found = self.page_parser(resp)
                Log.info("{:<3} {} (200) page {}".format(len(self.results), self.search_engine, page))

                if found == 0:
                    break

                page += 1
                sleep(self.jitter)
            except KeyboardInterrupt:
                Log.warn("Key event detected, exiting search...")
                break

        search_timer.stop()
        return self.results

    def drop_proxy(self, proxy):
        try:
            self.proxies.remove(proxy)
        except ValueError:
            pass

    def get_page(self, page, proxy=None):
        # Build the per-engine request. DuckDuckGo's HTML endpoint expects a POST form;
        # the rest paginate via a GET offset parameter.
        plist = [proxy] if proxy else []
        if self.search_engine == 'duckduckgo':
            data = {'q': 'site:linkedin.com/in "{}"'.format(self.target),
                    's': len(self.results), 'kl': 'us-en'}
            return web_request(self.url['duckduckgo'], self.conn_timeout, plist, method='POST', data=data)
        elif self.search_engine == 'brave':
            # Brave paginates by page index (offset=0,1,2...), not result count.
            url = self.url['brave'].format(self.target, page)
            return web_request(url, self.conn_timeout, plist)
        # google / bing (legacy) paginate by result-count offset.
        url = self.url[self.search_engine].format(self.target, len(self.results))
        return web_request(url, self.conn_timeout, plist)

    def page_parser(self, resp):
        # Returns the number of NEW results captured from this page.
        new = 0
        for url, text in self.extract_results(resp):
            try:
                if self.results_handler(url, text):
                    new += 1
            except Exception as e:
                Log.warn('Failed Parsing: {} - {}'.format(url, e))
        return new

    def extract_results(self, resp):
        # Yield (href, title_text) tuples using the engine-specific result layout.
        soup = BeautifulSoup(resp.content, 'lxml')
        results = []

        if self.search_engine == 'duckduckgo':
            for a in soup.select('a.result__a'):
                href = a.get('href')
                if href:
                    results.append((href, a.get_text(' ', strip=True)))

        elif self.search_engine == 'brave':
            for snip in soup.select('div.snippet'):
                a = snip.select_one('a[href*="linkedin.com/in"]')
                title = snip.select_one('.title')
                if a and title:
                    results.append((a.get('href'), title.get_text(' ', strip=True)))

        else:
            # google / bing legacy layout: scan every anchor, filter by href downstream.
            for a in soup.find_all('a'):
                href = a.get('href')
                if href:
                    results.append((href, a.get_text(' ', strip=True)))

        return results

    def link_parser(self, url, text):
        u = {'url': url}
        u['text'] = unidecode(text.split("|")[0].split("...")[0]).strip()  # Capture link text before trailing chars
        u['title'] = self.parse_linkedin_title(u['text'])                  # Extract job title
        u['name'] = self.parse_linkedin_name(u['text'])                    # Extract whole name
        return u

    def parse_linkedin_title(self, data):
        try:
            title = data.split("-")[1].split('https:')[0]
            return title.split("...")[0].split("|")[0].strip()
        except:
            return 'N/A'

    def parse_linkedin_name(self, data):
        try:
            name = data.split("-")[0].strip()
            return unidecode(name).lower()
        except:
            return False

    def results_handler(self, href, text):
        url = str(href).lower()

        if not extract_subdomain(url).endswith('linkedin.com'):
            return False
        elif 'linkedin.com/in' not in url:
            return False
        elif any(x in url for x in ('/login', '/authwall', 'session_redirect', 'fromsignin')):
            # Skip auth/login links that carry a profile URL inside a redirect parameter
            return False

        data = self.link_parser(url, text)
        return self.log_results(data) if data['name'] else False

    def log_results(self, d):
        # Prevent Duplicates & non-standard responses (i.e: "<span>linkedin.com</span></a>")
        if d in self.results:
            return False
        elif 'linkedin.com' in d['name']:
            return False

        self.results.append(d)
        # Search results are logged to names.csv but names.txt is not generated until end to prevent duplicates
        logging.debug('name: {:25} RawTxt: {}'.format(d['name'], d['text']))
        csv.info('"{}","{}","{}","{}","{}","{}",'.format(self.runtime, self.search_engine, d['name'], d['title'], d['url'], d['text']))
        return True


def get_statuscode(resp):
    try:
        return resp.status_code
    except:
        return 0


def get_proxy(proxies):
    tmp = choice(proxies) if proxies else False
    return {"http": tmp, "https": tmp} if tmp else {}


def get_agent():
    return choice([
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 14.2; rv:121.0) Gecko/20100101 Firefox/121.0',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15'
    ])


def web_request(url, timeout=3, proxies=[], method='GET', data=None, **kwargs):
    try:
        s = requests.Session()
        headers = {
            'User-Agent': get_agent(),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        }
        r = requests.Request(method, url, headers=headers, data=data, cookies={'CONSENT': 'YES+'}, **kwargs)
        p = r.prepare()
        return s.send(p, timeout=timeout, verify=False, proxies=get_proxy(proxies), allow_redirects=True)
    except requests.exceptions.TooManyRedirects as e:
        Log.fail('Proxy Error: {}'.format(e))
    except:
        pass
    return False


def extract_subdomain(url):
    return urlparse(url).netloc
