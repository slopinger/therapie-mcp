"""Private calendar export for user-recorded appointments; never books a visit."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from .parsing import TherapieError


def appointment_times(starts_at: str, duration_minutes: int, zone_name: str) -> tuple[str, str]:
    if type(duration_minutes) is not int or not 1 <= duration_minutes <= 480:
        raise TherapieError('Appointment duration must be 1–480 minutes.')
    try:
        zone = ZoneInfo(zone_name)
        if 'T' not in starts_at and ' ' not in starts_at:
            raise ValueError('time missing')
        parsed = datetime.fromisoformat(starts_at)
    except (ValueError, ZoneInfoNotFoundError) as error:
        raise TherapieError('Use an ISO date and time and a valid IANA timezone, e.g. 2026-10-20T14:30 and Europe/Berlin.') from error
    if parsed.tzinfo is None:
        candidates = {}
        for fold in (0, 1):
            aware = parsed.replace(tzinfo=zone, fold=fold)
            utc = aware.astimezone(timezone.utc)
            if utc.astimezone(zone).replace(tzinfo=None) == parsed:
                candidates[utc] = aware
        if not candidates:
            raise TherapieError('That local time does not exist during the daylight-saving transition.')
        if len(candidates) > 1:
            raise TherapieError('That local time is ambiguous during the daylight-saving transition; include an explicit UTC offset.')
        start = next(iter(candidates))
    else:
        start = parsed.astimezone(timezone.utc)
    return start.isoformat(), (start + timedelta(minutes=duration_minutes)).isoformat()


def escaped(value: str) -> str:
    value = value.replace('\r\n', '\n').replace('\r', '\n')
    return value.replace('\\', '\\\\').replace('\n', '\\n').replace(';', '\\;').replace(',', '\\,')


def folded(line: str) -> str:
    # RFC 5545: 75 octets per physical line, without splitting UTF-8 characters.
    chunks, current, length = [], '', 0
    for char in line:
        size = len(char.encode('utf-8'))
        if length + size > 75:
            chunks.append(current)
            current, length = ' ', 1
        current += char
        length += size
    chunks.append(current)
    return '\r\n'.join(chunks)


def calendar_export(appointment: dict) -> dict:
    def timestamp(value):
        return datetime.fromisoformat(value).astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//slop//therapie-mcp//EN',
             'CALSCALE:GREGORIAN', 'METHOD:PUBLISH', 'BEGIN:VEVENT',
             f"UID:{appointment['id']}@therapie-mcp.local", f"SEQUENCE:{appointment['revision']}",
             'DTSTAMP:' + timestamp(appointment['updated_at']),
             'DTSTART:' + timestamp(appointment['starts_at']), 'DTEND:' + timestamp(appointment['ends_at']),
             'SUMMARY:' + escaped(appointment['title']), 'LOCATION:' + escaped(appointment['location']),
             'DESCRIPTION:' + escaped(appointment['notes']), 'CLASS:PRIVATE',
             'STATUS:' + ('CANCELLED' if appointment['status'] == 'cancelled' else 'CONFIRMED'),
             'END:VEVENT', 'END:VCALENDAR']
    return {'appointment_id': appointment['id'], 'filename': f"appointment-{appointment['id']}.ics",
            'mime_type': 'text/calendar', 'ics': '\r\n'.join(folded(line) for line in lines) + '\r\n',
            'note': 'Private calendar data for manual import. This records your appointment; it does not book, invite or contact the practice.'}
