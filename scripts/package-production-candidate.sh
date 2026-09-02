#!/usr/bin/env bash

set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
release_sha="${RELEASE_SHA:?Set RELEASE_SHA}"
output_archive="${OUTPUT_ARCHIVE:?Set OUTPUT_ARCHIVE}"

if command -v sha256sum >/dev/null 2>&1; then
  checksum_command=(env LC_ALL=C LANG=C sha256sum)
elif command -v shasum >/dev/null 2>&1; then
  checksum_command=(env LC_ALL=C LANG=C shasum -a 256)
else
  echo "A SHA-256 checksum utility is required." >&2
  exit 1
fi

if [[ ! "$release_sha" =~ ^[0-9a-f]{40}$ ]]; then
  echo "RELEASE_SHA must be a full lowercase Git commit SHA." >&2
  exit 1
fi

if [ "$(git -C "$repository_root" rev-parse HEAD)" != "$release_sha" ]; then
  echo "The checked-out commit does not match RELEASE_SHA." >&2
  exit 1
fi

if [ -n "$(git -C "$repository_root" status --porcelain)" ]; then
  echo "Refusing to package a dirty candidate checkout." >&2
  exit 1
fi

temporary_root="$(mktemp -d)"
trap 'rm -rf "$temporary_root"' EXIT

metadata_root="$temporary_root/metadata"
install -d -m 700 "$metadata_root"

printf '%s\n' "$release_sha" >"$metadata_root/.release-source-sha"

(
  cd "$repository_root"
  while IFS= read -r -d '' tracked_file; do
    "${checksum_command[@]}" "$tracked_file"
  done < <(git ls-files -z)
) >"$metadata_root/.release-files.sha256"

git -C "$repository_root" -c tar.umask=0022 archive \
  --format=tar \
  --output="$temporary_root/candidate.tar" \
  "$release_sha"

candidate_mtime="$(git -C "$repository_root" show -s --format=%ct "$release_sha")"
python3 - \
  "$temporary_root/candidate.tar" \
  "$metadata_root" \
  "$candidate_mtime" <<'PY'
import pathlib
import sys
import tarfile

archive_path = pathlib.Path(sys.argv[1])
metadata_root = pathlib.Path(sys.argv[2])
mtime = int(sys.argv[3])

with tarfile.open(archive_path, mode="a") as archive:
    for name in (".release-source-sha", ".release-files.sha256"):
        path = metadata_root / name
        info = tarfile.TarInfo(name)
        info.size = path.stat().st_size
        info.mode = 0o600
        info.mtime = mtime
        info.uid = 0
        info.gid = 0
        info.uname = "root"
        info.gname = "root"
        with path.open("rb") as metadata:
            archive.addfile(info, metadata)
PY

install -d -m 700 "$(dirname "$output_archive")"
gzip -n -9 -c "$temporary_root/candidate.tar" >"$output_archive"
chmod 600 "$output_archive"

echo "Candidate archive created for $release_sha."
