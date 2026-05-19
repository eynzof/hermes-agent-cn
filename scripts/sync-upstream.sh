#!/usr/bin/env bash
# Sync this fork from NousResearch/hermes-agent upstream.
#
# This script never merges upstream directly into main. It creates a
# chore/sync-upstream-* branch, merges upstream/main there, and leaves the
# result for smoke testing and a PR back into origin/main.

set -euo pipefail

UPSTREAM_REMOTE="${UPSTREAM_REMOTE:-upstream}"
ORIGIN_REMOTE="${ORIGIN_REMOTE:-origin}"
BASE_BRANCH="${BASE_BRANCH:-main}"
SYNC_BRANCH="${SYNC_BRANCH:-chore/sync-upstream-$(date +%Y%m%d)}"

if ! git remote get-url "$UPSTREAM_REMOTE" >/dev/null 2>&1; then
  echo "ERROR: no '$UPSTREAM_REMOTE' remote configured. Run:"
  echo "  git remote add upstream https://github.com/NousResearch/hermes-agent.git"
  echo "  git remote set-url --push upstream no_push"
  exit 1
fi

UPSTREAM_PUSH_URL="$(git remote get-url --push "$UPSTREAM_REMOTE" 2>/dev/null || true)"
if [[ "$UPSTREAM_PUSH_URL" != "no_push" ]]; then
  echo "ERROR: '$UPSTREAM_REMOTE' push URL is not blocked."
  echo "Run: git remote set-url --push upstream no_push"
  exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "ERROR: working tree is not clean. Commit or stash first."
  git status --short
  exit 1
fi

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$CURRENT_BRANCH" != "$BASE_BRANCH" ]]; then
  echo "ERROR: not on $BASE_BRANCH (current: $CURRENT_BRANCH). Switch to $BASE_BRANCH first."
  exit 1
fi

echo "Fetching origin and upstream..."
git fetch --prune "$ORIGIN_REMOTE"
git fetch --prune "$UPSTREAM_REMOTE"
git pull --ff-only "$ORIGIN_REMOTE" "$BASE_BRANCH"

AHEAD="$(git rev-list --count "$BASE_BRANCH..$UPSTREAM_REMOTE/$BASE_BRANCH")"
BEHIND="$(git rev-list --count "$UPSTREAM_REMOTE/$BASE_BRANCH..$BASE_BRANCH")"

echo ""
echo "Status:"
echo "  $UPSTREAM_REMOTE/$BASE_BRANCH is $AHEAD commits ahead of $BASE_BRANCH"
echo "  $BASE_BRANCH is $BEHIND commits ahead of $UPSTREAM_REMOTE/$BASE_BRANCH (fork patches)"

if [[ "$AHEAD" -eq 0 ]]; then
  echo ""
  echo "Already up to date with $UPSTREAM_REMOTE/$BASE_BRANCH. Nothing to do."
  exit 0
fi

if git show-ref --verify --quiet "refs/heads/$SYNC_BRANCH"; then
  echo "ERROR: branch '$SYNC_BRANCH' already exists."
  echo "Set a different branch name with: SYNC_BRANCH=chore/sync-upstream-YYYYMMDD-2 $0"
  exit 1
fi

echo ""
echo "Upstream commits since last sync:"
git log --oneline --max-count=20 "$BASE_BRANCH..$UPSTREAM_REMOTE/$BASE_BRANCH"
TOTAL_LINES="$(git log --oneline "$BASE_BRANCH..$UPSTREAM_REMOTE/$BASE_BRANCH" | wc -l | tr -d ' ')"
if [[ "$TOTAL_LINES" -gt 20 ]]; then
  echo "... and $((TOTAL_LINES - 20)) more"
fi

echo ""
read -r -p "Create '$SYNC_BRANCH' and merge $UPSTREAM_REMOTE/$BASE_BRANCH? [y/N] " ANSWER
if [[ "$ANSWER" != "y" && "$ANSWER" != "Y" ]]; then
  echo "Aborted."
  exit 0
fi

git switch -c "$SYNC_BRANCH" "$BASE_BRANCH"

echo ""
if git merge --no-ff "$UPSTREAM_REMOTE/$BASE_BRANCH"; then
  echo ""
  echo "Merge clean. NEXT STEPS:"
  echo "  1. Run smoke tests from MAINTAINING.md"
  echo "  2. Push the sync branch: git push -u origin $SYNC_BRANCH"
  echo "  3. Open a PR from $SYNC_BRANCH into $BASE_BRANCH"
  echo "  4. After merge, tag a runtime-v<kernelVersion>-cn.<revision> release only from verified $BASE_BRANCH"
else
  echo ""
  echo "MERGE CONFLICT. Resolve manually on '$SYNC_BRANCH', then commit."
  echo "See MAINTAINING.md -> Conflict scenarios."
  echo ""
  echo "Conflicted files:"
  git diff --name-only --diff-filter=U
  exit 2
fi
