#!/bin/bash
# Installed by an administrator as /usr/local/sbin/wechat-ci-entry.
# A forced SSH command grants access only to this repository's release operations.
set -euo pipefail
read -r action revision service digest actor extra <<< "${SSH_ORIGINAL_COMMAND:-}"
[[ "$revision" =~ ^[0-9a-f]{40}$ ]] || exit 2
root=/opt/wechat-operation
case "$action" in
  archive)
    [[ "$service" =~ ^(backend|user|admin)$ && "$digest" =~ ^[0-9a-f]{64}$ ]]
    [[ "$actor" =~ ^sha256:[0-9a-f]{64}$ && -z "${extra:-}" ]] || exit 2
    umask 077
    staging=$(mktemp "$root/.deploy-images/ci-archive.XXXXXX")
    trap 'rm -f -- "$staging"' EXIT
    cat > "$staging"
    printf '%s  %s\n' "$digest" "$staging" | sha256sum -c -
    archive="$root/.deploy-images/wechat-ai-$service-git-${revision:0:7}.tar.gz"
    mv -- "$staging" "$archive"
    printf '%s\n' "$actor" > "$archive.image-id"
    ;;
  stage)
    [[ -z "${service:-}${digest:-}${actor:-}${extra:-}" ]] || exit 2
    umask 077
    staging=$(mktemp "$root/.deploy-images/ci-bundle.XXXXXX")
    trap 'rm -f -- "$staging"' EXIT
    cat > "$staging"
    git -C "$root" bundle verify "$staging" >/dev/null
    mv -- "$staging" "$root/.deploy-images/ci-$revision.bundle"
    ;;
  deploy)
    [[ "$service" =~ ^(backend|user|admin)$ && "$digest" =~ ^sha256:[0-9a-f]{64}$ ]]
    [[ "$actor" =~ ^[A-Za-z0-9][A-Za-z0-9-]*$ && -z "${extra:-}" ]] || exit 2
    exec /bin/bash /usr/local/lib/wechat-ci/deploy-ci-release.sh \
      "$revision" "$service" "$digest" "$actor"
    ;;
  *) exit 2 ;;
esac
