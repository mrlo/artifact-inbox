import base64
import json
import os
import sys
import tempfile

import pytest

os.environ["INBOX_DATA_DIR"] = tempfile.mkdtemp()
os.environ["INBOX_API_TOKEN"] = "t" * 64
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from starlette.testclient import TestClient  # noqa: E402

from app import server, store  # noqa: E402

AUTH = {"Authorization": "Bearer " + "t" * 64}
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


@pytest.fixture(scope="module")
def client():
    with TestClient(server.app, base_url="http://inbox.test") as c:
        yield c


def rpc(client, method, params, id_=1):
    r = client.post("/mcp", headers={**AUTH, "Accept": "application/json, text/event-stream"},
                    json={"jsonrpc": "2.0", "id": id_, "method": method, "params": params})
    assert r.status_code == 200, r.text
    return r.json()


def call(client, name, args):
    out = rpc(client, "tools/call", {"name": name, "arguments": args})["result"]
    if not out.get("isError"):
        out["structuredContent"] = json.loads(out["content"][0]["text"])
    return out


def test_auth(client):
    assert client.post("/mcp", json={}).status_code == 401
    assert client.post("/mcp", headers={"Authorization": "Bearer nope"}, json={}).status_code == 401
    assert client.post("/api/push", files={"file": ("a.md", b"x")}).status_code == 401
    assert client.get("/").status_code == 200  # UI auth is Traefik's job


def test_rest_push_list_done_delete(client):
    r = client.post("/api/push", headers=AUTH, data={"title": "Notes", "category": " Research ", "source_agent": "curl"},
                    files={"file": ("n.md", b"# Hello\n\n<script>alert(1)</script>\n\n[x](javascript:alert(1))\n\n<img src=x onerror=alert(1)>")})
    assert r.status_code == 201, r.text
    iid = r.json()["id"]
    it = store.get_item(iid)
    assert it["type"] == "markdown" and it["category"] == "research" and it["file_path"] == f"{iid}.md"
    page = client.get(f"/i/{iid}").text
    assert "<h1>Hello</h1>" in page and "<script>alert" not in page and "href=\"javascript" not in page and "<img src=x" not in page
    assert client.get("/").text.count("Notes") >= 1
    assert "Notes" not in client.get("/?tab=done").text
    assert client.post(f"/i/{iid}/done", data={"next": "/"}, follow_redirects=False).status_code == 303
    assert "Notes" in client.get("/?tab=done").text and "Notes" not in client.get("/?tab=unread").text
    assert store.get_item(iid)["done_at"]
    client.post(f"/i/{iid}/undone")
    assert store.get_item(iid)["done"] == 0
    assert client.post(f"/i/{iid}/delete", data={"next": f"/i/{iid}"}, follow_redirects=False).headers["location"] == "/"
    assert store.get_item(iid) is None and not (store.FILES_DIR / f"{iid}.md").exists()


def test_pdf_sniffing(client):
    # extension lies: a .txt that is really a PDF
    r = client.post("/api/push", headers=AUTH, data={"title": "Sneaky"}, files={"file": ("a.txt", PDF)})
    assert r.json()["type"] == "pdf"
    # claims pdf but is not
    r = client.post("/api/push", headers=AUTH, data={"title": "Fake"}, files={"file": ("a.pdf", b"hello")})
    assert r.status_code == 415
    # binary garbage
    r = client.post("/api/push", headers=AUTH, data={"title": "Bin"}, files={"file": ("a.bin", b"\x00\x01\xff\xfe")})
    assert r.status_code == 415
    raw = client.get(f"/raw/{store.list_items('all')[0]['id']}")
    assert raw.headers["x-content-type-options"] == "nosniff"


def test_size_limit(client, monkeypatch):
    monkeypatch.setattr(store, "MAX_BYTES", 100)
    r = client.post("/api/push", headers=AUTH, data={"title": "Big"}, files={"file": ("a.txt", b"x" * 101)})
    assert r.status_code == 413


