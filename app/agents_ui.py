"""Web UI for managing agents (named tokens) and single-use install links."""
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

from . import agents, store, ui

e = ui.e


def _view(extra: str = "", status: int = 200) -> Response:
    rows = []
    for a in agents.list_agents():
        state = (f"<span class=meta>revoked {e(a['revoked_at'])}</span>" if a["revoked_at"] else
                 f"<form method=post action='/agents/{e(a['id'])}/revoke' "
                 f"data-confirm='Revoke {e(a['name'])}? Its token stops working immediately.'>"
                 f"<button class=bad>Revoke</button></form>")
        rows.append(f"<div class=card><b>{e(a['name'])}</b>"
                    f"<div class=meta>created {e(a['created_at'])} &middot; "
                    f"last used {e(a['last_used_at'] or 'never')}</div><div class=row>{state}</div></div>")
    pending = [f"<div class=card><b>{e(p['name'])}</b> <span class=meta>install link unused, expires {e(p['expires_at'])}</span>"
               f"<div class=row><form method=post action='/agents/claims/{e(p['id'])}/cancel'>"
               f"<button>Cancel link</button></form></div></div>" for p in agents.list_pending()]
    body = (f"<h1>Agents</h1>{extra}"
            "<div class=card><b>Add an agent</b><div class=meta>Creates a single-use install link. Give the agent the "
            "link; it exchanges it once for its own token, which you can revoke later.</div>"
            "<form method=post action='/agents/new' class=row>"
            "<input name=name placeholder='e.g. claude-code' required maxlength=40 "
            "style='font:inherit;padding:6px 10px;border-radius:8px;border:1px solid var(--bd);background:var(--card);color:var(--fg)'>"
            "<button class=ok>Create install link</button></form></div>"
            + ("<h2 class=grp>Pending install links</h2>" + "".join(pending) if pending else "")
            + "<h2 class=grp>Agents</h2>" + ("".join(rows) or "<div class=empty>No per-agent tokens yet.</div>")
            + "<p class=meta>The admin token (<code>INBOX_API_TOKEN</code>) keeps working and is not listed here.</p>")
    return ui.page("Agents", body, status)


async def index(request: Request) -> Response:
    return _view()


async def new(request: Request) -> Response:
    form = await ui._form(request)
    if form is None:
        return Response("cross-origin request refused", 403)
    try:
        _, code = agents.create_claim(form.get("name"))
    except store.PushError as err:
        return _view(f"<div class=card style='border-color:var(--bad)'>{e(err)}</div>", err.status)
    prompt = f"install this: {ui.BASE_URL}/install?claim={code}"
    ttl = agents.CLAIM_TTL_MIN
    box = (f"<div class=card style='border-color:var(--ok)'><b>Install link created for {e(form.get('name'))}</b>"
           f"<div class=meta>Shown once. Single use, expires in {ttl} min. Paste this to the agent:</div>"
           f"<pre class=txt style='user-select:all'>{e(prompt)}</pre></div>")
    r = _view(box)
    r.headers["Cache-Control"] = "no-store"
    return r


async def revoke(request: Request) -> Response:
    form = await ui._form(request)
    if form is None:
        return Response("cross-origin request refused", 403)
    agents.revoke(request.path_params["id"])
    return RedirectResponse("/agents", 303)


async def cancel(request: Request) -> Response:
    form = await ui._form(request)
    if form is None:
        return Response("cross-origin request refused", 403)
    agents.cancel_claim(request.path_params["id"])
    return RedirectResponse("/agents", 303)


routes = [
    Route("/agents", index),
    Route("/agents/new", new, methods=["POST"]),
    Route("/agents/{id}/revoke", revoke, methods=["POST"]),
    Route("/agents/claims/{id}/cancel", cancel, methods=["POST"]),
]
