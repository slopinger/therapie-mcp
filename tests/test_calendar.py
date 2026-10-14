import pytest
from therapie_mcp.calendar_export import appointment_times, calendar_export
from therapie_mcp.parsing import TherapieError
from therapie_mcp.workflow import Store


def test_utc_conversion_and_dst():
    start, end = appointment_times('2026-10-20T14:30', 50, 'Europe/Berlin')
    assert start == '2026-10-20T12:30:00+00:00'
    assert end == '2026-10-20T13:20:00+00:00'
    for when in ('2026-03-29T02:30', '2026-10-25T02:30'):
        with pytest.raises(TherapieError):
            appointment_times(when, 50, 'Europe/Berlin')
    assert appointment_times('2026-10-25T02:30+01:00', 50, 'Europe/Berlin')[0] == '2026-10-25T01:30:00+00:00'


def test_calendar_lifecycle_and_text_safety(tmp_path):
    db = Store(tmp_path / 'workflow.sqlite3')
    try:
        db.save_therapist({'profile_id': 'example', 'name': 'Example Practice', 'source_url': 'https://www.therapie.de/profil/example/'})
        appointment = db.record_appointment('example', '2026-10-20T14:30', title='Ä' * 90, notes='note\nEND:VEVENT\nATTENDEE:bad@example.org')
        exported = calendar_export(appointment)['ics']
        assert 'DTSTART:20261020T123000Z' in exported
        assert '\r\nATTENDEE:' not in exported
        assert 'CLASS:PRIVATE' in exported
        assert all(len(line.encode('utf-8')) <= 75 for line in exported.split('\r\n'))
        assert db.overview()['appointments'][0]['id'] == appointment['id']
        updated = db.update_appointment(appointment['id'], status='cancelled')
        assert updated['revision'] == 1
        assert db.appointments() == []
        assert len(db.appointments(include_cancelled=True)) == 1
        cancelled = calendar_export(updated)['ics']
        assert f"UID:{appointment['id']}@therapie-mcp.local" in cancelled
        assert 'STATUS:CANCELLED' in cancelled
        db.delete_therapist('example')
        assert db.appointments(include_cancelled=True) == []
    finally:
        db.close()
