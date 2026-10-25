"""ASGI entrypoint: web UI + REST push + MCP (streamable HTTP) on one port."""
import base64
import hmac
import json
import os
from typing import Literal, Optional

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from . import store, ui

TOKEN = os.environ.get("INBOX_API_TOKEN", "").encode()
BASE_URL = ui.BASE_URL
MAX_REQ = store.MAX_BYTES * 4 // 3 + 1024 * 1024  # base64 inflation + JSON envelope

mcp = FastMCP(
    "artifact-inbox",
    instructions=("A artifact inbox for the human user. Push finished documents (reports, research summaries, "
                  "PDFs) here so the user can read them later; never mark them done yourself."),
    stateless_http=True, json_response=True, streamable_http_path="/mcp",
    max_request_body_size=MAX_REQ,
    # Host/Origin checks are replaced by the bearer token (public hostname, no cookies involved).
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


def link(item_id: str) -> str:
    return f"{BASE_URL}/i/{item_id}"


def public(it: dict) -> dict:
    return {"id": it["id"], "title": it["title"], "category": it["category"], "source_agent": it["source_agent"],
            "summary": it["summary"], "type": it["type"], "size": it["size"], "created_at": it["created_at"],
            "done": bool(it["done"]), "done_at": it["done_at"], "link": link(it["id"])}


def _err(e: store.PushError):
    return ValueError(f"{e.status}: {e}")


@mcp.tool()
def push_artifact(title: str, category: str = "general", content_base64: Optional[str] = None,
                  content_text: Optional[str] = None, url: Optional[str] = None,
                  filename: Optional[str] = None, type: Optional[Literal["pdf", "markdown", "html", "text"]] = None,
                  summary: Optional[str] = None, source_agent: Optional[str] = None) -> dict:
    """Save a finished document into the user's artifact inbox (inbox.example.com) so they can read it later.

    Use this when you have produced a report, research summary, generated PDF or any artifact longer than
    a chat message. Do NOT use it for short answers, secrets/credentials, or raw logs. After a successful
    push, give the user the returned `link` and do not repeat the document body in chat.

    Provide exactly ONE content source:
    - content_base64: base64 of the file bytes (use for PDFs and any binary file).
    - content_text: the document as plain text/markdown/HTML (use for markdown you wrote yourself).
    - url: an http(s) URL the server downloads (public addresses only).

    Fields:
    - title: descriptive, human-readable, no timestamps (e.g. "Q3 mortgage refinance comparison").
    - category: short lowercase label such as research, finance, jobs, server, drafts. Call list_categories
      first and reuse an existing one instead of inventing a near-duplicate. Default "general".
    - filename: original file name, helps type detection (e.g. "report.pdf"). Never used as a storage path.
    - type: pdf | markdown | html | text. Normally omit it; PDFs are detected by magic bytes, other
      types by filename or content. Set it only to force markdown/html/text.
    - summary: 1-2 sentences saying what the document is and why it matters.
    - source_agent: your own name (e.g. "claude-code", "hermes"). Always set it.
    Limit 50 MB. Returns {id, link, type, size, category}.
    """
    given = [x for x in (content_base64, content_text, url) if x]
    if len(given) != 1:
        raise ValueError("400: provide exactly one of content_base64, content_text or url")
    try:
        if content_base64:
            data = store.decode_b64(content_base64)
        elif content_text:
            data = content_text.encode()
        else:
            data, fetched_name = store.fetch_url(url)
            filename = filename or fetched_name
        it = store.add_item(title=title, category=category, data=data, filename=filename, declared_type=type,
                            summary=summary, source_agent=source_agent, from_text=bool(content_text))
    except store.PushError as e:
        raise _err(e)
    return {"id": it["id"], "link": link(it["id"]), "type": it["type"], "size": it["size"],
            "category": it["category"]}


@mcp.tool()
def update_artifact(id: str, content_base64: Optional[str] = None, content_text: Optional[str] = None,
                    url: Optional[str] = None, filename: Optional[str] = None,
                    type: Optional[Literal["pdf", "markdown", "html", "text"]] = None,
                    title: Optional[str] = None, category: Optional[str] = None,
                    summary: Optional[str] = None) -> dict:
    """Replace the content of an item you already pushed, keeping its id, link, done state and (for HTML)
    saved checkbox state. Use this instead of push_artifact when the document changed; do not push a duplicate.

    Provide exactly ONE content source (content_base64, content_text or url), as in push_artifact.
    title, category and summary are optional and left unchanged when omitted. Returns {id, link, type, size, category}.
    """
    given = [x for x in (content_base64, content_text, url) if x]
    if len(given) != 1:
        raise ValueError("400: provide exactly one of content_base64, content_text or url")
    try:
        if content_base64:
            data = store.decode_b64(content_base64)
        elif content_text:
            data = content_text.encode()
        else:
            data, fetched_name = store.fetch_url(url)
            filename = filename or fetched_name
        it = store.update_item(id, data=data, filename=filename, declared_type=type, title=title,
                               category=category, summary=summary, from_text=bool(content_text))
    except store.PushError as e:
        raise _err(e)
    return {"id": it["id"], "link": link(it["id"]), "type": it["type"], "size": it["size"],
            "category": it["category"]}


@mcp.tool()
def list_items(status: Literal["unread", "done", "all"] = "unread", category: Optional[str] = None,
               limit: int = 50, offset: int = 0) -> dict:
    """List items in the artifact inbox, newest first.

    Use this to check what is already in the inbox (e.g. to avoid pushing a duplicate) or to find an item id.
    status: unread (default) | done | all. category: exact category to filter by (optional).
    limit: 1-500 (default 50). offset: for paging. Returns {items:[{id,title,category,type,summary,
    source_agent,created_at,done,link,...}], count}. Does not return document bodies.
    """
    try:
        items = [public(i) for i in store.list_items(status, category, limit, offset)]
    except store.PushError as e:
        raise _err(e)
    return {"items": items, "count": len(items)}


@mcp.tool()
def get_item(id: str) -> dict:
    """Get the metadata of one inbox item by id (as returned by push_artifact or list_items).

    Use it to confirm an item exists or to check whether the user has marked it done. Returns metadata
    and the reader link, not the document body.
    """
    it = store.get_item(id)
    if not it:
        raise ValueError("404: no such item")
    return public(it)


@mcp.tool()
def mark_done(id: str, done: bool = True) -> dict:
    """Mark an item done (done=true) or unread again (done=false).

    Only the human user decides what is done. Do NOT call this on your own after pushing; use it only when
    the user explicitly asks you to (e.g. "mark the mortgage report as done"). Returns the updated item.
    """
    it = store.set_done(id, done)
    if not it:
        raise ValueError("404: no such item")
    return public(it)


@mcp.tool()
def list_categories() -> dict:
    """List the categories currently in use with item counts.

    Call this BEFORE push_artifact and reuse an existing category when one fits, instead of inventing a
    near-duplicate (e.g. use "research", not "researching"). Returns {categories:[{category,count,unread}]}.
    """
    return {"categories": store.categories("all")}


@mcp.tool()
def delete_item(id: str) -> dict:
    """Permanently delete an item and its file. Irreversible.

    Use only when the user explicitly asks to delete something, or to remove an item YOU pushed by mistake
    (wrong file, duplicate). Never delete items to tidy up. Returns {deleted: true, id}.
    """
    if not store.delete_item(id):
        raise ValueError("404: no such item")
    return {"deleted": True, "id": id}


# ---- REST -------------------------------------------------------------------------------------

async def api_push(request: Request) -> Response:
    form = await request.form(max_part_size=store.MAX_BYTES + 1024 * 1024)
    f = form.get("file")
    if f is None or not hasattr(f, "read"):
        return JSONResponse({"error": "multipart field 'file' is required"}, 400)
    data = await f.read(store.MAX_BYTES + 1)
    try:
        it = store.add_item(title=form.get("title") or os.path.splitext(f.filename or "")[0],
                            category=form.get("category"), data=data, filename=f.filename,
                            declared_type=form.get("type"), summary=form.get("summary"),
                            source_agent=form.get("source_agent"))
    except store.PushError as e:
        return JSONResponse({"error": str(e)}, e.status)
    return JSONResponse({"id": it["id"], "link": link(it["id"]), "type": it["type"], "size": it["size"],
                         "category": it["category"]}, 201)


async def api_update(request: Request) -> Response:
    form = await request.form(max_part_size=store.MAX_BYTES + 1024 * 1024)
    f = form.get("file")
    if f is None or not hasattr(f, "read"):
        return JSONResponse({"error": "multipart field 'file' is required"}, 400)
    data = await f.read(store.MAX_BYTES + 1)
    try:
        it = store.update_item(request.path_params["id"], data=data, filename=f.filename,
                               declared_type=form.get("type"), title=form.get("title"),
                               category=form.get("category"), summary=form.get("summary"))
    except store.PushError as e:
        return JSONResponse({"error": str(e)}, e.status)
    return JSONResponse({"id": it["id"], "link": link(it["id"]), "type": it["type"], "size": it["size"],
                         "category": it["category"]}, 200)


def _ui_creds():
    """Optional built-in login for the web UI (HTTP basic auth). Unset password = rely on your proxy."""
    pw = os.environ.get("INBOX_UI_PASSWORD", "")
    return (os.environ.get("INBOX_UI_USER", "admin").encode(), pw.encode()) if pw else None


def _basic_ok(header: bytes, creds) -> bool:
    if header[:6].lower() != b"basic ":
        return False
    try:
        user, _, pw = base64.b64decode(header[6:].strip(), validate=True).partition(b":")
    except ValueError:
        return False
    # Compare both fields unconditionally so timing doesn't reveal which one was wrong.
    return hmac.compare_digest(user, creds[0]) & hmac.compare_digest(pw, creds[1])


class Guard:
    """Bearer auth for /mcp and /api, request-size cap, optional basic auth for the UI."""

    PUBLIC = ("/healthz", "/install")  # token-free by design

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path = scope["path"]
            if path == "/mcp" or path.startswith(("/mcp/", "/api/")) or path == "/api":
                h = {k: v for k, v in scope["headers"]}
                got = h.get(b"authorization", b"")
                ok = bool(TOKEN) and got[:7].lower() == b"bearer " and hmac.compare_digest(got[7:].strip(), TOKEN)
                if not ok:
                    return await self._json(send, 401, {"error": "missing or invalid bearer token"},
                                            [(b"www-authenticate", b'Bearer realm="artifact-inbox"')])
                if int(h.get(b"content-length", b"0") or 0) > MAX_REQ:
                    return await self._json(send, 413, {"error": "file too large (limit 50 MB)"})
            elif not (path in self.PUBLIC or path.startswith("/install/")):
                creds = _ui_creds()
                got = {k: v for k, v in scope["headers"]}.get(b"authorization", b"")
                if creds and not _basic_ok(got, creds):
                    return await self._json(send, 401, {"error": "authentication required"},
                                            [(b"www-authenticate", b'Basic realm="artifact-inbox", charset="UTF-8"')])
        await self.app(scope, receive, send)

    @staticmethod
    async def _json(send, status, obj, extra=()):
        body = json.dumps(obj).encode()
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode()), *extra]})
        await send({"type": "http.response.body", "body": body})


def build():
    store.init()
    app = mcp.streamable_http_app()  # Starlette app, owns the MCP session-manager lifespan
    app.router.routes.extend(ui.routes)
    from starlette.routing import Route
    app.router.routes.append(Route("/api/push", api_push, methods=["POST"]))
    app.router.routes.append(Route("/api/items/{id}", api_update, methods=["PUT"]))
    return Guard(app)


app = build()
