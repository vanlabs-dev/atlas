#!/usr/bin/env bash
# Vercel ignored-build step. Vercel runs it from the project root (web/).
# Exit 0 skips the build, exit 1 builds. When the previous deployed commit
# is unknown or missing from the clone, build.
set -u

prev="${VERCEL_GIT_PREVIOUS_SHA:-}"
if [[ -z "$prev" ]] || ! git cat-file -e "$prev^{commit}" 2>/dev/null; then
  exit 1
fi
if git diff --quiet "$prev" HEAD -- .; then
  exit 0
fi
exit 1
