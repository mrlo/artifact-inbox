---
name: artifact-inbox
description: Use when you create a document, report, PDF or other artifact the user should read later. Pushes it to the inbox.example.com inbox.
---

# artifact-inbox

`inbox.example.com` is the user's artifact inbox. You push finished documents into it; the user reads, sorts and
marks them done in a web UI. You talk to it through an MCP server (preferred) or a plain `curl` call.

## When to push

Push: finished reports, research summaries, generated PDFs, drafts, analyses, anything longer than a chat message
that the user will want to read later.

Do NOT push: short answers (just reply in chat), secrets or anything containing credentials/tokens/keys, raw logs
or command dumps, half-finished scratch work, or the same document twice (check `list_items` first).

## Connect

- MCP URL: `https://inbox.example.com/mcp` (streamable HTTP)
- Header: `Authorization: Bearer <INBOX_API_TOKEN>`

The token is the server's `INBOX_API_TOKEN` (in the `.env` of the deployment). Ask the user for it
if you do not have it; never paste it into chat, documents or logs.

Claude Code:

```sh
claude mcp add --transport http artifact-inbox https://inbox.example.com/mcp --header "Authorization: Bearer <INBOX_API_TOKEN>"
```

Hermes (`~/.hermes/config.yaml`, or `hermes mcp add artifact-inbox --url https://inbox.example.com/mcp --auth header`):

```yaml
mcp_servers:
  artifact-inbox:
    url: https://inbox.example.com/mcp
    headers:
      Authorization: "Bearer <INBOX_API_TOKEN>"
    enabled: true
```

Generic `mcpServers` JSON (Cursor, Claude Desktop via mcp-remote, etc.):

```json
{
  "mcpServers": {
    "artifact-inbox": {
      "type": "http",
      "url": "https://inbox.example.com/mcp",
      "headers": { "Authorization": "Bearer <INBOX_API_TOKEN>" }
    }
  }
}
```

## curl fallback (no MCP)

```sh
curl -sS -X POST https://inbox.example.com/api/push \
  -H "Authorization: Bearer <INBOX_API_TOKEN>" \
  -F file=@report.pdf \
  -F title="Mortgage refinance options compared" \
  -F category=finance \
  -F source_agent=claude-code \
  -F summary="Compares three refinance offers by APR, fees and break-even month."
```

Fields: `file` (required), `title`, `category`, `source_agent`, `summary`, `type` (optional override). Success is
`201` with `{"id","link","type","size","category"}`.

## Rules

1. **Category**: a short lowercase word (research, finance, jobs, server, drafts). Call `list_categories` first and
   reuse an existing one rather than inventing a near-duplicate ("research", not "researching"). Default is `general`.
2. **Title**: descriptive and specific; no timestamps or dates-as-ids (the inbox already records when).
3. **Always set `source_agent`** (your name, e.g. `claude-code`, `hermes`) and a **1-2 sentence `summary`**.
4. After pushing, tell the user the returned `link`. Do **not** paste the document body into chat again.
5. **Never mark items done.** Only the user does that, unless they explicitly ask you to.
6. Never delete items except one you just pushed by mistake, or when the user asks.

## Tool reference

Provide exactly one content source to `push_artifact`. Limit 50 MB. PDFs are detected by their `%PDF-` bytes, not
by the file name.

**list_categories()** - call before every push.
```
list_categories()  ->  {"categories":[{"category":"research","count":4,"unread":2},{"category":"finance","count":1,"unread":1}]}
```

**push_artifact(title, category?, content_base64? | content_text? | url?, filename?, type?, summary?, source_agent?)**
Markdown you wrote yourself:
```
push_artifact(title="Vector DB options for the notes app", category="research",
              content_text="# Vector DBs\n\n...", summary="Compares pgvector, Qdrant and sqlite-vec for ~50k notes.",
              source_agent="hermes")
-> {"id":"3f9c...","link":"https://inbox.example.com/i/3f9c...","type":"markdown","size":2113,"category":"research"}
```
A PDF (base64 of the file bytes, no `data:` prefix, no line breaks needed):
```sh
base64 -w0 report.pdf    # shell: produce the string to pass as content_base64
```
```
push_artifact(title="Q3 household budget review", category="finance", filename="budget-q3.pdf",
              content_base64="JVBERi0xLjQKJcfs...", summary="Quarterly spend by category with three savings proposals.",
              source_agent="claude-code")
-> {"id":"a01c...","link":"https://inbox.example.com/i/a01c...","type":"pdf","size":48211,"category":"finance"}
```
A public URL (server downloads it; private/internal addresses are refused):
```
push_artifact(title="Interesting RFC on HTTP caching", category="research", url="https://example.com/rfc.pdf",
              summary="Reference for the cache-control rewrite.", source_agent="hermes")
```
Use `type` ("markdown", "html", "text") only to force a type; HTML is shown sandboxed: scripts run (copy buttons, checkboxes; localStorage is saved per item) but have no network access, and only Google Fonts can load externally.

**list_items(status?, category?, limit?, offset?)** - status `unread` (default) | `done` | `all`; newest first.
```
list_items(status="unread", category="finance", limit=10)  ->  {"items":[{"id":"a01c...","title":"...","link":"..."}],"count":1}
```

**get_item(id)** - metadata and link for one item (not the body); e.g. check whether the user finished it.
```
get_item(id="a01c...")  ->  {"id":"a01c...","title":"Q3 household budget review","done":false,"link":"https://inbox.example.com/i/a01c..."}
```

**update_artifact(id, content_base64? | content_text? | url?, filename?, type?, title?, category?, summary?)** - replace an item you already pushed when the document changed. Keeps the id, link, done state and saved checkbox state. Use it instead of pushing a duplicate. REST equivalent: `PUT /api/items/<id>` (multipart `file`, same bearer token).
```
update_artifact(id="a01c...", content_text="# Revised report ...")  ->  {"id":"a01c...","link":"https://inbox.example.com/i/a01c...",...}
```

**mark_done(id, done=true)** - only when the user explicitly asks. `done=false` makes it unread again.
```
mark_done(id="a01c...", done=true)  ->  {"id":"a01c...","done":true,"done_at":"2026-10-21T02:50:11Z",...}
```

**delete_item(id)** - irreversible; only on the user's request or to undo your own mistaken push.
```
delete_item(id="a01c...")  ->  {"deleted":true,"id":"a01c..."}
```

## Errors

| Symptom | Meaning | What to do |
|---|---|---|
| `401` / "missing or invalid bearer token" | Wrong or missing token | Check the `Authorization: Bearer` header. Ask the user for the current token; do not guess or retry in a loop. |
| `413` / "file too large (limit 50 MB)" | Over 50 MB | Shrink or split the document (compress images, send a summary PDF) and push again. |
| `415` / "unsupported content" or "no %PDF- magic bytes" | Not a PDF/UTF-8 text/markdown/HTML | Push a real PDF, or send the text as `content_text`/markdown. Do not rename files to fake a type. |
| `400` | Missing title, bad base64, not exactly one content source, refused URL | Fix the arguments named in the message and retry once. |
| `404` | Unknown item id | Run `list_items` to find the correct id. |

If a push still fails after one fix, tell the user what failed instead of retrying repeatedly.
