# Media Tooling

Reusable tooling for media production work.

## Installation

For macOS, the fastest setup is:

```bash
cd "$TOOLKIT_DIR"
./scripts/bootstrap-macos.sh
```

That script installs:

- `uv`
- `ffmpeg`
- Python 3.12 through `uv`
- the local virtual environment
- the shell helpers in `~/.zshrc`

If you want to install the dependencies by hand:

```bash
brew install uv ffmpeg
uv python install 3.12
cd "$TOOLKIT_DIR"
uv sync
./scripts/install-shell-helpers.sh
source ~/.zshrc
```

After installation, these helpers should be available in your shell:

- `extract`
- `subtitle`

## Boundary

This directory is the reusable toolkit layer.

- Reusable code lives here in [`src/media_tooling`](./src/media_tooling)
- Local package environment lives here in [`.venv`](./.venv)
- Cached MLX models live here in [`mlx_models`](./mlx_models)
- Project-specific outputs should live outside this directory

Typical setup:

- toolkit directory: `$HOME/dev/media-tooling`
- project workspace: `$HOME/projects/my-project-media`

The exact location does not matter. Keep the toolkit and the project workspace separate.

## Components

### CLI tools

- `media-subtitle`
  Generate transcript `.txt`, subtitle `.srt`, and structured `.json` from an audio or video file.
- `media-batch-subtitle`
  Process a manifest of spoken-media files sequentially and resume cleanly with `--skip-existing`.
- `media-contact-sheet`
  Generate a lightweight contact sheet `.png` from a video file using evenly spaced frames.
- `media-batch-contact-sheet`
  Process a manifest of silent or visual-only videos sequentially into contact sheets.

### Shell helpers

Installed from `shell/media-tooling.zsh`:

- `extract()`
  Extract `.m4a` audio from a video with `ffmpeg`.
- `subtitle()`
  Wrapper that runs subtitle generation from an audio or video input.

### Code layout

- [`src/media_tooling/subtitle.py`](./src/media_tooling/subtitle.py)
  Single-file transcript and subtitle generation.
- [`src/media_tooling/batch_subtitle.py`](./src/media_tooling/batch_subtitle.py)
  Manifest-driven spoken-media batch processing.
- [`src/media_tooling/contact_sheet.py`](./src/media_tooling/contact_sheet.py)
  Single-file contact-sheet generation for silent or visual-first media.
- [`src/media_tooling/batch_contact_sheet.py`](./src/media_tooling/batch_contact_sheet.py)
  Manifest-driven contact-sheet batch processing.

## Recommended Workflows

### Spoken media

Use when the source has meaningful audio you want to search, subtitle, quote, or caption.

Outputs usually go to:

- `assets/audio/`
- `transcripts/`
- `subtitles/`

Single file:

```bash
cd "$TOOLKIT_DIR"
uv run media-subtitle \
  "/path/to/video.mp4" \
  --model distil-medium.en \
  --language en \
  --ffmpeg-bin "$(command -v ffmpeg)" \
  --output-dir "$PROJECT_DIR/transcripts"
```

Batch:

```bash
cd "$TOOLKIT_DIR"
uv run media-batch-subtitle \
  --inputs-file "$PROJECT_DIR/inventory/spoken-sources.txt" \
  --audio-dir "$PROJECT_DIR/assets/audio" \
  --transcripts-dir "$PROJECT_DIR/transcripts" \
  --subtitles-dir "$PROJECT_DIR/subtitles" \
  --model distil-medium.en \
  --language en \
  --ffmpeg-bin "$(command -v ffmpeg)" \
  --skip-existing
```

### Silent or visual-first media

Use when the source is mostly screen recording, demo footage, or visual reference material.

Outputs usually go to:

- `assets/reference/`
- `inventory/`
- `analysis/`

Single file:

```bash
cd "$TOOLKIT_DIR"
uv run media-contact-sheet \
  "/path/to/silent-video.mov" \
  --ffmpeg-bin "$(command -v ffmpeg)" \
  --ffprobe-bin "$(command -v ffprobe)"
```

Batch:

```bash
cd "$TOOLKIT_DIR"
uv run media-batch-contact-sheet \
  --inputs-file "$PROJECT_DIR/inventory/silent-sources.txt" \
  --output-dir "$PROJECT_DIR/assets/reference" \
  --ffmpeg-bin "$(command -v ffmpeg)" \
  --ffprobe-bin "$(command -v ffprobe)" \
  --skip-existing
```

## Portable setup

One portable pattern is:

```bash
export TOOLKIT_DIR="$HOME/dev/media-tooling"
export PROJECT_DIR="$HOME/projects/my-project-media"

cd "$TOOLKIT_DIR"
uv sync
```

This works for podcasts, interviews, tutorials, shorts, product demos, and course materials.

## Common usage

Single-file helpers from the shell:

```bash
extract "/path/to/video.mp4"
subtitle "/path/to/video.mp4" --output-dir "$PROJECT_DIR/transcripts"
```

Batch work from the toolkit directory:

```bash
cd "$TOOLKIT_DIR"
uv run media-batch-subtitle \
  --inputs-file "$PROJECT_DIR/inventory/spoken-sources.txt" \
  --audio-dir "$PROJECT_DIR/assets/audio" \
  --transcripts-dir "$PROJECT_DIR/transcripts" \
  --subtitles-dir "$PROJECT_DIR/subtitles" \
  --model distil-medium.en \
  --language en \
  --ffmpeg-bin "$(command -v ffmpeg)" \
  --skip-existing
```

```bash
cd "$TOOLKIT_DIR"
uv run media-batch-contact-sheet \
  --inputs-file "$PROJECT_DIR/inventory/silent-sources.txt" \
  --output-dir "$PROJECT_DIR/assets/reference" \
  --ffmpeg-bin "$(command -v ffmpeg)" \
  --ffprobe-bin "$(command -v ffprobe)" \
  --skip-existing
```

## Documentation

- [`docs/EXPORTING.md`](./docs/EXPORTING.md)
- [`docs/AGENT-HARNESS-USAGE-EXAMPLES.md`](./docs/AGENT-HARNESS-USAGE-EXAMPLES.md)
- [`docs/GUIDE-EN.md`](./docs/GUIDE-EN.md)
- [`docs/GUIA-ES.md`](./docs/GUIA-ES.md)

## Toolkit skills

Toolkit-local skills live in:

- [`.agents/skills/media-subtitle-pipeline/SKILL.md`](./.agents/skills/media-subtitle-pipeline/SKILL.md)
- [`.agents/skills/media-launch-kit-ingest/SKILL.md`](./.agents/skills/media-launch-kit-ingest/SKILL.md)

## Operational Notes

- Video inputs for subtitle generation are first converted to `.m4a`.
- Silent videos should generally not go through the subtitle pipeline.
- For large corpora, prefer sequential batch runs over aggressive parallelization.
- Keep reusable code here and keep project artifacts in the project workspace.
