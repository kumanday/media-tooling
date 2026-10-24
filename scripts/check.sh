#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT_DIR"

# Tests run with a throwaway HOME (and no inherited agent or media-tooling config dirs), so a test that falls back
# to a default path cannot write into the real ~/.agents, ~/.claude or ~/.gemini. The skill links there are also
# compared before and after, in case something reaches them another way.
skill_links() {
  local dir entry
  for dir in "$HOME/.agents/skills" "$HOME/.claude/skills" "$HOME/.gemini/skills" \
             "$HOME/.gemini/antigravity/skills" "$HOME/.gemini/antigravity-cli/skills"; do
    [ -d "$dir" ] || continue
    for entry in "$dir"/*; do
      [ -L "$entry" ] && printf '%s -> %s\n' "$entry" "$(readlink "$entry")"
    done
  done
  return 0
}
TEST_HOME="$(mktemp -d)"
trap 'rm -rf "$TEST_HOME"' EXIT
links_before="$(skill_links)"

uv run --group dev env HOME="$TEST_HOME" CLAUDE_CONFIG_DIR= \
  MEDIA_TOOLING_CONFIG_DIR="$TEST_HOME/.config/media-tooling" MEDIA_TOOLING_CACHE_DIR="$TEST_HOME/.cache/media-tooling" \
  python -m unittest discover -s tests -v

if [ "$(skill_links)" != "$links_before" ]; then
  echo "The test run changed skill links in the real home:" >&2
  diff <(printf '%s\n' "$links_before") <(skill_links) >&2 || true
  exit 1
fi

uv run --group dev ruff check .
uv run --group dev mypy src tests
