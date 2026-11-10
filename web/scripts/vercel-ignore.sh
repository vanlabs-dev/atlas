#!/usr/bin/env bash
# Vercel ignored-build step. Vercel runs it from the project root (web/).
# Exit 0 skips the build, exit 1 builds. When the previous deployed commit
# is unknown or missing from the clone, build. A commit message holding
# "[build]" always builds: Vercel runs this step on dashboard redeploys
# too, so a change to the project's environment variables alone would
# otherwise never reach a deployment.
set -u

if [[ "${VERCEL_GIT_COMMIT_MESSAGE:-}" == *"[build]"* ]]; then
  exit 1
fi
prev="${VERCEL_GIT_PREVIOUS_SHA:-}"
if [[ -z "$prev" ]] || ! git cat-file -e "$prev^{commit}" 2>/dev/null; then
  exit 1
fi
if git diff --quiet "$prev" HEAD -- .; then
  exit 0
fi
exit 1
