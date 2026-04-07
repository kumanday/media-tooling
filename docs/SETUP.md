# Setup

## macOS bootstrap

The fastest setup path is:

```bash
git clone <toolkit-repo> "$HOME/dev/media-tooling"
cd "$HOME/dev/media-tooling"
./scripts/bootstrap-macos.sh
```

The bootstrap script installs:

- `uv`
- `ffmpeg`
- Python 3.12 through `uv`
- the local virtual environment
- the shell helpers from `shell/media-tooling.zsh`

The transcription backend depends on the workstation:

- Apple Silicon macOS installs `lightning-whisper-mlx`
- other systems install `faster-whisper`

## Manual setup

If you prefer to do it step by step:

```bash
brew install uv ffmpeg
uv python install 3.12
cd "$HOME/dev/media-tooling"
uv sync
./scripts/install-shell-helpers.sh
source ~/.zshrc
```

## Shell helpers

After setup, these helpers should be available in your shell:

### `extract`

Extract audio from a video into `.m4a`.

```bash
extract "/path/to/video.mp4"
```

### `subtitle`

Run subtitle generation from audio or video.

```bash
subtitle "/path/to/video.mp4" --output-dir "$PROJECT_DIR/transcripts"
```

## Local directories

This repository creates a few local-only directories during normal use.

### `.venv/`

The local Python environment used by `uv`.

### Cache directories

Package caches and downloaded runtime data may appear after the first run.

These files are not source code and they should not be committed.

## Recommended environment variables

Most examples in this repo assume:

```bash
export TOOLKIT_DIR="$HOME/dev/media-tooling"
export PROJECT_DIR="$HOME/projects/my-project-media"
```

## Recommended project workspace

Create one workspace per production:

```text
$PROJECT_DIR/
  assets/
    audio/
    reference/
  transcripts/
  subtitles/
  inventory/
  analysis/
  storyboards/
  rough-cuts/
```

## Operational notes

- Spoken media belongs in the subtitle pipeline.
- Silent screen recordings belong in the contact-sheet pipeline.
- Large media batches are more stable when processed sequentially.
- Project artifacts should stay outside the toolkit repository.
- Subtitle commands accept `--backend auto|mlx|faster-whisper`.
