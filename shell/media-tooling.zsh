# Media Tooling shell helpers for zsh.

if [[ -z "${MEDIA_TOOLING_DIR:-}" ]]; then
  typeset -g MEDIA_TOOLING_DIR="${${(%):-%N}:A:h:h}"
fi

extract() {
  if [[ $# -lt 1 ]]; then
    echo "usage: extract <video-file>" >&2
    return 1
  fi

  local ffmpeg_bin="${FFMPEG_BIN:-$(command -v ffmpeg)}"
  if [[ -z "$ffmpeg_bin" ]]; then
    echo "ffmpeg not found in PATH" >&2
    return 1
  fi

  "$ffmpeg_bin" -i "$1" -vn -acodec copy "${1%.*}.m4a"
}

subtitle() {
  if [[ $# -lt 1 ]]; then
    echo "usage: subtitle <media-file> [media-subtitle args...]" >&2
    return 1
  fi

  local tool_root="${MEDIA_TOOLING_DIR:-$HOME/dev/media-tooling}"
  local uv_bin="${UV_BIN:-$(command -v uv)}"
  local ffmpeg_bin="${FFMPEG_BIN:-$(command -v ffmpeg)}"
  local input="$1"
  shift

  if [[ ! -d "$tool_root" ]]; then
    echo "media-tooling directory not found: $tool_root" >&2
    return 1
  fi

  if [[ -z "$uv_bin" ]]; then
    echo "uv not found in PATH" >&2
    return 1
  fi

  if [[ -z "$ffmpeg_bin" ]]; then
    echo "ffmpeg not found in PATH" >&2
    return 1
  fi

  (
    cd "$tool_root" || exit 1
    "$uv_bin" run media-subtitle "$input" --ffmpeg-bin "$ffmpeg_bin" "$@"
  )
}
