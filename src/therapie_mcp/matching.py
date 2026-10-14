"""Compare explicit directory facts with the user's stated requirements."""
from __future__ import annotations
import re
import unicodedata
from typing import Any
from .parsing import TherapieError

BILLING_ALIASES = {'gesetzliche krankenversicherung': 'gkv: kassenleistung',
                   'gesetzliche krankenversicherung im kostenerstattungsverfahren': 'kostenerstattungsverfahren'}

FIELDS = {'billing', 'methods', 'focuses', 'audiences', 'languages', 'availability'}


def normalized(value: str) -> str:
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', value).casefold()).strip().rstrip('.')


def compare(profiles: list[dict[str, Any]], requirements: dict[str, list[str]], require_approbation: bool = False) -> dict[str, Any]:
    if set(requirements) - FIELDS:
        raise TherapieError('Supported comparison fields: ' + ', '.join(sorted(FIELDS)))
    if any(not isinstance(values, list) or not values or len(values) > 20 or
           any(not isinstance(value, str) or not value.strip() or len(value) > 200 for value in values)
           for values in requirements.values()):
        raise TherapieError('Each comparison field needs 1–20 non-empty option labels, at most 200 characters each.')
    results = []
    for profile in profiles:
        checks = []
        for field, desired in requirements.items():
            reported = profile.get(field, [])
            def label(value):
                value = normalized(value)
                return BILLING_ALIASES.get(value, value) if field == 'billing' else value
            matches = [wanted for wanted in desired if label(wanted) in {label(value) for value in reported}]
            checks.append({'field': field, 'wanted_any_of': desired, 'reported': reported,
                           'result': 'match' if matches else 'unknown' if not reported else 'not_listed', 'matched': matches})
        if require_approbation:
            qualifications = profile.get('qualifications', [])
            licensed = any(re.search(r'\bapprobiert\b|\bapprobation\b', normalized(value)) and
                           not re.search(r'\bnicht\b|\bohne\b', normalized(value)) for value in qualifications)
            checks.append({'field': 'approbation', 'reported': qualifications,
                           'result': 'match' if licensed else 'unknown',
                           'note': 'Only an explicit directory statement is checked; this is not professional-register verification.'})
        results.append({'profile_id': profile['profile_id'], 'name': profile['name'], 'source_url': profile['source_url'],
                        'retrieved_at': profile.get('retrieved_at'), 'checks': checks,
                        'all_requirements_listed': bool(checks) and all(check['result'] == 'match' for check in checks),
                        'matched_criteria': sum(check['result'] == 'match' for check in checks)})
    return {'comparisons': results, 'note': 'Exact directory-label comparison, not a clinical suitability or quality ranking. Unknown or not_listed means confirm directly. Alternatives within one field are OR; different fields are AND.'}
