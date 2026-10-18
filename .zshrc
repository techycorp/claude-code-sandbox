HISTSIZE=1000000
SAVEHIST=1000000
HISTFILE=/home/node/.zsh_history
setopt HIST_IGNORE_DUPS
setopt SHARE_HISTORY
setopt APPEND_HISTORY

autoload -Uz compinit && compinit

# Claude Code shortcuts. When csb has dropped an agent-vault session token, route
# claude's egress through the broker (so real credentials never enter the
# sandbox); otherwise run claude directly. ccr resumes; a trailing arg picks a
# session (e.g. `ccr <session-id>`), otherwise it opens the resume picker.
_av_token=/home/node/.claude/.av-token

cc() {
  if [ -r "$_av_token" ]; then
    AGENT_VAULT_ADDR="http://host.docker.internal:14321" \
    AGENT_VAULT_TOKEN="$(cat "$_av_token")" \
    NODE_EXTRA_CA_CERTS=/home/node/.agent-vault-ca.crt \
      agent-vault run --isolation host -- claude --dangerously-skip-permissions "$@"
  else
    claude --dangerously-skip-permissions "$@"
  fi
}

ccr() { cc --resume "$@"; }
