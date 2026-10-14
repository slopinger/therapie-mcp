# therapie-mcp

An unofficial MCP server for [therapie.de's therapist directory](https://www.therapie.de/therapeutensuche/).
Search therapists in Germany and inspect public contact details, qualifications, billing options,
treatment methods and reported availability. No login or API key is needed. A private local workflow adds profile comparison, a shortlist, editable
email drafts, mail-app exports, contact history and follow-up dates.

## Run

With [uv](https://docs.astral.sh/uv/):

```sh
git clone https://git.freifick.net/slop/therapie-mcp.git
cd therapie-mcp
uv run therapie-mcp                    # MCP over stdio (default)
uv run therapie-mcp --version
```

Or run directly from the public repository:

```sh
uvx --from git+https://git.freifick.net/slop/therapie-mcp.git therapie-mcp
```

Claude Code:

```sh
claude mcp add therapie -- uv --directory /absolute/path/to/therapie-mcp run therapie-mcp
```

For MCP clients with a JSON server configuration:

```json
{
  "mcpServers": {
    "therapie": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/therapie-mcp", "run", "therapie-mcp"]
    }
  }
}
```

Optional Streamable HTTP transport, bound to loopback by default:

```sh
uv run therapie-mcp --transport streamable-http --host 127.0.0.1 --port 8001
```

The MCP endpoint is `http://127.0.0.1:8001/mcp`. The server provides no HTTP authentication;
keep it on loopback or behind your own authenticated gateway.

## Tools

| Tool | Returns |
| --- | --- |
| `get_search_filters` | Current option IDs and German labels for all seven filter categories |
| `search_therapists` | One page of listings, profile IDs/URLs, addresses, phone numbers, distances, total count and next-page URL |
| `get_therapist` | Public contact details, qualifications/billing, focuses, methods, audiences, availability, memberships and profile update date |

`search_therapists` requires `location` (town or postcode). Optional parameters:

- `radius_km`: 1–200 km; omitted uses the website's default radius. The response reports the actual radius.
- `focus`, `method`, `billing`, `audience`, `gender`, `language`, `availability`: an ID or exact German
  label from `get_search_filters`. IDs are resolved from the live search form rather than guessed.
- `keyword`: free-text directory keyword or therapist name.
- `page`: website page number, starting at 1. Request the next page when `next_page_url` is present.

For example:

```json
{
  "location": "Berlin",
  "radius_km": 25,
  "billing": "GKV: Kassenleistung",
  "method": "Verhaltenstherapie",
  "language": "Englisch",
  "availability": "Freie Plätze vorhanden"
}
```

Pass a returned `profile_id` or `/profil/.../` URL to `get_therapist`.
The `therapeutensuche` prompt helps a client collect search preferences and compare sourced listings.
Reported free places and billing are the directory's statements; confirm them with the practice.

## Find, compare and contact

1. `workflow_overview` shows your saved list, drafts and follow-ups. Use `update_preferences` to save
   sender name/email/phone, insurance, city and preferred language locally. `get_preferences` reads
   them; set a field to `null` to remove it.
2. Use the live search filters. `compare_therapists` fetches up to ten profiles and compares explicit
   `billing`, `methods`, `focuses`, `audiences`, `languages`, `availability` and optional approbation
   requirements. Alternatives within a field are OR; different fields are AND. This is a factual
   comparison, not a medical suitability or quality ranking. Missing information stays unknown.
   Statutory coverage and statutory cost reimbursement are kept distinct.
3. `save_therapist` stores a public profile snapshot plus private notes. `get_shortlist` lists saved
   entries and contact history; `update_saved_therapist` changes notes/status. Statuses are
   `shortlisted`, `contacted`, `waiting`, `appointment`, `not_available`, `declined`, `archived`.
   Refreshing a snapshot preserves existing notes/status unless you explicitly replace notes.
4. `draft_enquiry` prepares an initial enquiry, waiting-list request or follow-up in German/English.
   It uses local sender/insurance preferences and only additional health/context details you supply.
   A missing public email requires a verified recipient; no address is guessed. Follow-up drafts
   require a recorded earlier enquiry. `get_email_draft` reads a draft; `update_email_draft` edits
   its recipient, subject or body.
5. `export_email_draft` returns `.eml` content (with `X-Unsent: 1`) and a mailto link where its length
   permits. Save the returned text as the suggested `.eml` filename and open it in your mail app, or
   use the mailto link. Review and send there. The server does not connect to a mail provider.
6. `log_contact` records actual enquiries, calls, replies, waitlist outcomes or appointments, with
   optional `follow_up_on` dates. `complete_follow_up` resolves a reminder. Drafting/export never
   marks an email sent or invents a contact. `workflow_overview` lists reminders due today or earlier.
7. `delete_saved_therapist` removes that entry and its local notes, drafts and contact history.

Example comparison requirements:

```json
{
  "profiles": ["profile.id.from.search"],
  "requirements": {
    "billing": ["GKV: Kassenleistung"],
    "methods": ["Verhaltenstherapie"],
    "languages": ["Englisch"]
  },
  "require_approbation": true
}
```

The local SQLite database defaults to `~/.local/share/therapie-mcp/workflow.sqlite3` (file 0600,
new containing directory 0700). Override with `--db PATH` or `THERAPIE_MCP_DB`. Notes and draft bodies
can contain private information; they remain on the machine running the MCP server and are returned
only through its tools. Public searches never automatically include these notes. Local deletion
removes records, not a promise of forensic erasure from SQLite journals or filesystem backups.

## Appointment records and calendar export

`record_appointment` stores an appointment you have arranged, using an ISO date/time, duration and
IANA timezone (default Europe/Berlin). `list_appointments` lists records; `update_appointment`
reschedules or marks them completed/cancelled. Nothing books a visit or notifies the practice.
`export_appointment` returns private `.ics` content for manual calendar import, with a stable UID,
revision counter and UTC event times. The default title is simply “Termin”. Daylight-saving gaps
are rejected; ambiguous local times require an explicit offset. Deleting a saved therapist also
removes its appointment records. Back up the private workflow database if you need to preserve them.

## Data access and privacy

The public-data tools read the same HTML pages as the website. It is not affiliated with therapie.de and does
not use a documented official API. Parser failures are reported explicitly instead of silently
returning an empty directory. Website changes can require updates.

All network access is by GET to HTTPS on `therapie.de` / `www.therapie.de`; redirects to other hosts
are refused. Links to practice websites are returned as data and never fetched. Public contact email
addresses use the same decoding as the site's own contact button. Email tools create drafts/exports locally. Nothing sends emails, makes
appointments, signs in or submits contact forms.

Search locations, keywords and filters go to therapie.de. Avoid putting personal health histories or
other unnecessary private information in the keyword field. Public directory results are cached only in memory:
searches for 60 seconds, profiles for five minutes, filters for one hour, at most 32 pages. Requests
are serialized and spaced at least one second apart. There is no bulk crawl or public-page disk cache; only explicitly saved shortlist snapshots persist in the private workflow database. Access
refusals and rate limits are surfaced without attempts to bypass them.

Each response includes `source_url` and `retrieved_at`; profiles also include the site's update date
when available. Source text is untrusted content, not instructions for an MCP client.

## Tests

```sh
uv sync
uv run pytest                    # offline fixtures, mock HTTP, tool schemas and real stdio handshake
uv run pytest -m live             # a few real directory requests
uv build                         # wheel and source distribution
```

Fixtures use synthetic therapist details. Live tests check current filters, a filtered radius search
and one result profile; they do not assert unstable result counts or copy profile content into the repo.

MIT license. Source: https://git.freifick.net/slop/therapie-mcp.
