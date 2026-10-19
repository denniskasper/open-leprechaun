# The AFK agent's sandbox: Python 3.14 for the API, Node 24 + pnpm for the
# web client and Claude Code. No `gh` and no GitHub token — the host
# orchestrator (main.mts) does every GitHub read and write, so the agent can
# change code but not the repo's issues or branches on GitHub.
FROM python:3.14-bookworm

RUN apt-get update && apt-get install -y \
  git \
  curl \
  jq \
  && rm -rf /var/lib/apt/lists/*

# Node from the official image rather than a distro package, matching the
# version the root Dockerfile builds the web client with.
COPY --from=node:24-bookworm /usr/local/bin/node /usr/local/bin/node
COPY --from=node:24-bookworm /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
  && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
  && npm install --global pnpm@11.10.0

# Build-args for UID/GID alignment: sandcastle docker build-image
# defaults these to the host user's UID/GID so image-built files
# and bind-mounted files share an owner without runtime chown.
ARG AGENT_UID=1000
ARG AGENT_GID=1000

RUN groupadd -o -g $AGENT_GID agent \
  && useradd -o -m -u $AGENT_UID -g $AGENT_GID -d /home/agent -s /bin/bash agent

# Chromium and the system libraries it needs, so the agent can run the
# Playwright e2e suite. The version matches @playwright/test in
# apps/web/package.json; the sandbox setup hook installs the browser again
# if the two ever drift, which is why the agent owns the browsers directory.
ARG PLAYWRIGHT_VERSION=1.62.1
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN npx --yes playwright@${PLAYWRIGHT_VERSION} install --with-deps chromium \
  && rm -rf /var/lib/apt/lists/* /root/.npm \
  && chown -R ${AGENT_UID}:${AGENT_GID} /ms-playwright

USER ${AGENT_UID}:${AGENT_GID}

# Created here so the bind-mounted caches main.mts adds land in directories
# the agent owns, not ones Docker creates as root.
RUN mkdir -p /home/agent/.cache/pip /home/agent/.local/share/pnpm/store

RUN curl -fsSL https://claude.ai/install.sh | bash

ENV PATH="/home/agent/.local/bin:$PATH"

WORKDIR /home/agent

# In worktree sandbox mode, Sandcastle bind-mounts the git worktree at /home/agent/workspace
# and overrides the working directory to /home/agent/workspace at container start.
ENTRYPOINT ["sleep", "infinity"]
