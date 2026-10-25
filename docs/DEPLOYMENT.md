# Deployment

## Security model

| Path | Protection |
|---|---|
| `/mcp`, `/api/*` | Bearer token (`READ_API_TOKEN`), enforced by the app. Fails closed if unset. |
| `/install`, `/install/SKILL.md` | Public by design. Token-free setup docs for agents. |
| everything else (web UI) | **None in the app.** Your reverse proxy must authenticate it. |

So do not expose port 8000 to untrusted networks directly. Either keep it on localhost/a private network
(Tailscale, WireGuard), or put it behind a proxy with SSO / basic auth for the UI paths and let `/mcp`, `/api`
and `/install` through (they carry their own protection).

## Setup

```sh
cp .env.example .env            # set READ_API_TOKEN (openssl rand -hex 32) and READ_BASE_URL
mkdir -p data && sudo chown 1000:1000 data
docker compose up -d --build
```

The UI is then on `http://127.0.0.1:8000`.

## Behind a reverse proxy

Two rules are needed: the UI behind auth, and `/mcp` + `/api` + `/install` without it.
`examples/compose.traefik.yml` shows this with Traefik labels (forward-auth middleware for the UI).

Caddy sketch:

```
read.example.com {
    @agents path /mcp* /api/* /install*
    handle @agents { reverse_proxy read:8000 }
    handle {
        basicauth { you <bcrypt-hash> }
        reverse_proxy read:8000
    }
}
```

Set `READ_BASE_URL` to the public URL so returned links and the `/install` page are correct.
Agents outside your private network need `/mcp` to be reachable (e.g. via a tunnel or public hostname);
that path is protected only by the single shared token, so use a long random one and rotate it if leaked.
