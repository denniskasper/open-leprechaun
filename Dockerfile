# Two images from one file, because they ship together: `api` is the Python
# service, `web` is the built client behind the server that also forwards /api.
# deploy/compose.tailnet.yaml builds both; nothing here is used in development,
# where both run on the host (ADR-0002).

# --- api ---
FROM python:3.14-slim AS api

RUN useradd -ms /bin/sh -u 1001 app

# The checkout's own layout, so settings.REPO_ROOT and alembic.ini resolve the
# same paths here as on a laptop.
WORKDIR /app/apps/api

# pip warns that running as root can conflict with the system package manager;
# in this image it cannot — pip installs into /usr/local, Debian's Python lives
# in /usr/lib. The dependencies sit above the source so a code change does not
# reinstall them.
COPY apps/api/requirements.txt ./
RUN pip install --no-cache-dir --root-user-action=ignore -r requirements.txt

COPY apps/api/pyproject.toml apps/api/alembic.ini ./
COPY apps/api/migrations ./migrations
COPY apps/api/src ./src
RUN pip install --no-cache-dir --root-user-action=ignore --no-deps -e .

USER app

ENV PYTHONUNBUFFERED=1

# Loopback only: the container shares the Tailscale sidecar's network
# namespace, and the web server beside it is the one caller. Forwarded headers
# are trusted from that address and no other, so login throttling counts per
# real client (ADR-0015). One worker, because the scheduler runs in-process.
CMD ["uvicorn", "open_leprechaun.main:app", "--host", "127.0.0.1", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --start-interval=2s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)" || exit 1

# --- web: build ---
FROM node:24-slim AS web-build

# No version: corepack reads `packageManager` from package.json.
RUN corepack enable

WORKDIR /app

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/
RUN pnpm install --frozen-lockfile

COPY apps/web apps/web
RUN pnpm build

# --- web ---
FROM caddy:2-alpine AS web

COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY --from=web-build /app/apps/web/dist /srv
