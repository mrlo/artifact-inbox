"""Server-rendered web UI (no JS needed except a delete confirm)."""
import html
import json
import re
import os
import secrets
import urllib.parse

import nh3
from markdown_it import MarkdownIt
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from starlette.routing import Route

from . import store

BASE_URL = os.environ.get("INBOX_BASE_URL", "http://localhost:8000").rstrip("/")
_md = MarkdownIt("commonmark", {"html": False, "linkify": False}).enable("table").enable("strikethrough")
_TAGS = {"p", "br", "hr", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "blockquote", "pre", "code",
         "em", "strong", "del", "a", "img", "table", "thead", "tbody", "tr", "th", "td", "sup", "sub"}
_ATTRS = {"a": {"href", "title"}, "img": {"src", "alt", "title"}, "th": {"align"}, "td": {"align"}}

CSS = """
:root{--bg:#fafaf7;--fg:#1d1d1f;--mut:#6b6b70;--card:#fff;--bd:#e2e2dc;--ac:#2554c7;--ok:#1d7a46;--bad:#b3261e}
@media(prefers-color-scheme:dark){:root{--bg:#121214;--fg:#e8e8ea;--mut:#9a9aa2;--card:#1b1b1f;--bd:#2f2f36;--ac:#7aa2ff;--ok:#5fcf8f;--bad:#ff8a80}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif}
body{display:grid;grid-template-columns:240px minmax(0,1fr);min-height:100vh}
main{max-width:860px;width:100%;margin:0 auto;padding:16px}
aside.side{border-right:1px solid var(--bd);background:var(--card);padding:16px 12px;position:sticky;top:0;height:100vh;overflow:auto}
aside.side .brand{display:block;color:var(--fg);text-decoration:none;font-weight:700;font-size:1.25rem;padding:0 8px 12px}
aside.side h3{font-size:.72rem;text-transform:uppercase;letter-spacing:.06em;color:var(--mut);margin:16px 8px 6px}
aside.side a.nav{display:flex;justify-content:space-between;gap:8px;padding:7px 10px;border-radius:8px;color:var(--fg);text-decoration:none;font-size:.93rem;word-break:break-word}
aside.side a.nav:hover{background:var(--bg)}aside.side a.nav.on{background:var(--ac);color:var(--bg)}
aside.side a.nav span{color:inherit;opacity:.7;font-variant-numeric:tabular-nums}
#navtoggle,label.menu{display:none}
@media(max-width:760px){
body{display:block}
label.menu{display:inline-block;position:sticky;top:0;z-index:5;margin:10px 16px 0;padding:6px 12px;border:1px solid var(--bd);border-radius:8px;background:var(--card);cursor:pointer;font-size:.9rem}
aside.side{display:none;position:static;height:auto;border-right:0;border-bottom:1px solid var(--bd);margin-top:8px}
#navtoggle:checked~aside.side{display:block}}a{color:var(--ac)}h1{font-size:1.4rem;margin:.2em 0 .6em}
nav.tabs,.chips,.bar{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}
nav.tabs a,.chips a{padding:6px 12px;border:1px solid var(--bd);border-radius:999px;text-decoration:none;color:var(--fg);background:var(--card);font-size:.9rem}
nav.tabs a.on,.chips a.on{background:var(--ac);border-color:var(--ac);color:var(--bg)}
.card{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:12px 14px;margin:10px 0}
.card.done .t{color:var(--mut)}.t{font-weight:600;font-size:1.05rem;text-decoration:none;color:var(--fg);word-break:break-word}
.meta{color:var(--mut);font-size:.82rem;margin:2px 0}.sum{margin:6px 0 2px}
.row{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}form{display:inline;margin:0}
button,.btn{font:inherit;font-size:.88rem;padding:6px 12px;border-radius:8px;border:1px solid var(--bd);background:var(--card);color:var(--fg);cursor:pointer;text-decoration:none;display:inline-block}
button.ok{border-color:var(--ok);color:var(--ok)}button.bad{border-color:var(--bad);color:var(--bad)}
h2.grp{font-size:1rem;margin:22px 0 4px;color:var(--mut);text-transform:uppercase;letter-spacing:.04em}
.doc{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:8px 20px;overflow-wrap:anywhere}
.doc img{max-width:100%}.doc pre{overflow:auto;background:var(--bg);padding:10px;border-radius:6px}
.doc table{border-collapse:collapse}.doc td,.doc th{border:1px solid var(--bd);padding:4px 8px}
iframe.view,embed.view{width:100%;height:78vh;border:1px solid var(--bd);border-radius:10px;background:#fff}
pre.txt{white-space:pre-wrap;overflow-wrap:anywhere;margin:0;padding:12px 0}.empty{color:var(--mut);padding:30px 0;text-align:center}
"""

