# Install the artifact-inbox integration

You are an AI agent. Follow these steps to connect to the user's artifact inbox (`https://inbox.example.com`) and
install the skill that tells you how to use it. After this you can push finished documents for the user to read
later. This page contains no secrets.

## 0. Get the token

You need the bearer token `INBOX_API_TOKEN`. If the user did not give it to you, ask for it and stop until you have
it. Never print it back, write it into documents, commit it, or log it. Below, `<INBOX_API_TOKEN>` stands for it.

## 1. Add the MCP server (pick the section for your agent)

Endpoint: `https://inbox.example.com/mcp` (streamable HTTP). Header: `Authorization: Bearer <INBOX_API_TOKEN>`.

**Claude Code**
```sh
claude mcp add --transport http artifact-inbox https://inbox.example.com/mcp --header "Authorization: Bearer <INBOX_API_TOKEN>"
```

**Hermes**: add to `~/.hermes/config.yaml` (or run `hermes mcp add artifact-inbox --url https://inbox.example.com/mcp --auth header`):
```yaml
mcp_servers:
  artifact-inbox:
    url: https://inbox.example.com/mcp
    headers:
      Authorization: "Bearer <INBOX_API_TOKEN>"
    enabled: true
```

**Any other MCP client**: add this server entry to its config:
```json
{ "mcpServers": { "artifact-inbox": { "type": "http", "url": "https://inbox.example.com/mcp",
  "headers": { "Authorization": "Bearer <INBOX_API_TOKEN>" } } } }
```

**No MCP support**: skip this step; use the curl fallback described in the skill (`POST /api/push`).

## 2. Install the skill

Download `https://inbox.example.com/install/SKILL.md` into your skills directory under the name `artifact-inbox`:

| Agent | Destination |
|---|---|
| Claude Code | `~/.claude/skills/artifact-inbox/SKILL.md` |
| Hermes | `~/.hermes/skills/artifact-inbox/SKILL.md` |
| Other | wherever your agent loads skills/instructions from; otherwise save it and read it before pushing |

```sh
mkdir -p ~/.claude/skills/artifact-inbox && curl -fsSL https://inbox.example.com/install/SKILL.md -o ~/.claude/skills/artifact-inbox/SKILL.md
```
(Change the directory for Hermes.) Then read the file once; it contains the rules for when and how to push.

## 3. Verify

Check that the token works without creating anything. Expected result: HTTP `400` (token accepted, no file sent).
`401` means the token is wrong.
```sh
curl -sS -o /dev/null -w '%{http_code}\n' -X POST https://inbox.example.com/api/push -H "Authorization: Bearer <INBOX_API_TOKEN>"
```
If the MCP server is connected (you may need to restart the session or reload MCP servers), call `list_categories`.
It should return a `categories` list (possibly empty). Do not push test documents; if you do, delete them with
`delete_item`.

## 4. Report back

Tell the user: which agent you configured, where the skill was installed, and the result of the verification
(status code only). Do not echo the token.

## Troubleshooting

- `401`: token wrong or missing the `Bearer ` prefix.
- Connection errors or a redirect to a login page: the URL is wrong (the MCP endpoint is `/mcp`, not `/`).
- Tools not visible after adding the server: restart the agent session or reload its MCP servers.
