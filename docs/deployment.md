# Deployment

The one deployed instance runs under Dokploy on a server inside a tailnet, and is reachable over
that tailnet only. CI runs the checks on every push and deploys a green `main` (ADR-0002).

Everything the repository can hold is in it: the `Dockerfile`, `deploy/compose.tailnet.yaml`,
`deploy/Caddyfile`, `deploy/serve.json`, `deploy/dokploy-deploy.sh`, `deploy/verify-not-public.sh`
and `.github/workflows/deploy.yml`. What follows is the part that lives outside it, set up once by
hand. The repository is public, so nothing here names the server or the tailnet; those values live
in Dokploy and in repository secrets.

## The shape

One Dokploy **compose** service, built from `deploy/compose.tailnet.yaml`:

| Service | What it is |
|---|---|
| `tailscale` | A sidecar that joins the tailnet as a node of its own and serves HTTPS under its MagicDNS name, with a certificate Tailscale issues. |
| `web` | Caddy: the built client, and `/api` forwarded to the API. |
| `api` | uvicorn, one worker, listening on loopback. |
| `migrate` | Runs `alembic upgrade head` once per deployment and exits; the API starts only after it succeeded. |
| `postgres` | The database, in a named volume. |

`web` and `api` share the sidecar's network namespace and both listen on loopback, so the chain is
Tailscale serve → Caddy (`127.0.0.1:8080`) → uvicorn (`127.0.0.1:8000`). Nothing publishes a port
and no Traefik router exists, so the server's public address has no route to the instance — rather
than a route that is filtered.

uvicorn trusts forwarded headers from `127.0.0.1` and nothing else, and Caddy passes on the
`X-Forwarded-For` it receives only because it comes from loopback. Login throttling therefore
counts per tailnet client (ADR-0015).

## What the stack expects

Set in Dokploy's environment for the service; none has a usable default.

| Variable | Meaning |
|---|---|
| `TS_AUTHKEY` | A Tailscale auth key the sidecar joins with. Needed for the first start only: the node's identity is kept in the `tailscale-state` volume afterwards. |
| `POSTGRES_PASSWORD` | The database password. It becomes part of `DATABASE_URL`, so keep it URL-safe: letters, digits, `-` and `_`. |
| `APPLICATION_SECRET` | The root secret venue credentials and the two-factor secret are encrypted under (ADR-0003, ADR-0005). Back it up outside the server. |
| `TS_HOSTNAME` | Optional, default `leprechaun`: the node's name, and so the first label of the address. |

Generate the two secrets with:

```sh
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

## Tailscale, once

1. **HTTPS certificates** enabled for the tailnet (DNS → HTTPS Certificates), with MagicDNS on.
2. **An auth key** for the sidecar (Settings → Keys): single-use, not ephemeral — the node must
   outlive a restart.
3. **An OAuth client** for CI (Settings → OAuth clients), scope `auth_keys`, tag `tag:ci`.
4. **The policy** lets `tag:ci` reach the Dokploy host's port 3000 and nothing else:

   ```jsonc
   "tagOwners": { "tag:ci": ["autogroup:admin"] },
   "acls": [
     { "action": "accept", "src": ["tag:ci"], "dst": ["<dokploy host>:3000"] }
   ]
   ```

   That rule only narrows anything if no broader one applies: a policy that still carries the
   default `{ "src": ["*"], "dst": ["*:*"] }` lets `tag:ci` reach everything regardless.

Funnel stays off for the node. It is the one switch that would publish the instance.

## Dokploy, once

1. New project, new **Compose** service. Provider: this repository, branch `main`, compose path
   `./deploy/compose.tailnet.yaml`.
2. General → **Auto Deploy: off**. If Dokploy listened to the push, the checks and the deployment
   would race and a red run would ship anyway.
3. Environment: the variables above.
4. No domain. A domain would create the Traefik router this arrangement exists to avoid.
5. Profile → API keys: generate one for the deploy job.

The compose id is the last path segment of the service's URL in Dokploy.

## GitHub Actions, once

Repository → Settings → Secrets and variables → Actions.

**Variables:**

| Name | Value |
|---|---|
| `DOKPLOY_COMPOSE_ID` | from the service's URL in Dokploy |

The deploy job is skipped while this is unset, so pushes to `main` stay green before Dokploy
exists. It has to be a variable: a job condition cannot read secrets.

**Secrets:**

| Name | Value |
|---|---|
| `DOKPLOY_URL` | `http://<dokploy host's MagicDNS name>:3000` |
| `DOKPLOY_API_KEY` | the key generated above |
| `TS_OAUTH_CLIENT_ID`, `TS_OAUTH_SECRET` | the OAuth client above |
| `APP_HOSTNAME` | the instance's MagicDNS name, `<TS_HOSTNAME>.<tailnet>.ts.net` |
| `SERVER_PUBLIC_IP` | the server's public IPv4 address |
| `SERVER_PUBLIC_IPV6` | only if the server has one |

The last four are secrets, not variables, because this repository's logs are public and the
scripts echo them; as secrets they are masked.

## Deploying

A push to `main` runs the three checks, then `deploy`, then `not-public`. `deploy` joins the
tailnet as an ephemeral node, asks Dokploy and waits for the build; a rejected or failed deployment
fails the step and shows what Dokploy replied. `not-public` then asks for the instance from a
runner that is not on the tailnet and fails if anything answers.

To redeploy without a push, re-run the latest workflow run on `main`, or from a machine on the
tailnet:

```sh
DOKPLOY_URL=... DOKPLOY_COMPOSE_ID=... DOKPLOY_API_KEY=... deploy/dokploy-deploy.sh
```

Dokploy builds the head of `main`, not the commit whose checks went green: two pushes in quick
succession can ship the second on the strength of the first.

## A shell in the instance

Dokploy names the containers after the service: `<service>-api-1`, `<service>-postgres-1`, and so
on. On the server:

```sh
docker ps --filter name=-api-1 --format '{{.Names}}'
docker exec -it <service>-api-1 python -m open_leprechaun.disable_two_factor   # docs/runbook.md
```

## Backing up

The database is the `postgres-data` volume and nothing copies it anywhere. Until a scheduled backup
exists, take one by hand before anything risky:

```sh
docker exec <service>-postgres-1 sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > leprechaun.dump
```

A dump restores the ledger; venue credentials and the two-factor secret inside it are readable only
with the same `APPLICATION_SECRET`, so the two are backed up separately and both are needed.
