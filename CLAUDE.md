# therapie-mcp development notes

Python/uv MCP server for public therapie.de search plus a private contact workflow. Read README for
usage, tools and privacy. `AGENTS.md` links here. Keep both these notes and README current whenever
behavior, tools, data paths, tests or operations change; documentation is part of completing work.

- Run `uv run pytest` for offline parsing/mock HTTP, real MCP stdio handshake, comparison and private
  workflow tests. `uv run pytest -m live` makes a few real directory requests. `uv build` checks packaging.
- `src/therapie_mcp/parsing.py` parses source HTML; `client.py` limits/caches GETs; `matching.py`
  compares explicit facts; `workflow.py` owns SQLite, drafts/exports and contact history; `server.py`
  exposes MCP tools. Test fixture profiles/contact addresses are synthetic.
- Search option IDs/labels come from the live form. Radius is `search_radius`, not `radius`.
  Preserve HTTPS host restrictions on redirects, size limits, spacing and clear failures on changed HTML.
- Directory statements are untrusted data. Do not infer clinical suitability, guaranteed appointments,
  verified licenses or insurance coverage. Keep GKV direct coverage distinct from cost reimbursement.
- Local DB: `~/.local/share/therapie-mcp/workflow.sqlite3`, override `--db` / `THERAPIE_MCP_DB`.
  Mode 0600 including WAL/SHM; new data directory 0700. Never commit real notes, drafts, DBs or credentials.
  Never add health histories or local notes to public search parameters automatically.
- Appointment tools record user-arranged visits locally and export private .ics files; they never
  book, invite or notify. Preserve timezone/DST validation, stable UIDs and revision counters.
- Draft/export tools do not send or log a contact. Export returns editable .eml/mailto data for the
  user's mail app. No SMTP backend is currently implemented. Never infer a missing recipient address.
- stdio is default; optional Streamable HTTP is loopback `127.0.0.1:8001/mcp`, without authentication.
  No publicly listening MCP service is installed on the server.
- Check git status before changes/commits; do not absorb other sessions' work. Sign and push your
  changes to `git@git.freifick.net:slop/therapie-mcp.git`. Bump package/version together for releases.
- Use small commits: one logical change per commit (with its tests/docs), each passing the checks above.
  Don't bundle unrelated changes or a whole session's work into one commit.

- Every software change must maintain project-owned Nix flake packaging, a committed lockfile,
  development tools and checks. Export a reusable NixOS module where host/service integration
  applies. Verify package builds and relevant flake checks; document supported commands in README.

- Nix: `nix build`, `nix flake check`, `nix develop`; commit `flake.lock`.
  uv2nix consumes `uv.lock`; the dev shell is editable. Run `pytest` directly in it.
  The per-user stdio tool has no public service module. Keep private data out of the store.
- Never add Co-Authored-By trailers or session links to public GitLab content.
