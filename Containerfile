FROM rust:slim AS aca-builder
ARG ACA_SAFETY_NET_REF=master
# Commit SHA of ACA_SAFETY_NET_REF; a new value busts the cache for the install below
ARG ACA_SAFETY_NET_SHA=
RUN cargo install --git https://github.com/techycorp/aca-safety-net --branch ${ACA_SAFETY_NET_REF} aca-safety-net

FROM node:20

ARG TZ
ENV TZ="$TZ"

ARG CLAUDE_CODE_VERSION=latest

RUN apt-get update && apt-get install -y --no-install-recommends \
  less \
  git \
  procps \
  sudo \
  fzf \
  zsh \
  man-db \
  unzip \
  gnupg2 \
  gh \
  iptables \
  ipset \
  iproute2 \
  dnsutils \
  aggregate \
  jq \
  nano \
  vim \
  sox \
  libpulse0 \
  libsox-fmt-pulse \
  ca-certificates \
  fonts-liberation \
  libasound2 \
  libatk-bridge2.0-0 \
  libatk1.0-0 \
  libcairo2 \
  libcups2 \
  libdbus-1-3 \
  libdrm2 \
  libexpat1 \
  libgbm1 \
  libglib2.0-0 \
  libgtk-3-0 \
  libnspr4 \
  libnss3 \
  libpango-1.0-0 \
  libpangocairo-1.0-0 \
  libx11-6 \
  libx11-xcb1 \
  libxcb1 \
  libxcomposite1 \
  libxdamage1 \
  libxext6 \
  libxfixes3 \
  libxkbcommon0 \
  libxrandr2 \
  xdg-utils \
  && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /usr/local/share/npm-global && \
  chown -R node:node /usr/local/share

ENV DEVCONTAINER=true

RUN mkdir -p /home/node/.claude && \
  chown -R node:node /home/node/.claude

WORKDIR /home/node

USER node

ENV NPM_CONFIG_PREFIX=/usr/local/share/npm-global
ENV PATH=$PATH:/usr/local/share/npm-global/bin
ENV SHELL=/bin/zsh
ENV EDITOR=nano
ENV VISUAL=nano

RUN npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}

# Headless Chromium for screenshotting dev sites. System deps were installed
# above (as root); this only downloads the browser binary, so it needs no
# sudo/apt access as the node user.
RUN npm install -g playwright && \
  npx playwright install chromium

COPY --from=aca-builder /usr/local/cargo/bin/aca-safety-net /usr/local/bin/
# Enforce the aca-safety-net PreToolUse hook as administrator policy. Managed
# settings live outside ~/.claude (the per-session mount), so they are stable
# across launches and the user cannot drop them. root-owned 0644 via COPY.
COPY managed-settings.json /etc/claude-code/managed-settings.json
COPY .zshrc /home/node/.zshrc
COPY shims/docker /usr/local/bin/docker
COPY shims/xclip /usr/local/bin/xclip
COPY shims/rec /usr/local/bin/rec
COPY init-firewall.sh /usr/local/bin/
COPY fix-claude-perms.sh /usr/local/bin/
COPY start.sh /usr/local/bin/
USER root
RUN chmod +x /usr/local/bin/init-firewall.sh /usr/local/bin/fix-claude-perms.sh \
      /usr/local/bin/start.sh /usr/local/bin/docker /usr/local/bin/xclip /usr/local/bin/rec && \
  printf "node ALL=(root) NOPASSWD: /usr/local/bin/init-firewall.sh\nnode ALL=(root) NOPASSWD: /usr/local/bin/fix-claude-perms.sh\nDefaults env_keep += \"CSB_DEV_NETWORKS\"\n" > /etc/sudoers.d/node-firewall && \
  chmod 0440 /etc/sudoers.d/node-firewall
USER node

# Keep all Claude Code state (incl. .claude.json) inside the mounted ~/.claude
# dir. Without this, .claude.json lands at the home root, which is not mounted,
# so it's wiped on every reinstall and the OAuth login has to be redone.
# Placed last on purpose: an ENV earlier in the file would invalidate the
# Docker layer cache for the steps below it (notably the playwright install).
ENV CLAUDE_CONFIG_DIR=/home/node/.claude

ENTRYPOINT ["/usr/local/bin/start.sh"]
