#!/bin/bash
# Installed by an administrator; invoked only through the dedicated forced SSH command.
set -euo pipefail
revision=$1 service=$2 digest=$3 actor=$4
[[ "$revision" =~ ^[0-9a-f]{40}$ && "$digest" =~ ^sha256:[0-9a-f]{64}$ ]] || exit 2
[[ "$actor" =~ ^[A-Za-z0-9][A-Za-z0-9-]*$ ]] || exit 2
cd /opt/wechat-operation
exec 9>.deploy-images/user-release.lock
flock -w 300 9
[[ -z "$(git status --porcelain)" ]] || { echo 'Production checkout is dirty.' >&2; exit 1; }
case "$service" in
  backend) version_key=BACKEND_VERSION; repository_key=BACKEND_IMAGE_REPOSITORY
    services=(backend-api worker scheduler) ;;
  user) version_key=USER_WEB_VERSION; repository_key=USER_WEB_IMAGE_REPOSITORY
    services=(user-web) ;;
  admin) version_key=ADMIN_WEB_VERSION; repository_key=ADMIN_WEB_IMAGE_REPOSITORY
    services=(admin-web) ;;
  *) exit 2 ;;
esac
repository="ghcr.io/eors583/wechat-ai-$service"
tag="git-${revision:0:7}"
previous_tag=$(sed -n "s/^$version_key=//p" .env.server)
previous_repository=$(sed -n "s/^$repository_key=//p" .env.server)
previous_repository=${previous_repository:-wechat-ai-$service}
[[ "$previous_tag" =~ ^git-[0-9a-f]{7,40}$ ]] || exit 2
[[ "$previous_repository" =~ ^[a-z0-9./_-]+$ ]] || exit 2
bundle=".deploy-images/ci-$revision.bundle"
git fetch "$bundle" HEAD
[[ "$(git rev-parse FETCH_HEAD)" = "$revision" ]] || exit 2
git merge-base --is-ancestor HEAD "$revision" || {
  echo 'Target is older than, or diverges from, the production checkout.' >&2; exit 1;
}
previous_revision=$(git rev-parse "${previous_tag#git-}^{commit}")
if [[ "$service" = backend ]] && ! git diff --quiet "$previous_revision" "$revision" \
  -- services/platform-backend/migrations; then
  echo 'Database migrations changed. Complete the documented backup and one-shot migration before releasing.' >&2
  exit 1
fi
docker image inspect "$previous_repository:$previous_tag" >/dev/null
export DOCKER_CONFIG
DOCKER_CONFIG=$(mktemp -d)
trap 'rm -rf -- "$DOCKER_CONFIG"; rm -f -- "$bundle"' EXIT
# The deploy job supplies a short-lived, read-only package token over encrypted stdin.
archive=".deploy-images/wechat-ai-$service-$tag.tar.gz"
delivery=registry
if [[ -f "$archive" && -f "$archive.image-id" ]]; then
  # The runner pulled this exact registry digest, then delivered a SHA-256 checked archive.
  cat >/dev/null
  docker load --input "$archive"
  # Classic Docker reports the config digest as Id; the containerd store may report
  # a manifest digest. Compare the original config and unpacked layers instead.
  python3 - "$archive" "$repository:$tag" <<'PY'
import hashlib
import json
import subprocess
import sys
import tarfile
from pathlib import Path
archive, image = sys.argv[1:]
expected = Path(archive + '.image-id').read_text().strip()
with tarfile.open(archive, 'r:gz') as bundle:
    manifest = json.load(bundle.extractfile('manifest.json'))
    entry = next(item for item in manifest if image in (item.get('RepoTags') or []))
    raw_config = bundle.extractfile(entry['Config']).read()
if 'sha256:' + hashlib.sha256(raw_config).hexdigest() != expected:
    raise SystemExit('Archive image configuration checksum mismatch.')
config = json.loads(raw_config)
loaded = json.loads(subprocess.check_output(['docker', 'image', 'inspect', image]))[0]
if loaded['RootFS']['Layers'] != config['rootfs']['diff_ids']:
    raise SystemExit('Loaded image filesystem layers do not match the archive.')
PY
  delivery=github-ssh-archive
else
  if ! timeout 45 docker login ghcr.io --username "$actor" --password-stdin \
    || ! timeout 180 docker pull "$repository@$digest"; then
    echo 'Registry pull unavailable or timed out; request the verified GitHub archive.' >&2
    exit 75
  fi
  docker tag "$repository@$digest" "$repository:$tag"
fi
[[ "$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$repository:$tag")" = linux/amd64 ]]
[[ "$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$repository:$tag")" = "$revision" ]]
record=".deploy-images/ci-$service-$tag-rollback.txt"
printf '%s\n' "$repository_key=$previous_repository" "$version_key=$previous_tag" \
  "target=$repository:$tag" "digest=$digest" "delivery=$delivery" > "$record"
docker image inspect --format '{{.Id}} {{.RepoTags}}' "$previous_repository:$previous_tag" >> "$record"
git merge --ff-only "$revision"
compose=(docker compose --env-file .env.server -f deploy/compose/compose.server-preview.yml)
set_version() {
  python3 - "$repository_key" "$1" "$version_key" "$2" <<'PY'
import os
import stat
import sys
import tempfile
from pathlib import Path
path = Path('.env.server')
updates = dict(zip(sys.argv[1::2], sys.argv[2::2]))
lines = []
for line in path.read_text().splitlines():
    key = line.partition('=')[0]
    if key in updates:
        continue
    lines.append(line)
lines.extend(f'{key}={value}' for key, value in updates.items())
fd, name = tempfile.mkstemp(prefix='.env.server.', dir='.')
try:
    os.fchmod(fd, stat.S_IMODE(path.stat().st_mode))
    with os.fdopen(fd, 'w') as out:
        out.write('\n'.join(lines) + '\n')
    os.replace(name, path)
finally:
    if os.path.exists(name):
        os.unlink(name)
PY
}
set_version "$repository" "$tag"
if ! "${compose[@]}" up -d --no-build --no-deps --force-recreate "${services[@]}" \
  || ! "${compose[@]}" restart gateway; then
  set_version "$previous_repository" "$previous_tag"
  "${compose[@]}" up -d --no-build --no-deps --force-recreate "${services[@]}"
  "${compose[@]}" restart gateway
  echo "Service switch failed; restored $previous_repository:$previous_tag" >&2
  exit 1
fi
for name in "${services[@]}"; do
  docker inspect --format '{{.Name}} {{.Config.Image}} {{.State.Status}}' "$("${compose[@]}" ps -q "$name")"
done
# Give the previous image a local registry alias for pruning, preserving its original reference.
if [[ "$previous_repository" != "$repository" ]]; then
  docker tag "$previous_repository:$previous_tag" "$repository:$previous_tag"
fi
bash scripts/prune-release-images.sh "$service" "$tag" "$previous_tag" "$repository"
# Compressed CI archives are delivery files; loaded current/previous Docker images are retained.
rm -f -- "$archive" "$archive.image-id"
printf '%s\n' 'Service switched; previous image retained. Functional tests not run.'
