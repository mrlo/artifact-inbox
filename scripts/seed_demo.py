#!/usr/bin/env python3
"""Fill a running instance with fictional demo items (for screenshots / trying the UI).

    INBOX_API_TOKEN=... python3 scripts/seed_demo.py [http://127.0.0.1:8000]

Uses only the standard library. Optional: INBOX_UI_USER / INBOX_UI_PASSWORD if the UI has basic auth
(only needed for --mark-done, which uses the web form).
"""
import base64
import json
import os
import sys
import urllib.parse
import urllib.request
import uuid

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
TOKEN = os.environ["INBOX_API_TOKEN"]


def tiny_pdf(title: str, lines: list[str]) -> bytes:
    """A one-page PDF with plain Helvetica text; no dependencies."""
    esc = lambda s: s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    text = [f"BT /F2 20 Tf 56 780 Td ({esc(title)}) Tj ET"]
    y = 744
    for ln in lines:
        text.append(f"BT /F1 11 Tf 56 {y} Td ({esc(ln)}) Tj ET")
        y -= 18
    stream = "\n".join(text).encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>"]
    out, offs = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return bytes(out)


def push(title, category, filename, data, summary, agent):
    b = uuid.uuid4().hex
    fields = {"title": title, "category": category, "summary": summary, "source_agent": agent}
    body = b"".join(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
                    for k, v in fields.items())
    body += (f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
             f'Content-Type: application/octet-stream\r\n\r\n').encode() + data + f"\r\n--{b}--\r\n".encode()
    req = urllib.request.Request(f"{BASE}/api/push", body, {
        "Authorization": f"Bearer {TOKEN}", "Content-Type": f"multipart/form-data; boundary={b}"})
    r = json.load(urllib.request.urlopen(req))
    print("pushed", r["id"], title)
    return r["id"]


def mark_done(item_id):
    h = {"Content-Type": "application/x-www-form-urlencoded", "Origin": BASE}
    if os.environ.get("INBOX_UI_PASSWORD"):
        cred = f'{os.environ.get("INBOX_UI_USER", "admin")}:{os.environ["INBOX_UI_PASSWORD"]}'
        h["Authorization"] = "Basic " + base64.b64encode(cred.encode()).decode()
    urllib.request.urlopen(urllib.request.Request(
        f"{BASE}/i/{item_id}/done", urllib.parse.urlencode({"next": "/"}).encode(), h))


VECTOR = """# Vector stores for a 50k-note knowledge base

**Recommendation:** start with `sqlite-vec`. At this size it is fast enough and adds no new service.

| Option | Ops burden | p95 query (50k, 768-d) | Notes |
|---|---|---|---|
| sqlite-vec | none (extension) | ~12 ms | Same file as your notes DB |
| pgvector | one Postgres | ~8 ms | Worth it if you already run Postgres |
| Qdrant | one container | ~5 ms | Best filtering, most moving parts |

## Why not the others
Anything above 5M vectors changes the answer. Below that, the operational cost dominates the latency difference.

## Next steps
1. Embed the existing notes in batches of 256.
2. Compare recall@10 against a 200-query hand-labelled set.
3. Revisit if the corpus grows past ~500k chunks.
"""

CHECKLIST = """<!doctype html><html><head><meta charset=utf-8><style>
body{font:16px system-ui;max-width:560px;margin:2rem auto;padding:0 1rem;color:#222}
h1{font-size:1.4rem} label{display:block;padding:.45rem 0;border-bottom:1px solid #eee}
h2{font-size:1rem;margin-top:1.4rem;color:#555;text-transform:uppercase;letter-spacing:.05em}
</style></head><body><h1>Weekend trip: packing checklist</h1>
<p>Two nights, mild weather, one hike. Ticks are saved with this item.</p>
<h2>Clothes</h2>
<label><input type=checkbox id=c1> 2 base layers</label><label><input type=checkbox id=c2> Rain shell</label>
<label><input type=checkbox id=c3> Hiking socks (x2)</label>
<h2>Gear</h2>
<label><input type=checkbox id=g1> Headlamp + spare batteries</label><label><input type=checkbox id=g2> Water filter</label>
<label><input type=checkbox id=g3> Offline maps downloaded</label>
<h2>Admin</h2>
<label><input type=checkbox id=a1> Parking permit printed</label>
<script>document.querySelectorAll('input').forEach(function(i){
 i.checked=localStorage.getItem(i.id)==='1';
 i.addEventListener('change',function(){localStorage.setItem(i.id,i.checked?'1':'0')})})</script>
</body></html>"""

