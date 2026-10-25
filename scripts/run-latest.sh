#!/usr/bin/env bash
# Update the app checkout to the latest origin/main, rebuild what changed, and serve.
#
#   scripts/run-latest.sh [dam options] [-- serve options]
#   scripts/run-latest.sh --data-dir "$HOME/Library/Application Support/DigitalArchiveManager-public"
#   scripts/run-latest.sh --archive Demo -- --port 8766 --no-open
#
# The app runs from its own worktree (default <repo>/.claude/worktrees/app, override
# with DAM_APP_DIR), a detached checkout of origin/main, so branch work and builds in
# other checkouts never change the running app. Stop the app with Ctrl+C and run the
# script again to update.
set -euo pipefail

# Everything runs inside main, so bash has read the whole script before the checkout
# below can replace this file.
main() {
  local script_dir repo app head
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  repo="$(cd "$script_dir" && cd "$(git rev-parse --git-common-dir)/.." && pwd)"
  app="${DAM_APP_DIR:-$repo/.claude/worktrees/app}"

  echo "==> Fetching origin/main"
  git -C "$repo" fetch --quiet origin main

  if [ ! -e "$app/.git" ]; then
    echo "==> Creating the app worktree at $app"
    git -C "$repo" worktree add --detach "$app" origin/main
  elif [ -n "$(git -C "$app" status --porcelain --untracked-files=no)" ]; then
    echo "error: $app has local changes; it should only ever hold origin/main." >&2
    git -C "$app" status --short --untracked-files=no >&2
    exit 1
  else
    git -C "$app" checkout --quiet --detach origin/main
  fi
  head="$(git -C "$app" rev-parse HEAD)"
  echo "==> App is at $(git -C "$app" log -1 --format='%h %s')"

  echo "==> Backend: uv sync"
  (cd "$app/backend" && uv sync --quiet)

  # npm ci only when the lockfile changed, the build only when the commit changed.
  local lock_hash lock_stamp="$app/frontend/node_modules/.dam-lock-hash"
  lock_hash="$(git -C "$app" hash-object frontend/package-lock.json)"
  if [ "$(cat "$lock_stamp" 2>/dev/null)" != "$lock_hash" ]; then
    echo "==> Frontend: npm ci"
    (cd "$app/frontend" && npm ci --no-audit --no-fund)
    echo "$lock_hash" > "$lock_stamp"
  fi
  local built_stamp="$app/frontend/dist/.dam-built-from"
  if [ "$(cat "$built_stamp" 2>/dev/null)" != "$head" ]; then
    echo "==> Frontend: npm run build"
    (cd "$app/frontend" && npm run build)
    echo "$head" > "$built_stamp"
  else
    echo "==> Frontend: build is current"
  fi

  # Arguments before a `--` go to dam, the ones after it to `serve`.
  local dam_args=() serve_args=()
  while [ $# -gt 0 ] && [ "$1" != "--" ]; do dam_args+=("$1"); shift; done
  [ $# -gt 0 ] && shift
  serve_args=("$@")

  echo "==> Starting dam"
  cd "$app/backend"
  exec uv run dam ${dam_args[@]+"${dam_args[@]}"} serve ${serve_args[@]+"${serve_args[@]}"}
}

main "$@"
