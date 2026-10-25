import base64
import json
import os
import sys
import tempfile

import pytest

os.environ["READ_DATA_DIR"] = tempfile.mkdtemp()
os.environ["READ_API_TOKEN"] = "t" * 64
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from starlette.testclient import TestClient  # noqa: E402

from app import server, store  # noqa: E402

AUTH = {"Authorization": "Bearer " + "t" * 64}
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


@pytest.fixture(scope="module")
def client():
    with TestClient(server.app, base_url="http://read.test") as c:
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
    ok = {"Origin": "http://read.test"}
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
    assert "<READ_API_TOKEN>" in r.text and "t" * 64 not in r.text
    assert client.get("/install/SKILL.md").text.startswith("---\nname: read-inbox")
    assert "read.example.com" not in r.text and ui.BASE_URL in r.text


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
