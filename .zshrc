HISTSIZE=1000000
SAVEHIST=1000000
HISTFILE=/home/node/.zsh_history
setopt HIST_IGNORE_DUPS
setopt SHARE_HISTORY
setopt APPEND_HISTORY

autoload -Uz compinit && compinit

# Claude Code shortcuts. ccr resumes; a trailing arg picks a session
# (e.g. `ccr <session-id>`), otherwise it opens the resume picker.
alias cc='claude --dangerously-skip-permissions'
alias ccr='claude --dangerously-skip-permissions --resume'
