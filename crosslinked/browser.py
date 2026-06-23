from bs4 import BeautifulSoup

CHALLENGE_MARKERS = ('unusual traffic', 'recaptcha', 'our systems have detected', 'id="captcha-form"')


def is_challenge(url, html):
    u = (url or '').lower()
    h = (html or '').lower()
    if '/sorry/' in u:
        return True
    return any(m in h for m in CHALLENGE_MARKERS)


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
