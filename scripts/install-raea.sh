#!/usr/bin/env bash
# Install the raea engine for the media-tooling motion-graphics pilot (see docs/RAEA.md).
#
# Runs raea's own installer pinned to the release this pilot was checked against, and by default leaves raea's agent
# skills out of ~/.claude/skills: the media-motion-raea skill points agents at the copy the release ships in
# ~/.raea/share/raea/skills instead, so installing raea doesn't change what agents load in other sessions.
#
#   RAEA_VERSION=0.1.0-canary.3 ./scripts/install-raea.sh   # another release
#   RAEA_SKILLS=1 ./scripts/install-raea.sh                  # also copy raea's skills into ~/.claude/skills
set -euo pipefail

version="${RAEA_VERSION:-0.1.0-canary.2}"

case "$(uname -s)/$(uname -m)" in
  Darwin/arm64 | Linux/x86_64) ;;
  *) echo "raea runs on Apple Silicon macOS or x86_64 Linux; this is $(uname -s)/$(uname -m)." >&2; exit 1 ;;
esac

for tool in curl ffmpeg ffprobe; do
  command -v "$tool" >/dev/null 2>&1 || { echo "$tool is required." >&2; exit 1; }
done

installer="$(mktemp)"
trap 'rm -f "$installer"' EXIT
curl -fsSL https://raea.io/install -o "$installer"

if [ -n "${RAEA_SKILLS:-}" ]; then
  RAEA_VERSION="$version" sh "$installer"
else
  RAEA_VERSION="$version" RAEA_NO_SKILLS=1 sh "$installer"
fi

raea="${RAEA_PREFIX:-$HOME/.raea}/bin/raea"
"$raea" help >/dev/null
echo "raea: $(cat "${RAEA_PREFIX:-$HOME/.raea}/share/raea/VERSION" 2>/dev/null || echo "$version") at $raea"
echo "Upstream skill: ${RAEA_PREFIX:-$HOME/.raea}/share/raea/skills/raea/SKILL.md"
echo "FFmpeg: $(ffmpeg -version | sed -n '1p')"
