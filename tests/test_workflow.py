from datetime import date
from email import policy
from email.parser import Parser
import json
import pytest
from therapie_mcp.parsing import TherapieError, parse_profile
from therapie_mcp.workflow import Store, draft_enquiry, export_email
from therapie_mcp.matching import compare

@pytest.fixture
def store(tmp_path, profile_html):
    db = Store(tmp_path / 'private/workflow.sqlite3')
    db.save_therapist(parse_profile(profile_html, 'https://www.therapie.de/profil/test.person/'))
    try:
        yield db
    finally:
        db.close()


def test_private_permissions_and_preferences(store):
    assert store.path.stat().st_mode & 0o777 == 0o600
    assert store.path.parent.stat().st_mode & 0o777 == 0o700
    for suffix in ('-wal', '-shm'):
        assert store.path.with_name(store.path.name + suffix).stat().st_mode & 0o777 == 0o600
    store.update_preferences({'sender_name': 'Example User', 'sender_email': 'user@example.org', 'insurance': 'GKV'})
    assert store.preferences()['insurance'] == 'GKV'
    store.update_preferences({'insurance': None})
    assert 'insurance' not in store.preferences()
    with pytest.raises(TherapieError):
        store.update_preferences({'unknown': 'private'})


def test_enquiry_uses_only_supplied_details_and_does_not_record_contact(store):
    store.update_preferences({'sender_name': 'Example User', 'sender_email': 'user@example.org', 'insurance': 'gesetzlich versichert'})
    draft = draft_enquiry(store, 'test.person', additional_context='Termine sind am Dienstag möglich.')
    assert draft['recipient'] == 'test@example.org'
    assert 'Example User' in draft['body']
    assert 'gesetzlich versichert' in draft['body']
    assert 'Dienstag' in draft['body']
    assert store.therapist('test.person')['contacts'] == []
    assert store.therapist('test.person')['status'] == 'shortlisted'
    exported = export_email(draft)
    message = Parser(policy=policy.default).parsestr(exported['eml'])
    assert message['To'] == 'test@example.org'
    assert message['From'] == 'user@example.org'
    assert message['X-Unsent'] == '1'
    assert message.get_content().replace('\r\n', '\n').strip() == draft['body'].strip()
    assert exported['mailto_url'].startswith('mailto:test@example.org?')
    assert store.therapist('test.person')['contacts'] == []


def test_edit_export_and_missing_sender(store):
    draft = draft_enquiry(store, 'test.person', language='en')
    assert '[Your name]' in draft['body']
    edited = store.update_draft(draft['id'], subject='Updated enquiry', body='An edited message', recipient='other@example.org')
    message = Parser(policy=policy.default).parsestr(export_email(edited)['eml'])
    assert message['To'] == 'other@example.org'
    assert message['Subject'] == 'Updated enquiry'
    assert message['From'] is None


def test_follow_up_requires_actual_contact_and_can_be_resolved(store):
    with pytest.raises(TherapieError, match='earlier enquiry'):
        draft_enquiry(store, 'test.person', kind='follow_up')
    contact = store.log_contact('test.person', 'email', 'enquiry', follow_up_on=date.today().isoformat())
    assert len(store.overview()['follow_ups_due']) == 1
    assert draft_enquiry(store, 'test.person', kind='follow_up')['id']
    store.complete_follow_up(contact['id'])
    assert store.overview()['follow_ups_due'] == []


def test_shortlist_refresh_preserves_notes_and_status(store):
    store.update_therapist('test.person', status='waiting', notes='Private note')
    profile = store.therapist('test.person')['profile']
    store.save_therapist(profile)
    assert store.therapist('test.person')['notes'] == 'Private note'
    assert store.therapist('test.person')['status'] == 'waiting'
    store.save_therapist(profile, '')
    assert store.therapist('test.person')['notes'] == ''


def test_delete_cascades_private_data(store):
    draft = draft_enquiry(store, 'test.person')
    store.log_contact('test.person', 'phone', 'note')
    store.delete_therapist('test.person')
    assert store.shortlist() == []
    assert store.overview()['drafts'] == []
    with pytest.raises(TherapieError):
        store.draft(draft['id'])

@pytest.mark.parametrize('email', ['test@example.org\r\nBcc: attacker@example.org', 'a@example.org,b@example.org', 'not-an-email'])
def test_email_header_injection_rejected(store, email):
    with pytest.raises(TherapieError):
        draft_enquiry(store, 'test.person', recipient=email)


def test_subject_injection_rejected(store):
    draft = draft_enquiry(store, 'test.person')
    with pytest.raises(TherapieError):
        store.update_draft(draft['id'], subject='hello\nBcc: other@example.org')


def test_matching_is_explicit_and_distinguishes_unknown(store):
    profile = store.therapist('test.person')['profile']
    result = compare([profile], {'billing': ['GKV: Kassenleistung'], 'methods': ['Verhaltenstherapie'], 'languages': ['Englisch']}, require_approbation=True)
    checks = result['comparisons'][0]['checks']
    assert [check['result'] for check in checks] == ['match', 'match', 'match', 'match']
    assert result['comparisons'][0]['all_requirements_listed']
    profile['billing'] = ['Gesetzliche Krankenversicherung im Kostenerstattungsverfahren']
    profile['languages'] = []
    result = compare([profile], {'billing': ['GKV: Kassenleistung'], 'languages': ['Englisch']})
    assert [check['result'] for check in result['comparisons'][0]['checks']] == ['not_listed', 'unknown']