# Injected into served HTML items. Runs in the sandboxed frame (opaque origin, so real storage throws):
# localStorage/sessionStorage become in-memory maps seeded from the server and mirrored to the parent;
# navigator.clipboard.writeText falls back to execCommand when the Clipboard API is blocked.
SHIM = """(function(){var seed=__STATE__,d={};try{d=JSON.parse(seed)||{}}catch(x){}
function mk(persist){var m=persist?d:{};var s={getItem:function(k){return Object.prototype.hasOwnProperty.call(m,k)?m[k]:null},
setItem:function(k,v){m[k]=String(v);sync()},removeItem:function(k){delete m[k];sync()},clear:function(){for(var k in m)delete m[k];sync()},
key:function(i){return Object.keys(m)[i]||null}};Object.defineProperty(s,'length',{get:function(){return Object.keys(m).length}});
function sync(){if(persist)try{parent.postMessage({readState:JSON.stringify(m)},'*')}catch(x){}}return s}
try{Object.defineProperty(window,'localStorage',{value:mk(true),configurable:true});
Object.defineProperty(window,'sessionStorage',{value:mk(false),configurable:true})}catch(x){}
function fb(t){return new Promise(function(ok,no){var a=document.createElement('textarea');a.value=t;a.style.cssText='position:fixed;opacity:0';
document.body.appendChild(a);a.select();var r=false;try{r=document.execCommand('copy')}catch(x){}a.remove();r?ok():no(new Error('copy blocked'))})}
var w=navigator.clipboard&&navigator.clipboard.writeText?navigator.clipboard.writeText.bind(navigator.clipboard):null;
var c={writeText:function(t){return w?w(t).catch(function(){return fb(t)}):fb(t)}};
try{Object.defineProperty(navigator,'clipboard',{value:c,configurable:true})}catch(x){}})();"""

# Parent side: persist the frame's state per item. Only messages from our own iframe are accepted.
BRIDGE = ("(function(){var f=document.getElementById('htmlview'),t;window.addEventListener('message',function(ev){"
          "if(!f||ev.source!==f.contentWindow||!ev.data||typeof ev.data.readState!=='string')return;"
          "var b=ev.data.readState;clearTimeout(t);t=setTimeout(function(){fetch('/state/__ID__',{method:'PUT',"
          "headers:{'Content-Type':'application/json'},body:b,credentials:'same-origin'})},300)})})();")