BACKUP = """Backup summary, last 7 nights
==============================
mon  ok    12m41s   +1.8 GB
tue  ok    11m02s   +0.4 GB
wed  ok    11m30s   +0.6 GB
thu  WARN  19m55s   +9.2 GB   (large photo import)
fri  ok    12m10s   +0.5 GB
sat  ok    11m48s   +0.3 GB
sun  ok    12m02s   +0.7 GB

Repo size: 214 GB -> 227 GB. Prune scheduled Sunday; no action needed.
"""

JOBS = """# Backend roles shortlist (week 43)

Filtered for remote-friendly, Python or Go, and a posted salary range.

1. **Platform engineer, observability**: Northwind Labs. $150-175k. Go, OpenTelemetry. *Strong match.*
2. **Senior backend engineer**: Harbor & Pine. $140-165k. Python, Postgres. *Good match; on-call heavy.*
3. **Staff engineer, data infra**: Quarry. $175-200k. Python, Kafka. *Stretch; asks for 3 yrs of Kafka.*

Skipped 9 postings with no salary range or a mandatory relocation.
"""

DRAFT = """# Draft: What I learned giving my agents one inbox

*Status: first draft, ~40% done. Needs a stronger opening and one real example.*

When every agent writes its output to a different place (a chat thread, a desktop app, a file on a server),
you stop reading any of it. The fix was boring: one inbox that all of them push to.

## Outline
- The problem: artifacts scattered across tools
- The setup: one container, MCP + REST, bearer token
- What changed: I read more, and I can find things
"""

RFC = """# Notes: HTTP caching RFC (9111)

Key points for the cache-control rewrite:

- `no-cache` means *revalidate before reuse*, not *do not store*. Use `no-store` for that.
- `stale-while-revalidate` is safe to add to static assets.
- Always send `Vary: Accept-Encoding` when compressing.
"""

if __name__ == "__main__":
    push("Vector stores for a 50k-note knowledge base", "research", "vectors.md", VECTOR.encode(),
         "Compares sqlite-vec, pgvector and Qdrant; recommends sqlite-vec at this scale.", "hermes")
    push("Q3 household budget review", "finance", "budget-q3.pdf", tiny_pdf("Q3 household budget review", [
        "Spending vs. plan, July - September", "",
        "Groceries      $1,820   (plan $1,700)   +7%", "Dining out      $  610   (plan $  800)  -24%",
        "Utilities      $  940   (plan $  900)   +4%", "Subscriptions  $  215   (plan $  250)  -14%", "",
        "Proposal 1: cancel two unused subscriptions (-$31/mo).",
        "Proposal 2: move $300/mo of the dining surplus to savings.",
        "Proposal 3: review the electricity plan before winter."]),
         "Quarterly spend by category with three savings proposals.", "claude-code")
    push("Weekend trip: packing checklist", "planning", "packing.html", CHECKLIST.encode(),
         "Interactive checklist; ticks persist.", "hermes")
    push("Backup summary, last 7 nights", "server", "backups.txt", BACKUP.encode(),
         "One slow night (large import); otherwise healthy.", "hermes")
    push("Backend roles shortlist (week 43)", "jobs", "jobs.md", JOBS.encode(),
         "Three matching roles, ranked, with salary ranges.", "research-bot")
    push("Draft: What I learned giving my agents one inbox", "drafts", "draft.md", DRAFT.encode(),
         "First draft of a blog post; needs an opening and an example.", "claude-code")
    done = push("Notes: HTTP caching RFC (9111)", "research", "rfc.md", RFC.encode(),
                "Reference notes for the cache-control rewrite.", "hermes")
    mark_done(done)
