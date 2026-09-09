#!/bin/sh
set -eu

if [ "$#" -lt 3 ] || [ "$#" -gt 4 ]; then
  echo "Usage: $0 <user|admin|backend> <current-git-tag> <previous-git-tag> [image-repository]" >&2
  exit 2
fi

case "$1" in
  user) image="wechat-ai-user" ;;
  admin) image="wechat-ai-admin" ;;
  backend) image="wechat-ai-backend" ;;
  *) echo "Unknown service: $1" >&2; exit 2 ;;
esac

current_tag="$2"
previous_tag="$3"
repository=${4:-$image}
case "$repository" in
  "$image"|*/"$image") ;;
  *) echo "Repository must end with $image: $repository" >&2; exit 2 ;;
esac

for tag in "$current_tag" "$previous_tag"; do
  if ! printf '%s\n' "$tag" | grep -Eq '^git-[0-9a-f]{7,40}$'; then
    echo "Invalid release tag: $tag" >&2
    exit 2
  fi
  docker image inspect "$repository:$tag" >/dev/null
done

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
repository_dir=$(dirname -- "$script_dir")
archive_dir="$repository_dir/.deploy-images"

docker image ls "$repository" --format '{{.Repository}}:{{.Tag}}' | while IFS= read -r reference; do
  tag=${reference#*:}
  case "$tag" in
    git-*)
      if [ "$tag" != "$current_tag" ] && [ "$tag" != "$previous_tag" ]; then
        docker image rm "$reference"
      fi
      ;;
  esac
done

if [ -d "$archive_dir" ]; then
  for archive in "$archive_dir/$image"-git-*.tar; do
    [ -e "$archive" ] || continue
    case "$(basename -- "$archive")" in
      "$image-$current_tag.tar"|"$image-$previous_tag.tar") ;;
      *) rm -- "$archive" ;;
    esac
  done
fi

echo "Kept $repository:$current_tag and $repository:$previous_tag; removed older release images and archives."
