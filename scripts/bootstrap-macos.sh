#!/usr/bin/env bash
set -euo pipefail

tool_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is required. Install it from https://brew.sh and rerun this script." >&2
  exit 1
fi

brew install uv ffmpeg

if command -v uv >/dev/null 2>&1; then
  uv python install 3.12
fi

cd "$tool_root"
uv sync
"$tool_root/scripts/install-shell-helpers.sh"

echo
echo "Media Tooling bootstrap completed."
echo "Toolkit root: $tool_root"
echo "Next step: source ~/.zshrc and run 'subtitle <media-file>' or 'uv run media-subtitle --help'"
