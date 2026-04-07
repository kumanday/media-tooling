#!/usr/bin/env bash
set -euo pipefail

shell_rc="${1:-$HOME/.zshrc}"
tool_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source_line="source \"$tool_root/shell/media-tooling.zsh\""

mkdir -p "$(dirname "$shell_rc")"
touch "$shell_rc"

if grep -Fq "$source_line" "$shell_rc"; then
  echo "Shell helpers already installed in $shell_rc"
  exit 0
fi

{
  printf '\n'
  printf '# Media Tooling shell helpers\n'
  printf '%s\n' "$source_line"
} >> "$shell_rc"

echo "Installed shell helpers into $shell_rc"
echo "Open a new shell or run: source \"$shell_rc\""
