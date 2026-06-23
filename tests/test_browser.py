from crosslinked.browser import is_challenge, extract_google_results

GOOGLE_RESULTS = """
<div class="g"><a href="https://www.linkedin.com/in/jdoe"><h3>John Doe - Engineer at Acme</h3></a></div>
<div class="g"><a href="https://www.linkedin.com/in/asmith"><br><h3>Alice Smith - Acme</h3></a></div>
<div class="g"><a href="https://www.google.com/imgres?q=x">an image</a></div>
<div class="g"><a href="https://www.linkedin.com/in/jdoe"><h3>John Doe - Engineer at Acme</h3></a></div>
"""

SORRY_PAGE = '<html><head><title>https://www.google.com/sorry/index</title></head><body>Our systems have detected unusual traffic ... recaptcha</body></html>'


def test_is_challenge_detects_sorry_url():
    assert is_challenge('https://www.google.com/sorry/index?continue=x', '<html></html>') is True


def test_is_challenge_detects_body_markers():
    assert is_challenge('https://www.google.com/search?q=x', SORRY_PAGE) is True


def test_is_challenge_false_on_normal_results():
    assert is_challenge('https://www.google.com/search?q=x', GOOGLE_RESULTS) is False


def test_extract_google_results_pulls_linkedin_in_with_titles():
    res = extract_google_results(GOOGLE_RESULTS)
    assert ('https://www.linkedin.com/in/jdoe', 'John Doe - Engineer at Acme') in res
    assert ('https://www.linkedin.com/in/asmith', 'Alice Smith - Acme') in res
    # non-linkedin anchors excluded
    assert all('linkedin.com/in' in href for href, _ in res)
    # duplicate anchor still returned at extraction layer (dedup happens downstream)
    assert len(res) == 3
