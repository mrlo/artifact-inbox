# Deployment

## Security model

| Path | Protection |
|---|---|
| `/mcp`, `/api/*` | Bearer token: admin `INBOX_API_TOKEN` or a per-agent token, enforced by the app. Fails closed. |
| `/api/claim` | Public, protected by the single-use claim code in the request. Must be reachable by agents. |
| `/install`, `/install/SKILL.md` | Public by design. Setup docs for agents; `?claim=` only echoes the code you already hold. |
| `/healthz` | Public (health check). |
| everything else (web UI) | HTTP basic auth if `INBOX_UI_PASSWORD` is set (user `INBOX_UI_USER`, default `admin`); otherwise **open**. |

The simplest safe setup: set `INBOX_UI_PASSWORD`, serve over HTTPS. Alternatively keep the port on
localhost or a private network (Tailscale, WireGuard), or leave the password empty and let a proxy do SSO for the
UI paths while letting `/mcp`, `/api` and `/install` through (they carry their own protection).
Basic auth has no lockout; use a long password.

## Setup

```sh
cp .env.example .env            # set INBOX_API_TOKEN (openssl rand -hex 32) and INBOX_BASE_URL
mkdir -p data && sudo chown 1000:1000 data
docker compose up -d --build
```

The UI is then on `http://127.0.0.1:8000`.

## Behind a reverse proxy

With `INBOX_UI_PASSWORD` set, a plain proxy is enough: forward everything. To use SSO instead, leave the password
empty and make two rules: the UI behind your auth, and `/mcp` + `/api` + `/install` without it.
`examples/compose.traefik.yml` shows this with Traefik labels (forward-auth middleware for the UI).

Caddy sketch:

```
inbox.example.com {
    @agents path /mcp* /api/* /install*
    handle @agents { reverse_proxy artifact-inbox:8000 }
    handle {
        basicauth { you <bcrypt-hash> }   # not needed if INBOX_UI_PASSWORD is set
        reverse_proxy artifact-inbox:8000
    }
}
```

Set `INBOX_BASE_URL` to the public URL so returned links and the `/install` page are correct.
Agents outside your private network need `/mcp` to be reachable (e.g. via a tunnel or public hostname);
that path is protected only by the single shared token, so use a long random one and rotate it if leaked.

Install links contain the claim code in the URL, so a proxy access log may record it. It is single-use and short-lived,
so a leaked, already-used link is harmless; keep `INBOX_CLAIM_TTL_MIN` low if you log full URLs.