def e(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


SCRIPT = ("document.addEventListener('submit',function(ev){var m=ev.target.getAttribute('data-confirm');"
          "if(m&&!confirm(m))ev.preventDefault()})")


def page(title: str, body: str, status: int = 200, side: str = "", script: str = "") -> HTMLResponse:
    nonce = secrets.token_urlsafe(12)
    doc = (f"<!doctype html><html lang=en><head><meta charset=utf-8>"
           f"<meta name=viewport content='width=device-width,initial-scale=1'>"
           f"<meta name=color-scheme content='light dark'><title>{e(title)}</title><style>{CSS}</style></head>"
           f"<body><input type=checkbox id=navtoggle><label class=menu for=navtoggle>&#9776; Menu</label>"
           f"{side or sidebar()}<main>{body}</main>"
           f"<script nonce='{nonce}'>{SCRIPT}{script}</script></body></html>")
    return HTMLResponse(doc, status_code=status, headers={
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src https: data:; "
                                   "frame-src 'self'; connect-src 'self'; object-src 'self'; form-action 'self'; "
                                   f"base-uri 'none'; frame-ancestors 'self'; script-src 'nonce-{nonce}'",
        "Cache-Control": "no-store"})


def sidebar(tab: str = "", cat: str = "", sort: str = "") -> str:
    cnt = store.counts()
    s_arg = sort if sort and sort != "recent" else ""
    status = "".join(
        f"<a class='nav{' on' if t == tab and not cat else ''}' href='/{qs(tab=t, sort=s_arg)}'>{label}<span>{cnt[t]}</span></a>"
        for t, label in (("unread", "Unread"), ("done", "Done"), ("all", "All items")))
    view = tab if tab in ("unread", "done", "all") else "unread"
    cats = "".join(
        f"<a class='nav{' on' if c['category'] == cat else ''}' href='/{qs(tab=view, sort=s_arg, cat=c['category'])}'>"
        f"{e(c['category'])}<span>{c['count']}</span></a>" for c in store.categories(view))
    cats = cats or "<div class=meta style='padding:0 10px'>No categories yet</div>"
    return (f"<aside class=side><a class=brand href=/>artifact-inbox</a><h3>Inbox</h3>{status}"
            f"<h3>Categories</h3>{cats}<h3>Admin</h3><a class=nav href=/agents>Agents</a></aside>")


def render_markdown(text: str) -> str:
    return nh3.clean(_md.render(text), tags=_TAGS, attributes=_ATTRS,
                     url_schemes={"http", "https", "mailto"}, link_rel="noopener noreferrer nofollow")


def qs(**kw) -> str:
    return "?" + urllib.parse.urlencode({k: v for k, v in kw.items() if v})


def safe_next(v: str | None, default: str = "/") -> str:
    return v if v and v.startswith("/") and not v.startswith("//") and "\\" not in v else default


def card(it: dict, nxt: str) -> str:
    done = it["done"]
    toggle = (f"<form method=post action='/i/{it['id']}/{'undone' if done else 'done'}'>"
              f"<input type=hidden name=next value='{e(nxt)}'>"
              f"<button class={'' if done else 'ok'}>{'Mark unread' if done else 'Mark done'}</button></form>")
    delete = (f"<form method=post action='/i/{it['id']}/delete' "
              f"data-confirm='Delete this item permanently?'>"
              f"<input type=hidden name=next value='{e(nxt)}'><button class=bad>Delete</button></form>")
    summ = f"<div class=sum>{e(it['summary'])}</div>" if it["summary"] else ""
    return (f"<div class='card{' done' if done else ''}'><a class=t href='/i/{it['id']}'>{e(it['title'])}</a>"
            f"<div class=meta>{e(it['category'])} · {e(it['type'])} · {e(it['source_agent'])} · "
            f"{e(it['created_at'][:16].replace('T', ' '))} UTC{' · done' if done else ''}</div>{summ}"
            f"<div class=row><a class=btn href='/i/{it['id']}'>Open</a>{toggle}{delete}</div></div>")


def index(request: Request) -> Response:
    q = request.query_params
    tab = q.get("tab") if q.get("tab") in ("unread", "done", "all") else "unread"
    sort = "category" if q.get("sort") == "category" else "recent"
    cat = store.norm_category(q["cat"]) if q.get("cat") else ""
    items = store.list_items(tab, cat or None, limit=500, sort=sort)
    here = "/" + qs(tab=tab, sort=sort if sort != "recent" else "", cat=cat)
    sorts = "".join(f"<a class='{'on' if s == sort else ''}' href='/{qs(tab=tab, sort=s if s != 'recent' else '', cat=cat)}'>{label}</a>"
                    for s, label in (("recent", "Newest first"), ("category", "By category")))
    unread_here = sum(1 for i in items if not i["done"])
    bulk = ""
    if tab != "done" and unread_here:
        label = f"Mark all done ({unread_here}{' in ' + e(cat) if cat else ''})"
        bulk = (f"<form method=post action='/bulk/done' data-confirm='Mark {unread_here} item(s) done?'>"
                f"<input type=hidden name=cat value='{e(cat)}'><input type=hidden name=next value='{e(here)}'>"
                f"<button class=ok>{label}</button></form>")
    if not items:
        body_items = "<div class=empty>Nothing here.</div>"
    elif sort == "category":
        out, last = [], None
        for it in items:
            if it["category"] != last:
                last = it["category"]
                n = sum(1 for x in items if x["category"] == last)
                out.append(f"<h2 class=grp>{e(last)} ({n})</h2>")
            out.append(card(it, here))
        body_items = "".join(out)
    else:
        body_items = "".join(card(it, here) for it in items)
    heading = f"{e(cat) if cat else {'unread': 'Unread', 'done': 'Done', 'all': 'All items'}[tab]}"
    return page("artifact-inbox", f"<h1>{heading} <span class=meta>({len(items)})</span></h1>"
                        f"<nav class=tabs>{sorts}</nav><div class=bar>{bulk}</div>{body_items}",
                side=sidebar(tab, cat, sort))


def reader(request: Request) -> Response:
    it = store.get_item(request.path_params["id"])
    if not it:
        return page("Not found", "<h1>Not found</h1><p><a href=/>Back</a></p>", 404)
    me = f"/i/{it['id']}"
    raw = f"/raw/{it['id']}"
    path = store.file_for(it)
    extra = ""
    if it["type"] == "pdf":
        view = (f"<embed class=view src='{raw}#view=FitH' type='application/pdf'>"
                f"<p class=meta>Can't see the PDF? <a href='{raw}?download=1'>Download it</a>.</p>")
    elif it["type"] == "html":
        view = (f"<iframe id=htmlview class=view sandbox='allow-scripts' allow='clipboard-write' "
                f"src='{raw}' title='{e(it['title'])}'></iframe>")
        extra = BRIDGE.replace("__ID__", it["id"])
    else:
        text = path.read_text("utf-8", errors="replace")
        view = (f"<div class=doc>{render_markdown(text)}</div>" if it["type"] == "markdown"
                else f"<div class=doc><pre class=txt>{e(text)}</pre></div>")
    done = it["done"]
    toggle = (f"<form method=post action='{me}/{'undone' if done else 'done'}'><input type=hidden name=next value='{me}'>"
              f"<button class={'' if done else 'ok'}>{'Mark unread' if done else 'Mark done'}</button></form>")
    delete = (f"<form method=post action='{me}/delete' data-confirm='Delete this item permanently?'>"
              f"<input type=hidden name=next value='/'><button class=bad>Delete</button></form>")
    summ = f"<p class=sum>{e(it['summary'])}</p>" if it["summary"] else ""
    head = (f"<p><a href='/'>&larr; Inbox</a></p><h1>{e(it['title'])}</h1>"
            f"<div class=meta>{e(it['category'])} · {e(it['type'])} · {e(it['source_agent'])} · "
            f"{e(it['created_at'][:16].replace('T', ' '))} UTC{' · done' if done else ''}</div>{summ}"
            f"<div class=row>{toggle}<a class=btn href='{raw}?download=1'>Download</a>{delete}</div><br>")
    return page(it["title"], head + view, side=sidebar("all", it["category"]), script=extra)


def raw(request: Request) -> Response:
    it = store.get_item(request.path_params["id"])
    if not it:
        return Response("not found", 404)
    path = store.file_for(it)
    ctype = {"pdf": "application/pdf", "html": "text/html; charset=utf-8",
             "markdown": "text/plain; charset=utf-8", "text": "text/plain; charset=utf-8"}[it["type"]]
    dl = request.query_params.get("download")
    safe = "".join(ch if ch.isalnum() or ch in "-_ ." else "_" for ch in it["title"])[:80].strip() or "item"
    headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store",
               "Content-Disposition": f"{'attachment' if dl else 'inline'}; filename=\"{safe}.{store.EXT[it['type']]}\""}
    if it["type"] != "pdf":
        # Untrusted bytes: no scripts, no network, opaque origin even if opened directly.
        headers["Content-Security-Policy"] = ("sandbox; default-src 'none'; style-src 'unsafe-inline'; "
                                              "img-src data:")
    if it["type"] == "html" and not dl:
        # Scripts run in an opaque origin (no same-origin, no network): the shim gives them a
        # localStorage backed by the parent page, which persists it per item.
        headers["Content-Security-Policy"] = (
            "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; "
            "style-src 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
            "img-src data:")
        html = path.read_text("utf-8", errors="replace")
        state = json.dumps(store.get_state(it["id"])).replace("<", "\\u003c")
        shim = f"<script>{SHIM.replace('__STATE__', state)}</script>"
        m = re.search(r"<head[^>]*>", html, re.I) or re.search(r"<html[^>]*>", html, re.I)
        html = html[:m.end()] + shim + html[m.end():] if m else shim + html
        return Response(html, media_type=ctype, headers=headers)
    return FileResponse(path, media_type=ctype, headers=headers)


