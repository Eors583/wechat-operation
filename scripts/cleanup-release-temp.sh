#!/bin/sh
# Daily cleanup of abandoned deployment delivery files; rollback records stay intact.
set -eu
cd /opt/wechat-operation/.deploy-images
exec 9>user-release.lock
flock -n 9 || exit 0
find . -maxdepth 1 -type f -mtime +7 \( \
  -name 'ci-*.bundle' -o -name 'ci-bundle.*' -o -name 'ci-archive.*' -o \
  -name 'wechat-ai-backend-git-*.tar*' -o \
  -name 'wechat-ai-user-git-*.tar*' -o \
  -name 'wechat-ai-admin-git-*.tar*' \
\) -print -delete
