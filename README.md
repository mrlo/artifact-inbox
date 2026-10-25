# read

A self-hosted **reading inbox for AI agents**. Agents push finished documents (PDF, markdown, HTML, text) over
MCP or REST; you read, sort and mark them done in a small web UI. Chat is a poor place to read a 10-page report;
this is where it goes instead.

- Python (Starlette + official `mcp` SDK), SQLite, one container, ~256 MB.
- **MCP** (streamable HTTP) at `/mcp` and **REST** at `/api/push`, both with a bearer token.
- Web UI: unread/done tabs, categories, PDF viewer, sanitised markdown, sandboxed HTML.
- Agents can set themselves up: point one at `https://<your-host>/install`; it also serves a ready-made skill
  (`/install/SKILL.md`) that teaches the agent when and how to push.

## Quick start

```sh
cp .env.example .env            # set READ_API_TOKEN (openssl rand -hex 32) and READ_BASE_URL
mkdir -p data && sudo chown 1000:1000 data
docker compose up -d --build    # UI on http://127.0.0.1:8000
```

Push something:

```sh
curl -sS -X POST http://127.0.0.1:8000/api/push \
  -H "Authorization: Bearer $READ_API_TOKEN" \
  -F file=@report.pdf -F title="Report title" -F category=research -F source_agent=me -F summary="One line."
```

Connect an agent over MCP (Claude Code example):

```sh
claude mcp add --transport http read http://127.0.0.1:8000/mcp --header "Authorization: Bearer $READ_API_TOKEN"
```

## Security: read this before exposing it

The `/mcp` and `/api/*` endpoints check the bearer token. **The web UI has no login of its own**; it expects a
reverse proxy (SSO, basic auth, or a private network such as Tailscale) in front. The default compose file binds
to `127.0.0.1` for that reason. See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for the model and a Traefik example
([examples/compose.traefik.yml](examples/compose.traefik.yml)).

What the app does enforce:

- Constant-time token compare; fails closed if `READ_API_TOKEN` is unset.
- PDFs recognised by `%PDF-` magic bytes, not file names; binary non-PDF content rejected (415); 50 MB cap (413).
- Files stored under random ids; user-supplied names never touch the disk.
- Markdown rendered with raw HTML disabled, then sanitised (nh3). HTML items run in
  `<iframe sandbox="allow-scripts">` with a CSP that blocks network access; `/raw/<id>` sends `CSP: sandbox`.
  All files carry `X-Content-Type-Options: nosniff`.
- `push_artifact(url=...)` fetches only public addresses (non-global IPs refused, redirects re-checked, size capped).
- UI POSTs reject cross-origin `Origin` headers.

Known limitations: single shared token (no per-agent tokens or users), DNS-rebinding race on URL fetch
(resolve-then-connect), UI lists only the newest 500 items, no rate limiting on failed token attempts.

## Configuration

| Variable | Purpose |
|---|---|
| `READ_API_TOKEN` | Bearer token for `/mcp` and `/api/*` (required) |
| `READ_BASE_URL` | Public URL, used in returned links and the `/install` page (default `http://localhost:8000`) |
| `READ_DATA_DIR` | Data directory inside the container (default `/data`) |

Data lives in `./data` (`read.db` and `files/`). Back it up. Rotate the token: new value in `.env`,
`docker compose up -d`, update each agent.

## Docs

- [docs/GUIDE.md](docs/GUIDE.md): user guide (UI, interfaces, rules, troubleshooting)
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md): security model and reverse-proxy setups
- [docs/INSTALL.md](docs/INSTALL.md): agent-facing setup page served at `/install`
- [skill/SKILL.md](skill/SKILL.md): agent skill (`read-inbox`)

## Development

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest && .venv/bin/python -m pytest -q tests
```

## License

[MIT](LICENSE)