async def state(request: Request) -> Response:
    item_id = request.path_params["id"]
    if not store.get_item(item_id):
        return Response("not found", 404)
    if request.method == "PUT":
        origin = request.headers.get("origin")
        if not origin or urllib.parse.urlsplit(origin).netloc != request.headers.get("host"):
            return Response("cross-origin request refused", 403)
        body = await request.body()
        if len(body) > store.MAX_STATE:
            return Response("too large", 413)
        try:
            ok = isinstance(json.loads(body), dict)
        except ValueError:
            ok = False
        if not ok:
            return Response("expected a JSON object", 400)
        store.set_state(item_id, body.decode("utf-8"))
        return Response(status_code=204)
    return Response(store.get_state(item_id), media_type="application/json", headers={"Cache-Control": "no-store"})


async def _form(request: Request):
    # Cheap CSRF guard on top of SSO cookies: same-origin POSTs only.
    origin = request.headers.get("origin")
    if origin and urllib.parse.urlsplit(origin).netloc != request.headers.get("host"):
        return None
    return await request.form()


async def act(request: Request) -> Response:
    form = await _form(request)
    if form is None:
        return Response("cross-origin request refused", 403)
    item_id, action = request.path_params["id"], request.path_params["action"]
    nxt = safe_next(form.get("next"))
    if action == "delete":
        store.delete_item(item_id)
        if nxt.startswith(f"/i/{item_id}"):
            nxt = "/"
    elif action in ("done", "undone"):
        store.set_done(item_id, action == "done")
    return RedirectResponse(nxt, 303)