def test_html_served_sandboxed(client):
    r = client.post("/api/push", headers=AUTH, data={"title": "H"}, files={"file": ("a.html", b"<script>1</script>")})
    iid = r.json()["id"]
    raw = client.get(f"/raw/{iid}")
    assert raw.headers["content-type"].startswith("text/html")
    assert "sandbox" in raw.headers["content-security-policy"]
    assert "sandbox='allow-scripts'" in client.get(f"/i/{iid}").text
    csp = raw.headers["content-security-policy"]
    assert "allow-same-origin" not in csp and "connect-src" not in csp and "default-src 'none'" in csp
    assert "readState" in raw.text and raw.text.index("readState") < raw.text.index("<script>1")


def test_html_state_roundtrip(client):
    iid = client.post("/api/push", headers=AUTH, data={"title": "S"}, files={"file": ("a.html", b"<html><head></head>x")}).json()["id"]
    assert client.get(f"/state/{iid}").json() == {}
    bad = {"Origin": "https://evil.example"}
    assert client.put(f"/state/{iid}", headers=bad, content=b"{}").status_code == 403
    ok = {"Origin": "http://inbox.test"}
    assert client.put(f"/state/{iid}", headers=ok, content=b"[1]").status_code == 400
    assert client.put(f"/state/{iid}", headers=ok, content=b'{"done:1":"1"}').status_code == 204
    assert client.get(f"/state/{iid}").json() == {"done:1": "1"}
    assert "done:1" in client.get(f"/raw/{iid}").text


def test_csrf(client):
    iid = client.post("/api/push", headers=AUTH, data={"title": "C"}, files={"file": ("a.md", b"x")}).json()["id"]
    r = client.post(f"/i/{iid}/delete", headers={"Origin": "https://evil.example"}, follow_redirects=False)
    assert r.status_code == 403 and store.get_item(iid)


def test_mcp_tools_flow(client):
    tools = {t["name"] for t in rpc(client, "tools/list", {})["result"]["tools"]}
    assert tools == {"push_artifact", "update_artifact", "list_items", "get_item", "mark_done", "list_categories", "delete_item"}
    b64 = base64.b64encode(PDF).decode()
    res = call(client, "push_artifact", {"title": "A PDF", "category": "Finance", "content_base64": b64,
                                         "filename": "x.pdf", "source_agent": "test", "summary": "s"})
    out = res["structuredContent"]
    assert out["type"] == "pdf" and out["link"].endswith("/i/" + out["id"]) and not res.get("isError")
    iid = out["id"]
    res = call(client, "push_artifact", {"title": "Bad", "content_base64": base64.b64encode(b"zz\x00").decode()})
    assert res["isError"] and "415" in res["content"][0]["text"]
    res = call(client, "push_artifact", {"title": "Two", "content_text": "a", "url": "http://x"})
    assert res["isError"]
    call(client, "push_artifact", {"title": "Md", "category": "research", "content_text": "# Hi"})
    cats = call(client, "list_categories", {})["structuredContent"]["categories"]
    assert {c["category"] for c in cats} >= {"finance", "research"}
    lst = call(client, "list_items", {"category": "finance"})["structuredContent"]
    assert [i["id"] for i in lst["items"]] == [iid]
    assert call(client, "mark_done", {"id": iid})["structuredContent"]["done"] is True
    assert call(client, "list_items", {"category": "finance"})["structuredContent"]["count"] == 0
    assert call(client, "list_items", {"status": "done"})["structuredContent"]["count"] >= 1
    assert call(client, "get_item", {"id": iid})["structuredContent"]["done"] is True
    assert call(client, "delete_item", {"id": iid})["structuredContent"]["deleted"] is True
    assert call(client, "get_item", {"id": iid})["isError"]


def test_ui_sort_filter_bulk(client):
    for t, c in (("one", "zeta"), ("two", "alpha"), ("three", "alpha")):
        client.post("/api/push", headers=AUTH, data={"title": t, "category": c}, files={"file": ("a.md", b"x")})
    html = client.get("/?sort=category&tab=all").text
    assert html.index("alpha (") < html.index("zeta (")
    assert "alpha (2)" in html
    client.post("/bulk/done", data={"cat": "alpha", "next": "/"})
    unread = {i["title"] for i in store.list_items("unread", "alpha")}
    assert unread == set()
    assert any(i["title"] == "one" for i in store.list_items("unread"))


