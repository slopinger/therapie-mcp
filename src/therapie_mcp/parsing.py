"""Parse the public directory HTML, keeping source text separate from instructions."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

BASE_URL = 'https://www.therapie.de'
SEARCH_PATH = '/therapeutensuche/ergebnisse/'
FILTERS = {
    'focus': ('arbeitsschwerpunkt', 'Behandlungs-Schwerpunkt'),
    'method': ('verfahren', 'Therapieverfahren'),
    'billing': ('abrechnungsverfahren', 'Abrechnung'),
    'audience': ('therapieangebot', 'Therapie-Angebot'),
    'gender': ('geschlecht', 'Therapeuten-Geschlecht'),
    'language': ('sprache', 'Weitere Sprache'),
    'availability': ('terminzeitraum', 'Freie Plätze / Wartezeiten'),
}


class TherapieError(ValueError):
    """A useful user-facing validation, network or page-structure error."""


def text(node: Tag | None) -> str | None:
    return ' '.join(node.stripped_strings) if node else None


def site_url(value: str) -> str:
    parsed = urlsplit(urljoin(BASE_URL, value))
    try:
        valid_port = parsed.port in (None, 443)
    except ValueError:
        valid_port = False
    if (parsed.scheme != 'https' or parsed.hostname not in {'www.therapie.de', 'therapie.de'}
            or parsed.username or parsed.password or not valid_port):
        raise TherapieError('Only HTTPS URLs on therapie.de are supported.')
    return parsed.geturl()


def profile_url(value: str) -> str:
    value = value.strip()
    if not value:
        raise TherapieError('Provide a therapist profile ID or therapie.de profile URL.')
    if '://' not in value and not value.startswith('/'):
        value = '/profil/' + value + '/'
    parsed = urlsplit(site_url(value))
    match = re.fullmatch(r'/profil/([^/]+)/?', unquote(parsed.path))
    if not match or parsed.query or parsed.fragment:
        raise TherapieError('Expected a /profil/<id>/ URL or a profile ID.')
    identifier = match.group(1)
    if (len(identifier) > 150 or identifier in {'.', '..'}
            or not all(char.isalnum() or char in '._-' for char in identifier)):
        raise TherapieError('Invalid profile ID.')
    return BASE_URL + '/profil/' + identifier + '/'


def _property(scope: Tag, name: str) -> str | None:
    node = scope.select_one(f'[itemprop="{name}"]')
    if node is None:
        return None
    return node.get('content') or text(node)


def _address(scope: Tag) -> dict[str, str | None]:
    return {key: _property(scope, name) for key, name in (
        ('street', 'streetAddress'), ('postal_code', 'postalCode'),
        ('city', 'addressLocality'), ('country', 'addressCountry'),
    )}


def parse_filters(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, 'html.parser')
    form = soup.find('form', action=SEARCH_PATH)
    if form is None:
        raise TherapieError('Therapie.de search form was not found; the website may have changed.')
    result: dict[str, Any] = {}
    for key, (parameter, label) in FILTERS.items():
        select = form.find('select', attrs={'name': parameter})
        if select is None:
            raise TherapieError(f'Therapie.de filter {parameter!r} was not found; the website may have changed.')
        options = []
        for option in select.select('option[value]'):
            value = option.get('value', '').strip()
            if value:
                options.append({'id': value, 'label': text(option)})
        if not options:
            raise TherapieError(f'Therapie.de filter {parameter!r} contained no options.')
        result[key] = {'parameter': parameter, 'label': label, 'options': options}
    return result


def parse_search(html: str, url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, 'html.parser')
    main = soup.select_one('main.resultlist-ts')
    if main is None:
        raise TherapieError('Therapie.de results page was not found; the website may have changed.')
    summary = text(main.select_one('h5.subheader')) or ''
    match = re.search(r'([\d.\s]+)\s+Treffer', summary)
    total = int(re.sub(r'\D', '', match.group(1))) if match else None
    entries = []
    for row in main.select('.search-results-list > li'):
        scope = row.select_one('[itemtype="https://schema.org/MedicalBusiness"]') or row
        name = _property(scope, 'name') or text(row.select_one('.search-results-name'))
        if not name:
            continue
        link = scope.select_one('a[itemprop="url"][href]')
        canonical = profile_url(link['href']) if link else None
        distance = text(row.select_one('.search-results-distance'))
        number = re.search(r'([\d.,]+)\s*km', distance or '')
        entries.append({
            'profile_id': urlsplit(canonical).path.split('/')[2] if canonical else None,
            'profile_url': canonical, 'name': name,
            'description': _property(scope, 'description'),
            'address': _address(scope), 'phone': _property(scope, 'telephone'),
            'distance_km': float(number.group(1).replace(',', '.')) if number else None,
        })
    if not entries and total != 0:
        raise TherapieError('No therapist rows could be parsed; the website may have changed or rejected the search.')
    next_link = main.select_one('#pagenav-top li.next a[href]')
    next_url = site_url(next_link['href']) if next_link else None
    if next_url and urlsplit(next_url).path != SEARCH_PATH:
        raise TherapieError('Unexpected search pagination URL.')
    radius = text(main.select_one('#search-radius'))
    return {
        'source_url': url, 'title': text(main.select_one('h1')), 'summary': summary,
        'total_results': total, 'radius_km': float(radius) if radius and re.fullmatch(r'\d+(\.\d+)?', radius) else None,
        'therapists': entries, 'returned': len(entries), 'next_page_url': next_url,
    }


def _decode_email(value: str) -> str | None:
    # Same shift used by the site's public contact button (decryptString(...,-1)).
    out = []
    for char in value:
        code = ord(char)
        for lower, upper in ((43, 58), (64, 90), (97, 122)):
            if lower <= code <= upper:
                code = upper if code == lower else code - 1
                break
        out.append(chr(code))
    email = ''.join(out)
    return email if re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email) else None


def parse_profile(html: str, url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, 'html.parser')
    scope = soup.select_one('.therapist-details[itemtype="https://schema.org/MedicalBusiness"]')
    main = soup.select_one('main')
    if scope is None or main is None or not _property(scope, 'name'):
        raise TherapieError('Therapist profile was not found; the profile may be gone or the website may have changed.')
    sections = {}
    for heading in main.select('h4'):
        label = text(heading)
        values = heading.find_next_sibling('ul')
        if label and values:
            sections[label] = [text(row) for row in values.find_all('li', recursive=False)]
    contact = scope.select_one('[data-contact-email]')
    email_link = scope.select_one('a[href^="mailto:"]')
    email = _decode_email(contact['data-contact-email']) if contact else None
    if not email and email_link:
        email = unquote(email_link['href'][7:].split('?', 1)[0])
    website = scope.select_one('.contact-web a[href]')
    phone_link = scope.select_one('a[href^="tel:"]')
    updated = re.search(r'Letzte Änderung am\s+(\d{2}\.\d{2}\.\d{4})', main.get_text(' ', strip=True))
    return {
        'source_url': url, 'profile_id': urlsplit(profile_url(url)).path.split('/')[2],
        'name': _property(scope, 'name'), 'description': _property(scope, 'description'),
        'address': _address(scope), 'phone': _property(scope, 'telephone'),
        'phone_uri': phone_link['href'] if phone_link else None,
        'email': email, 'website': website['href'] if website else None,
        'qualifications_and_billing': sections.get('Ausbildung, Heilerlaubnis, Abrechnung', []),
        'focuses': sections.get('Behandlungs-Schwerpunkte', []),
        'methods': sections.get('Verfahren', []),
        'audiences': sections.get('Therapie-Angebot', []),
        'availability': sections.get('Freie Plätze / Wartezeiten', []),
        'memberships': sections.get('Mitgliedschaften', []),
        'last_changed': updated.group(1) if updated else None,
        'availability_note': 'Directory statements are self-reported. Confirm current availability and billing directly with the practice.',
    }