async def bulk(request: Request) -> Response:
    form = await _form(request)
    if form is None:
        return Response("cross-origin request refused", 403)
    store.mark_all_done(form.get("cat") or None)
    return RedirectResponse(safe_next(form.get("next")), 303)


DOC_DIR = os.environ.get("INBOX_DOC_DIR", "/srv")


def _public_text(rel: str):
    def handler(request: Request) -> Response:
        try:
            body = open(os.path.join(DOC_DIR, rel), encoding="utf-8").read()
        except OSError:
            return Response("not found", 404)
        body = body.replace("https://inbox.example.com", BASE_URL)
        claim = request.query_params.get("claim", "")
        if re.fullmatch(r"[A-Za-z0-9_-]{20,128}", claim):  # GET never consumes the claim; POST /api/claim does
            body = body.replace("<CLAIM_CODE>", claim)
        return Response(body, media_type="text/markdown; charset=utf-8", headers={
            "X-Content-Type-Options": "nosniff", "Cache-Control": "no-cache"})
    return handler


def healthz(request: Request) -> Response:
    store.counts()
    return Response("ok", media_type="text/plain")


routes = [
    Route("/", index), Route("/healthz", healthz),
    Route("/install", _public_text("docs/INSTALL.md")), Route("/install/SKILL.md", _public_text("skill/SKILL.md")), Route("/i/{id}", reader), Route("/raw/{id}", raw), Route("/state/{id}", state, methods=["GET", "PUT"]),
    Route("/i/{id}/{action}", act, methods=["POST"]), Route("/bulk/done", bulk, methods=["POST"]),
]
