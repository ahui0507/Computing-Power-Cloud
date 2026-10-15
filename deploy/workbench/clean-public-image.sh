#!/bin/sh
# Only run during a public image build, never in a user's running instance.
set -eu
test ! -d /run/platform-shell
test ! -d /run/platform-auth

for directory in /workspace /root /tmp /var/tmp; do
    test ! -L "$directory"
    mkdir -p "$directory"
    find "$directory" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
done
# Keep the distribution's default shell configuration, without build sessions.
cp -a /etc/skel/. /root/
chmod 700 /root
rm -f /etc/ssh/ssh_host_*
find /var/log -type f -exec truncate -s 0 -- {} +
rm -rf /var/lib/apt/lists/*
