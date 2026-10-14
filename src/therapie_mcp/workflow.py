"""Private local shortlist, contact history and editable email drafts."""
from __future__ import annotations

from datetime import date, datetime, timezone
from email import policy
from email.message import EmailMessage
from email.utils import parseaddr
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
from typing import Any
from urllib.parse import quote, urlencode
from uuid import uuid4

from .parsing import TherapieError

PREFERENCE_FIELDS = {'sender_name', 'sender_email', 'sender_phone', 'insurance', 'city', 'preferred_language'}
STATUSES = {'shortlisted', 'contacted', 'waiting', 'appointment', 'not_available', 'declined', 'archived'}
CHANNELS = {'email', 'phone', 'web', 'in_person'}
OUTCOMES = {'enquiry', 'follow_up', 'reply', 'waitlist', 'appointment', 'unavailable', 'declined', 'note'}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def email_address(value: str) -> str:
    value = value.strip()
    if '\r' in value or '\n' in value or parseaddr(value)[1] != value or not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+', value):
        raise TherapieError('Provide one plain email address without display names or line breaks.')
    return value


def iso_date(value: str | None) -> str | None:
    if value is None or value == '':
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as error:
        raise TherapieError('Use an ISO date: YYYY-MM-DD.') from error


class Store:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or os.environ.get('THERAPIE_MCP_DB', '~/.local/share/therapie-mcp/workflow.sqlite3')).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.is_symlink():
            raise TherapieError('The workflow database must not be a symbolic link.')
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            if self.path.stat().st_uid != os.getuid():
                raise TherapieError('The workflow database must belong to the current user.')
        else:
            os.close(descriptor)
        self.path.chmod(0o600)
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript('''
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            PRAGMA busy_timeout=5000;
            CREATE TABLE IF NOT EXISTS preferences(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS shortlist(
                profile_id TEXT PRIMARY KEY, snapshot TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'shortlisted', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS drafts(
                id TEXT PRIMARY KEY, profile_id TEXT NOT NULL REFERENCES shortlist(profile_id) ON DELETE CASCADE,
                recipient TEXT NOT NULL, sender TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS contacts(
                id TEXT PRIMARY KEY, profile_id TEXT NOT NULL REFERENCES shortlist(profile_id) ON DELETE CASCADE,
                channel TEXT NOT NULL, outcome TEXT NOT NULL, occurred_on TEXT NOT NULL,
                notes TEXT NOT NULL, follow_up_on TEXT, created_at TEXT NOT NULL);
        ''')

    def close(self) -> None:
        with self.lock:
            self.conn.close()

    def preferences(self) -> dict[str, str]:
        with self.lock:
            return dict(self.conn.execute('SELECT key,value FROM preferences'))

    def update_preferences(self, fields: dict[str, str | None]) -> dict[str, str]:
        if set(fields) - PREFERENCE_FIELDS:
            raise TherapieError('Allowed preference fields: ' + ', '.join(sorted(PREFERENCE_FIELDS)))
        for key, value in fields.items():
            if value is not None and (not isinstance(value, str) or len(value) > 300 or '\n' in value or '\r' in value):
                raise TherapieError('Preferences must be single-line strings of at most 300 characters, or null to remove.')
            if key == 'sender_email' and value:
                email_address(value)
        with self.lock:
            for key, value in fields.items():
                if value is None:
                    self.conn.execute('DELETE FROM preferences WHERE key=?', (key,))
                else:
                    self.conn.execute('INSERT INTO preferences VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, value.strip()))
        return self.preferences()

    def save_therapist(self, profile: dict[str, Any], notes: str | None = None) -> dict[str, Any]:
        if notes is not None and len(notes) > 10000:
            raise TherapieError('Shortlist notes must be at most 10000 characters.')
        timestamp = now()
        with self.lock:
            self.conn.execute('''INSERT INTO shortlist(profile_id,snapshot,notes,created_at,updated_at) VALUES (?,?,?,?,?)
                ON CONFLICT(profile_id) DO UPDATE SET snapshot=excluded.snapshot, notes=COALESCE(?,shortlist.notes),updated_at=excluded.updated_at''',
                (profile['profile_id'], json.dumps(profile), notes or '', timestamp, timestamp, notes))
        return self.therapist(profile['profile_id'])

    def therapist(self, profile_id: str) -> dict[str, Any]:
        with self.lock:
            row = self.conn.execute('SELECT * FROM shortlist WHERE profile_id=?', (profile_id,)).fetchone()
            if row is None:
                raise TherapieError('Therapist is not in the local shortlist. Use save_therapist first.')
            result = dict(row)
            result['profile'] = json.loads(result.pop('snapshot'))
            result['contacts'] = [dict(contact) for contact in self.conn.execute('SELECT * FROM contacts WHERE profile_id=? ORDER BY occurred_on DESC,created_at DESC', (profile_id,))]
            return result

    def shortlist(self, status: str | None = None) -> list[dict[str, Any]]:
        if status is not None and status not in STATUSES:
            raise TherapieError('Unknown shortlist status.')
        with self.lock:
            query = 'SELECT profile_id FROM shortlist' + (' WHERE status=?' if status else '') + ' ORDER BY updated_at DESC'
            ids = [row[0] for row in self.conn.execute(query, (status,) if status else ())]
            return [self.therapist(identifier) for identifier in ids]

    def update_therapist(self, profile_id: str, status: str | None = None, notes: str | None = None) -> dict[str, Any]:
        self.therapist(profile_id)
        if status is not None and status not in STATUSES:
            raise TherapieError('Unknown shortlist status.')
        if notes is not None and len(notes) > 10000:
            raise TherapieError('Shortlist notes must be at most 10000 characters.')
        with self.lock:
            self.conn.execute('UPDATE shortlist SET status=COALESCE(?,status),notes=COALESCE(?,notes),updated_at=? WHERE profile_id=?', (status, notes, now(), profile_id))
        return self.therapist(profile_id)

    def delete_therapist(self, profile_id: str) -> dict[str, Any]:
        with self.lock:
            deleted = self.conn.execute('DELETE FROM shortlist WHERE profile_id=?', (profile_id,)).rowcount
        return {'deleted': bool(deleted), 'profile_id': profile_id, 'includes': 'local notes, drafts and contact history'}

    def log_contact(self, profile_id: str, channel: str, outcome: str, occurred_on: str | None = None,
                    notes: str = '', follow_up_on: str | None = None) -> dict[str, Any]:
        self.therapist(profile_id)
        if channel not in CHANNELS or outcome not in OUTCOMES:
            raise TherapieError('Unknown contact channel or outcome.')
        if len(notes) > 10000:
            raise TherapieError('Contact notes must be at most 10000 characters.')
        record = {'id': uuid4().hex, 'profile_id': profile_id, 'channel': channel, 'outcome': outcome,
                  'occurred_on': iso_date(occurred_on) or date.today().isoformat(), 'notes': notes,
                  'follow_up_on': iso_date(follow_up_on), 'created_at': now()}
        with self.lock:
            self.conn.execute('INSERT INTO contacts VALUES (:id,:profile_id,:channel,:outcome,:occurred_on,:notes,:follow_up_on,:created_at)', record)
        return record

    def draft(self, identifier: str) -> dict[str, Any]:
        with self.lock:
            row = self.conn.execute('SELECT * FROM drafts WHERE id=?', (identifier,)).fetchone()
        if row is None:
            raise TherapieError('Email draft was not found.')
        return dict(row)

    def save_draft(self, profile_id: str, recipient: str, sender: str, subject: str, body: str) -> dict[str, Any]:
        self.therapist(profile_id)
        recipient = email_address(recipient)
        if sender:
            sender = email_address(sender)
        self.validate_message(subject, body)
        identifier, timestamp = uuid4().hex, now()
        with self.lock:
            self.conn.execute('INSERT INTO drafts VALUES (?,?,?,?,?,?,?,?)', (identifier, profile_id, recipient, sender, subject, body, timestamp, timestamp))
        return self.draft(identifier)

    @staticmethod
    def validate_message(subject: str, body: str) -> None:
        if not subject.strip() or len(subject) > 200 or '\r' in subject or '\n' in subject:
            raise TherapieError('Subject must be a non-empty single line of at most 200 characters.')
        if not body.strip() or len(body) > 20000:
            raise TherapieError('Email body must be between 1 and 20000 characters.')

    def update_draft(self, identifier: str, subject: str | None = None, body: str | None = None,
                     recipient: str | None = None) -> dict[str, Any]:
        draft = self.draft(identifier)
        subject = draft['subject'] if subject is None else subject
        body = draft['body'] if body is None else body
        recipient = draft['recipient'] if recipient is None else email_address(recipient)
        self.validate_message(subject, body)
        with self.lock:
            self.conn.execute('UPDATE drafts SET subject=?,body=?,recipient=?,updated_at=? WHERE id=?', (subject, body, recipient, now(), identifier))
        return self.draft(identifier)

    def complete_follow_up(self, contact_id: str) -> dict[str, Any]:
        with self.lock:
            updated = self.conn.execute('UPDATE contacts SET follow_up_on=NULL WHERE id=?', (contact_id,)).rowcount
        if not updated:
            raise TherapieError('Contact record was not found.')
        return {'contact_id': contact_id, 'follow_up_completed': True}

    def overview(self) -> dict[str, Any]:
        with self.lock:
            due = [dict(row) for row in self.conn.execute('''SELECT c.* FROM contacts c JOIN shortlist s ON s.profile_id=c.profile_id
                WHERE c.follow_up_on <= ? AND s.status NOT IN ('archived','declined','not_available','appointment')
                ORDER BY c.follow_up_on''', (date.today().isoformat(),))]
            return {'preferences': self.preferences(), 'shortlist': self.shortlist(), 'follow_ups_due': due,
                    'drafts': [dict(row) for row in self.conn.execute('SELECT id,profile_id,recipient,subject,updated_at FROM drafts ORDER BY updated_at DESC')]}


def draft_enquiry(store: Store, profile_id: str, *, kind: str = 'initial', language: str = 'de',
                  recipient: str | None = None, additional_context: str = '') -> dict[str, Any]:
    if kind not in {'initial', 'follow_up', 'waitlist'} or language not in {'de', 'en'}:
        raise TherapieError('Use initial, follow_up or waitlist and language de or en.')
    if len(additional_context) > 6000:
        raise TherapieError('Additional context must be at most 6000 characters.')
    saved = store.therapist(profile_id)
    profile, prefs = saved['profile'], store.preferences()
    recipient = recipient or profile.get('email')
    if not recipient:
        raise TherapieError('No public email address is listed. Supply a verified recipient or use the profile phone/contact website.')
    if kind == 'follow_up' and not any(contact['outcome'] in {'enquiry', 'follow_up'} for contact in saved['contacts']):
        raise TherapieError('No earlier enquiry is recorded. Log the previous contact before drafting a follow-up.')
    name = prefs.get('sender_name') or ('[Ihr Name]' if language == 'de' else '[Your name]')
    insurance = prefs.get('insurance')
    if language == 'de':
        subject = {'initial': 'Anfrage nach einem psychotherapeutischen Erstgespräch', 'follow_up': 'Nachfrage zu meiner Therapieplatzanfrage', 'waitlist': 'Anfrage zur Warteliste für Psychotherapie'}[kind]
        request = {'initial': 'ich suche einen Psychotherapieplatz und möchte fragen, ob Sie derzeit eine psychotherapeutische Sprechstunde oder ein Erstgespräch anbieten.',
                   'follow_up': 'ich möchte freundlich nachfragen, ob Sie meine bisherige Anfrage erhalten haben und ob ein Erstgespräch möglich ist.',
                   'waitlist': 'ich möchte fragen, ob Sie eine Warteliste für einen Psychotherapieplatz führen und wie ich mich gegebenenfalls vormerken lassen kann.'}[kind]
        paragraphs = [f"Guten Tag {profile['name']},", request]
        if insurance:
            paragraphs.append(f'Meine Versicherung / gewünschte Abrechnung: {insurance}. Können Sie mir bitte mitteilen, ob und unter welchen Voraussetzungen eine Abrechnung bei Ihnen möglich ist?')
        paragraphs.append('Falls aktuell kein Platz frei ist, wäre ich auch für eine Information zur Wartezeit oder zu einer Warteliste dankbar.')
        closing = f'Vielen Dank für Ihre Rückmeldung.\n\nMit freundlichen Grüßen\n{name}'
    else:
        subject = {'initial': 'Enquiry about an initial psychotherapy appointment', 'follow_up': 'Following up on my psychotherapy enquiry', 'waitlist': 'Enquiry about your psychotherapy waiting list'}[kind]
        request = {'initial': 'I am looking for psychotherapy and would like to ask whether you currently offer an initial consultation.',
                   'follow_up': 'I would like to follow up on my earlier enquiry and ask whether an initial consultation might be possible.',
                   'waitlist': 'I would like to ask whether you keep a waiting list for psychotherapy and how I could join it.'}[kind]
        paragraphs = [f"Hello {profile['name']},", request]
        if insurance:
            paragraphs.append(f'My insurance / preferred billing arrangement is: {insurance}. Could you let me know whether and under what conditions this can be billed at your practice?')
        paragraphs.append('If no place is currently available, I would appreciate information about waiting times or a waiting list.')
        closing = f'Thank you for your reply.\n\nKind regards,\n{name}'
    if additional_context.strip():
        paragraphs.append(additional_context.strip())
    paragraphs.append(closing)
    if prefs.get('sender_phone'):
        paragraphs.append(prefs['sender_phone'])
    result = store.save_draft(profile_id, recipient, prefs.get('sender_email', ''), subject, '\n\n'.join(paragraphs))
    result['review_note'] = 'Draft only. Review recipient, personal details, billing and wording before sending. No contact was recorded.'
    return result


def export_email(draft: dict[str, Any]) -> dict[str, Any]:
    message = EmailMessage(policy=policy.SMTP)
    message['To'] = email_address(draft['recipient'])
    if draft['sender']:
        message['From'] = email_address(draft['sender'])
    message['Subject'] = draft['subject']
    message['X-Unsent'] = '1'
    message.set_content(draft['body'])
    mailto = 'mailto:' + quote(draft['recipient'], safe='@') + '?' + urlencode({'subject': draft['subject'], 'body': draft['body']}, quote_via=quote)
    return {'draft_id': draft['id'], 'filename': f"therapie-enquiry-{draft['id']}.eml", 'mime_type': 'message/rfc822',
            'eml': message.as_string(), 'mailto_url': mailto if len(mailto) <= 2000 else None,
            'note': 'Open the .eml content or mailto link in your mail app, review it, then send there. This export does not send or log a contact.'}
