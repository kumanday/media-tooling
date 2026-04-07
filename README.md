# Media Tooling

Media Tooling is a small toolkit for turning raw media into usable production artifacts.

It helps with:

- transcripts for spoken audio and video
- `.srt` subtitles
- contact sheets for silent screen recordings and demos
- project workspaces for inventories, analysis, storyboards, and rough cuts

It fits podcasts, interviews, tutorials, courses, product videos, shorts, reels, and YouTube uploads.

Transcription uses a platform-appropriate backend:

- Apple Silicon macOS: MLX backend
- other workstations: faster-whisper backend

## Quick start

Clone the repository and run the macOS bootstrap script:

```bash
git clone <toolkit-repo> "$HOME/dev/media-tooling"
cd "$HOME/dev/media-tooling"
./scripts/bootstrap-macos.sh
```

That installs `uv`, `ffmpeg`, Python 3.12, the local environment, and the `extract` and `subtitle` shell helpers.

Create a separate project workspace for each production:

```bash
export TOOLKIT_DIR="$HOME/dev/media-tooling"
export PROJECT_DIR="$HOME/projects/my-project-media"

mkdir -p "$PROJECT_DIR"/{assets/audio,assets/reference,transcripts,subtitles,inventory,analysis,storyboards,rough-cuts}
```

Then use the toolkit from the repository directory:

```bash
cd "$TOOLKIT_DIR"
uv run media-subtitle \
  "/path/to/video.mp4" \
  --backend auto \
  --model small \
  --language en \
  --ffmpeg-bin "$(command -v ffmpeg)" \
  --output-dir "$PROJECT_DIR/transcripts"
```

```bash
cd "$TOOLKIT_DIR"
uv run media-contact-sheet \
  "/path/to/silent-video.mov" \
  --ffmpeg-bin "$(command -v ffmpeg)" \
  --ffprobe-bin "$(command -v ffprobe)"
```

## Typical workflow

1. Gather the source corpus.
2. Split spoken media from silent media and still images.
3. Generate transcripts and subtitles for spoken media.
4. Generate contact sheets for silent media.
5. Write inventories, analysis notes, storyboards, and rough-cut plans in the project workspace.

## Core commands

- `media-subtitle`
  Generate transcript `.txt`, subtitle `.srt`, and structured `.json` from a single audio or video file.
- `media-batch-subtitle`
  Process a manifest of spoken-media files sequentially.
- `media-contact-sheet`
  Generate a contact sheet from a single silent or visual-first video.
- `media-batch-contact-sheet`
  Process a manifest of silent or visual-only videos sequentially.

Shell helpers installed into `~/.zshrc`:

- `extract`
- `subtitle`

Both subtitle commands accept `--backend auto|mlx|faster-whisper`.

## Project boundaries

Keep reusable code in this repository. Keep project outputs in a separate workspace.

Typical setup:

- toolkit directory: `$HOME/dev/media-tooling`
- project workspace: `$HOME/projects/my-project-media`

This repository also creates a few local-only directories during normal use:

- `.venv/` for the local Python environment
- cache directories for downloaded packages and local runtime data

Those directories are generated on demand, safe to delete, and ignored by Git.

## Documentation

- [`docs/SETUP.md`](./docs/SETUP.md)
- [`docs/WORKFLOWS.md`](./docs/WORKFLOWS.md)
- [`docs/EXPORTING.md`](./docs/EXPORTING.md)

## Toolkit skills

Toolkit-local skills live in:

- [`.agents/skills/media-subtitle-pipeline/SKILL.md`](./.agents/skills/media-subtitle-pipeline/SKILL.md)
- [`.agents/skills/media-launch-kit-ingest/SKILL.md`](./.agents/skills/media-launch-kit-ingest/SKILL.md)
