#!/bin/bash
set -e
rm -f /tmp/csb-entrypoint-ready
sudo /usr/local/bin/fix-claude-perms.sh
sudo /usr/local/bin/init-firewall.sh
touch /tmp/csb-entrypoint-ready

# Create symlinks in home dir for each mounted path
if [ -n "$CSB_MOUNTS" ]; then
    IFS=':' read -ra paths <<< "$CSB_MOUNTS"
    for path in "${paths[@]}"; do
        name=$(basename "$path")
        ln -sfn "$path" "/home/node/$name"
    done
fi

exec zsh "$@"
