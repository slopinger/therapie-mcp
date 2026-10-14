import pytest
from therapie_mcp.parsing import TherapieError, parse_filters, parse_profile, parse_search, profile_url, site_url

@pytest.mark.parametrize('value', ['test.person', '/profil/test.person/', 'https://www.therapie.de/profil/test.person/'])
def test_profile_url(value):
    assert profile_url(value) == 'https://www.therapie.de/profil/test.person/'

@pytest.mark.parametrize('value', ['https://evil.test/profil/x/', '//evil.test/profil/x/', 'http://www.therapie.de/profil/x/', 'https://user@www.therapie.de/profil/x/', 'https://www.therapie.de:8443/profil/x/', '../x', 'x/y', '%2fetc', 'https://www.therapie.de/profil/x/?secret=x'])
def test_unsafe_profile_url(value):
    with pytest.raises(TherapieError):
        profile_url(value)

def test_filters(filters_html):
    result = parse_filters(filters_html)
    assert len(result) == 7
    assert result['billing']['parameter'] == 'abrechnungsverfahren'
    assert result['billing']['options'][0] == {'id': '1', 'label': 'Test Option'}

def test_search(search_html):
    result = parse_search(search_html, 'source')
    assert result['total_results'] == 1234
    assert result['radius_km'] == 25
    assert result['returned'] == 1
    assert result['therapists'][0]['profile_id'] == 'test.person'
    assert result['therapists'][0]['distance_km'] == 1.2
    assert 'page=2' in result['next_page_url']

def test_zero_results():
    result = parse_search('<main class="resultlist-ts"><h5 class="subheader">0 Treffer</h5></main>', 'source')
    assert result['therapists'] == []
    assert result['total_results'] == 0

def test_profile(profile_html):
    result = parse_profile(profile_html, 'https://www.therapie.de/profil/test.person/')
    assert result['email'] == 'test@example.org'
    assert result['methods'] == ['Verhaltenstherapie']
    assert result['audiences'] == ['Einzeltherapie: Erwachsene']
    assert result['availability'] == ['Wartezeit bis drei Monate']
    assert result['last_changed'] == '14.10.2026'
    assert result['phone_uri'] == 'tel:030000000'

@pytest.mark.parametrize('parser', [parse_filters, lambda html: parse_search(html, 'source'), lambda html: parse_profile(html, 'https://www.therapie.de/profil/x/')])
def test_changed_page_fails_clearly(parser):
    with pytest.raises(TherapieError):
        parser('<html><h1>Access denied</h1></html>')