def test_ssrf_blocked(client):
    res = call(client, "push_artifact", {"title": "x", "url": "http://127.0.0.1:1/x"})
    assert res["isError"] and "non-public" in res["content"][0]["text"]


def test_install_page_public(client, monkeypatch):
    from app import ui
    monkeypatch.setattr(ui, "DOC_DIR", os.path.dirname(os.path.dirname(__file__)))
    r = client.get("/install")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/markdown")
    assert "<INBOX_API_TOKEN>" in r.text and "t" * 64 not in r.text
    assert client.get("/install/SKILL.md").text.startswith("---\nname: artifact-inbox")
    assert "inbox.example.com" not in r.text and ui.BASE_URL in r.text


def test_update_in_place(client):
    iid = client.post("/api/push", headers=AUTH, data={"title": "U"}, files={"file": ("a.md", b"# one")}).json()["id"]
    store.set_done(iid, True)
    r = client.put(f"/api/items/{iid}", headers=AUTH, data={"title": "U2"}, files={"file": ("a.html", b"<p>two</p>")})
    assert r.status_code == 200 and r.json()["id"] == iid and r.json()["type"] == "html"
    it = store.get_item(iid)
    assert it["title"] == "U2" and it["done"] == 1 and "two" in client.get(f"/raw/{iid}").text
    assert not (store.FILES_DIR / f"{iid}.md").exists()
    assert client.put("/api/items/nope", headers=AUTH, files={"file": ("a.md", b"x")}).status_code == 404
    assert client.put(f"/api/items/{iid}", files={"file": ("a.md", b"x")}).status_code == 401


def test_ui_basic_auth(client, monkeypatch):
    # off by default: the UI is open (proxy mode)
    assert client.get("/").status_code == 200
    monkeypatch.setenv("INBOX_UI_PASSWORD", "s3cret")
    r = client.get("/")
    assert r.status_code == 401 and r.headers["www-authenticate"].startswith("Basic")
    good = {"Authorization": "Basic " + base64.b64encode(b"admin:s3cret").decode()}
    bad = {"Authorization": "Basic " + base64.b64encode(b"admin:nope").decode()}
    assert client.get("/", headers=good).status_code == 200
    assert client.get("/", headers=bad).status_code == 401
    assert client.get("/", headers={"Authorization": "Basic !!!"}).status_code == 401
    assert client.get("/raw/x").status_code == 401 and client.post("/bulk/done").status_code == 401
    # agent + public paths are unaffected
    assert client.get("/healthz").status_code == 200
    assert client.post("/api/push").status_code == 401  # bearer error, not basic
    assert "Bearer" in client.post("/api/push").headers["www-authenticate"]
    monkeypatch.setenv("INBOX_UI_USER", "larry")
    assert client.get("/", headers=good).status_code == 401


# ---- per-agent tokens / claim links ------------------------------------------------------------

from app import agents  # noqa: E402


def _claim(name="claude-code"):
    return agents.create_claim(name)[1]


def _redeem(client, code):
    return client.post("/api/claim", data={"claim": code})


def _docs(monkeypatch):
    from app import ui
    monkeypatch.setattr(ui, "DOC_DIR", os.path.dirname(os.path.dirname(__file__)))


def test_claim_is_single_use_and_does_not_burn_on_get(client, monkeypatch):
    _docs(monkeypatch)
    code = _claim("agent-one")
    page = client.get(f"/install?claim={code}")  # a link previewer / prefetch must not consume it
    assert page.status_code == 200 and code in page.text and "<CLAIM_CODE>" not in page.text
    r = _redeem(client, code)
    assert r.status_code == 200 and r.json()["name"] == "agent-one" and r.json()["token"].startswith("ain_")
    assert r.headers["cache-control"] == "no-store"
    assert _redeem(client, code).status_code == 410  # second use refused


