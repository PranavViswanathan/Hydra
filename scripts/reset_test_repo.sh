#!/usr/bin/env bash
# Put the end-to-end test repository back to its vulnerable state (PROJECT.md 16).
#
#   ./scripts/reset_test_repo.sh [owner/repo]
#
# Closes any open agent pull requests, deletes the vulnagent/* branches, and
# force-resets the default branch to the tag `vulnerable-baseline`.
# Appwrite rows for the repository are cleared by scripts/reset_test_rows.py.

set -euo pipefail

REPO="${1:-${VULNAGENT_TEST_REPO:-}}"
BASELINE_TAG="${BASELINE_TAG:-vulnerable-baseline}"

if [[ -z "$REPO" ]]; then
  echo "usage: $0 <owner/repo>   (or set VULNAGENT_TEST_REPO)" >&2
  exit 1
fi

command -v gh >/dev/null || { echo "this script needs the gh CLI" >&2; exit 1; }

echo "Resetting $REPO to $BASELINE_TAG"

echo "- closing open agent pull requests"
gh pr list --repo "$REPO" --label vulnagent --state open --json number \
  --jq '.[].number' | while read -r number; do
  [[ -n "$number" ]] && gh pr close "$number" --repo "$REPO" --delete-branch || true
done

echo "- deleting leftover vulnagent/* branches"
gh api "repos/$REPO/git/matching-refs/heads/vulnagent/" --jq '.[].ref' |
  while read -r ref; do
    [[ -n "$ref" ]] && gh api -X DELETE "repos/$REPO/git/refs/${ref#refs/}" || true
  done

echo "- resetting the default branch to $BASELINE_TAG"
DEFAULT_BRANCH=$(gh repo view "$REPO" --json defaultBranchRef --jq .defaultBranchRef.name)
BASELINE_SHA=$(gh api "repos/$REPO/git/ref/tags/$BASELINE_TAG" --jq .object.sha)
gh api -X PATCH "repos/$REPO/git/refs/heads/$DEFAULT_BRANCH" \
  -f sha="$BASELINE_SHA" -F force=true >/dev/null

echo "Done. Now run: uv run python scripts/reset_test_rows.py $REPO"
