#!/usr/bin/env bash
set -euo pipefail

required_node_major=22

if ! command -v node >/dev/null 2>&1; then
  echo "Node.js >= ${required_node_major} is required for Hyperframes." >&2
  echo "Install Node.js first, then rerun this script." >&2
  exit 1
fi

node_major="$(node -p 'Number(process.versions.node.split(".")[0])')"
if [ "$node_major" -lt "$required_node_major" ]; then
  echo "Node.js >= ${required_node_major} is required for Hyperframes; found $(node --version)." >&2
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required for Hyperframes installation." >&2
  exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg is required for Hyperframes rendering." >&2
  exit 1
fi

if ! command -v ffprobe >/dev/null 2>&1; then
  echo "ffprobe is required for Hyperframes/media-tooling verification." >&2
  exit 1
fi

npm install -g hyperframes@latest

export HYPERFRAMES_NO_TELEMETRY=1
export HYPERFRAMES_NO_UPDATE_CHECK=1
export HYPERFRAMES_NO_AUTO_INSTALL=1

hyperframes telemetry disable >/dev/null 2>&1 || true

echo "Hyperframes: $(hyperframes --version)"
echo "Node.js: $(node --version)"
echo "FFmpeg: $(ffmpeg -version | sed -n '1p')"
echo "FFprobe: $(ffprobe -version | sed -n '1p')"
echo "Run 'hyperframes doctor' for a fuller local environment check."
