#!/bin/bash
# Trust the agent-vault MITM CA (piped in on stdin) so the agent's TLS to
# upstreams, re-signed by the broker, validates. Installs to the system store
# (curl/python), a node-readable copy (NODE_EXTRA_CA_CERTS), and the path
# `agent-vault run` points node at.
set -euo pipefail
CERT=/usr/local/share/ca-certificates/agent-vault-ca.crt
cat > "$CERT"
update-ca-certificates
cp "$CERT" /home/node/.agent-vault-ca.crt
mkdir -p /home/node/.agent-vault
cp "$CERT" /home/node/.agent-vault/mitm-ca.pem
chown -R node:node /home/node/.agent-vault-ca.crt /home/node/.agent-vault
