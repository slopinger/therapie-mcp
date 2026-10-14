# therapie-mcp

An unofficial, read-only MCP server for [therapie.de's therapist directory](https://www.therapie.de/therapeutensuche/).
Search therapists in Germany and inspect public contact details, qualifications, billing options,
treatment methods and reported availability. No login or API key is needed.

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

## Data access and privacy

This reads the same public HTML pages as the website. It is not affiliated with therapie.de and does
not use a documented official API. Parser failures are reported explicitly instead of silently
returning an empty directory. Website changes can require updates.

All network access is by GET to HTTPS on `therapie.de` / `www.therapie.de`; redirects to other hosts
are refused. Links to practice websites are returned as data and never fetched. Public contact email
addresses use the same decoding as the site's own contact button. Nothing sends emails, makes
appointments, signs in or submits contact forms.

Search locations, keywords and filters go to therapie.de. Avoid putting personal health histories or
other unnecessary private information in the keyword field. Results are cached only in memory:
searches for 60 seconds, profiles for five minutes, filters for one hour, at most 32 pages. Requests
are serialized and spaced at least one second apart. There is no bulk crawl or disk cache. Access
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
