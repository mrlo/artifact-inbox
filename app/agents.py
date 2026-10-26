"""Per-agent tokens and single-use claim links. Only hashes are stored; plaintext is shown once."""
import hashlib
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone

from . import store

CLAIM_TTL_MIN = int(os.environ.get("INBOX_CLAIM_TTL_MIN", "60"))
TOKEN_PREFIX = "ain_"
_NAME_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,39}$")
_TOUCH_EVERY = 60  # seconds between last_used_at writes
_touched: dict[str, float] = {}


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def clean_name(name) -> str:
    name = " ".join(str(name or "").split())
    if not _NAME_OK.match(name):
        raise store.PushError(400, "agent name: 1-40 chars; letters, digits, space, dot, dash, underscore")
    return name


def create_claim(name) -> tuple[str, str]:
    """Return (claim_id, code). The code is shown to the owner once and is valid for CLAIM_TTL_MIN minutes."""
    name = clean_name(name)
    code = secrets.token_urlsafe(32)
    cid = secrets.token_hex(6)
    ts = datetime.now(timezone.utc)
    with store._lock, store.db() as c:
        c.execute("DELETE FROM claims WHERE expires_at < ? OR used_at IS NOT NULL", (_iso(ts - timedelta(days=1)),))
        if c.execute("SELECT 1 FROM agents WHERE name=? AND revoked_at IS NULL", (name,)).fetchone():
            raise store.PushError(409, f"an active agent named {name!r} already exists; revoke it first or pick another name")
        c.execute("INSERT INTO claims(id,code_hash,name,created_at,expires_at) VALUES(?,?,?,?,?)",
                  (cid, _hash(code), name, _iso(ts), _iso(ts + timedelta(minutes=CLAIM_TTL_MIN))))
    return cid, code


def redeem_claim(code: str) -> dict | None:
    """Atomically burn a claim and mint the agent's token. Returns {name, token} or None (unknown/used/expired)."""
    if not code or len(code) > 128:
        return None
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    now = store.now()
    with store._lock, store.db() as c:
        cur = c.execute("UPDATE claims SET used_at=? WHERE code_hash=? AND used_at IS NULL AND expires_at>?",
                        (now, _hash(code), now))
        if cur.rowcount != 1:
            return None
        name = c.execute("SELECT name FROM claims WHERE code_hash=?", (_hash(code),)).fetchone()["name"]
        c.execute("INSERT INTO agents(id,name,token_hash,created_at) VALUES(?,?,?,?)",
                  (secrets.token_hex(6), name, _hash(token), now))
    return {"name": name, "token": token}


def verify_token(token: str) -> str | None:
    """Return the agent name for a live per-agent token, else None."""
    if not token.startswith(TOKEN_PREFIX) or len(token) > 128:
        return None
    h = _hash(token)
    with store.db() as c:
        row = c.execute("SELECT id,name FROM agents WHERE token_hash=? AND revoked_at IS NULL", (h,)).fetchone()
        if not row:
            return None
        if time.monotonic() - _touched.get(row["id"], -1e9) > _TOUCH_EVERY:
            _touched[row["id"]] = time.monotonic()
            c.execute("UPDATE agents SET last_used_at=? WHERE id=?", (store.now(), row["id"]))
    return row["name"]


def list_agents() -> list[dict]:
    with store.db() as c:
        return [dict(r) for r in c.execute(
            "SELECT id,name,created_at,last_used_at,revoked_at FROM agents ORDER BY revoked_at IS NOT NULL, created_at DESC")]


def revoke(agent_id: str) -> bool:
    with store._lock, store.db() as c:
        return c.execute("UPDATE agents SET revoked_at=? WHERE id=? AND revoked_at IS NULL",
                         (store.now(), agent_id)).rowcount == 1


def list_pending() -> list[dict]:
    with store.db() as c:
        return [dict(r) for r in c.execute(
            "SELECT id,name,created_at,expires_at FROM claims WHERE used_at IS NULL AND expires_at>? ORDER BY created_at DESC",
            (store.now(),))]


def cancel_claim(claim_id: str) -> bool:
    with store._lock, store.db() as c:
        return c.execute("DELETE FROM claims WHERE id=? AND used_at IS NULL", (claim_id,)).rowcount == 1