def test_claim_unknown_expired_and_malformed(client, monkeypatch):
    _docs(monkeypatch)
    assert _redeem(client, "x" * 43).status_code == 410
    assert _redeem(client, "").status_code == 410
    code = _claim("old-one")
    with store.db() as c:
        c.execute("UPDATE claims SET expires_at='2000-01-01T00:00:00Z'")
    assert _redeem(client, code).status_code == 410
    bad = client.get("/install?claim=<script>alert(1)</script>")
    assert "<script>alert" not in bad.text and "<CLAIM_CODE>" in bad.text  # only [A-Za-z0-9_-] is substituted


def test_agent_token_works_and_forces_source_agent(client):
    token = _redeem(client, _claim("alice-bot")).json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    r = client.post("/api/push", headers=h, data={"title": "T", "source_agent": "spoofed"},
                    files={"file": ("a.md", b"# hi")})
    assert r.status_code == 201
    assert store.get_item(r.json()["id"])["source_agent"] == "alice-bot"
    # MCP path too
    out = client.post("/mcp", headers={**h, "Accept": "application/json, text/event-stream"}, json={
        "jsonrpc": "2.0", "id": 9, "method": "tools/call",
        "params": {"name": "push_artifact", "arguments": {"title": "M", "content_text": "# x", "source_agent": "spoofed"}}})
    iid = json.loads(out.json()["result"]["content"][0]["text"])["id"]
    assert store.get_item(iid)["source_agent"] == "alice-bot"
    # admin token still works and keeps the caller-supplied name
    r = client.post("/api/push", headers=AUTH, data={"title": "A", "source_agent": "legacy"}, files={"file": ("a.md", b"x")})
    assert store.get_item(r.json()["id"])["source_agent"] == "legacy"


def test_revoke_cuts_off_only_that_agent(client):
    t1 = _redeem(client, _claim("keep-me")).json()["token"]
    t2 = _redeem(client, _claim("drop-me")).json()["token"]
    ids = {a["name"]: a["id"] for a in agents.list_agents() if not a["revoked_at"]}
    assert agents.revoke(ids["drop-me"])
    push = lambda t: client.post("/api/push", headers={"Authorization": f"Bearer {t}"}, data={"title": "t"},
                                 files={"file": ("a.md", b"x")}).status_code
    assert push(t1) == 201 and push(t2) == 401
    assert client.post("/api/push", headers={"Authorization": "Bearer ain_nope"}).status_code == 401


def test_tokens_stored_hashed_and_duplicate_names(client):
    token = _redeem(client, _claim("hash-check")).json()["token"]
    with store.db() as c:
        dump = json.dumps([tuple(r) for r in c.execute("SELECT * FROM agents")]) + \
               json.dumps([tuple(r) for r in c.execute("SELECT * FROM claims")])
    assert token not in dump
    with pytest.raises(store.PushError) as ei:
        agents.create_claim("hash-check")
    assert ei.value.status == 409
    for bad in ("", "  ", "<b>x</b>", "a" * 41):
        with pytest.raises(store.PushError):
            agents.create_claim(bad)


def test_agents_ui(client, monkeypatch):
    origin = {"Origin": "http://inbox.test"}
    r = client.post("/agents/new", data={"name": "ui-made"}, headers=origin)
    assert r.status_code == 200 and "/install?claim=" in r.text and r.headers["cache-control"] == "no-store"
    assert client.post("/agents/new", data={"name": "ui-made2"}, headers={"Origin": "http://evil.test"}).status_code == 403
    page = client.get("/agents")
    assert "ui-made" in page.text and "claim=" not in page.text  # the code is never shown again
    # with UI basic auth on, the agents page is protected but /api/claim stays reachable
    monkeypatch.setenv("INBOX_UI_PASSWORD", "pw")
    assert client.get("/agents").status_code == 401
    assert client.post("/agents/new", data={"name": "x"}).status_code == 401
    assert _redeem(client, "z" * 43).status_code == 410
