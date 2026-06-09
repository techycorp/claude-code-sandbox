FROM rust:slim AS aca-builder
ARG ACA_SAFETY_NET_REF=master
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
  && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /usr/local/share/npm-global && \
  chown -R node:node /usr/local/share

ENV DEVCONTAINER=true

RUN mkdir -p /workspaces /home/node/.claude && \
  chown -R node:node /workspaces /home/node/.claude

WORKDIR /workspaces

USER node

ENV NPM_CONFIG_PREFIX=/usr/local/share/npm-global
ENV PATH=$PATH:/usr/local/share/npm-global/bin
ENV SHELL=/bin/zsh
ENV EDITOR=nano
ENV VISUAL=nano

RUN npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}

COPY --from=aca-builder /usr/local/cargo/bin/aca-safety-net /usr/local/bin/
COPY .zshrc /home/node/.zshrc
COPY shims/podman /usr/local/bin/podman
COPY shims/docker /usr/local/bin/docker
COPY shims/rec /usr/local/bin/rec
COPY init-firewall.sh /usr/local/bin/
COPY start.sh /usr/local/bin/
USER root
RUN chmod +x /usr/local/bin/init-firewall.sh /usr/local/bin/start.sh \
      /usr/local/bin/podman /usr/local/bin/docker /usr/local/bin/rec && \
  echo "node ALL=(root) NOPASSWD: /usr/local/bin/init-firewall.sh" > /etc/sudoers.d/node-firewall && \
  chmod 0440 /etc/sudoers.d/node-firewall
USER node

ENTRYPOINT ["/usr/local/bin/start.sh"]
