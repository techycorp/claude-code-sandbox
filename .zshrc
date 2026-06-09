HISTSIZE=1000000
SAVEHIST=1000000
HISTFILE=/home/node/.zsh_history
setopt HIST_IGNORE_DUPS
setopt SHARE_HISTORY
setopt APPEND_HISTORY

autoload -Uz compinit && compinit
