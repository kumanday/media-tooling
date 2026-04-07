# Media Tooling

Media Tooling helps an agent harness turn raw media into production artifacts.

It covers:

- transcripts for spoken audio and video
- `.srt` subtitles
- contact sheets for silent screen recordings and demos
- project workspaces for inventories, analysis, storyboards, and rough cuts

It fits podcasts, interviews, tutorials, courses, product videos, shorts, reels, and YouTube uploads.

Transcription uses a platform-appropriate backend:

- Apple Silicon macOS: MLX
- other workstations: faster-whisper

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

## Primary workflow

The usual workflow is prompt-driven. You give an agent harness the toolkit, a project workspace, and a source corpus. The harness uses the toolkit commands under the hood and writes project artifacts into the project workspace.

Typical flow:

1. Put the toolkit in `$TOOLKIT_DIR`.
2. Put project-specific outputs in `$PROJECT_DIR`.
3. Point the harness at the raw media folders.
4. Ask it to ingest the corpus, process the media, and produce planning artifacts.

## Prompt patterns

These prompt patterns are the main entry point for the toolkit.

### Ingest a mixed corpus

```text
I have a new media project in $PROJECT_DIR.

Source folders:
- spoken videos: /path/to/spoken
- silent screen recordings: /path/to/silent
- screenshots: /path/to/images

Please:
1. inventory the corpus
2. separate spoken, silent, and image assets
3. create manifests for batch processing
4. process spoken media into transcripts and SRT subtitles
5. process silent media into contact sheets
6. produce short analysis notes in $PROJECT_DIR/analysis

Use sequential processing and keep project outputs out of the toolkit repo.
```

### Build a shot list after ingestion

```text
The corpus has already been processed in $PROJECT_DIR.

Please review:
- transcripts/
- subtitles/
- assets/reference/
- analysis/

Then produce:
1. a short list of the strongest clips
2. a shot list with start time, end time, duration, and purpose
3. a note on what still needs to be recorded
```

### Prepare a rough cut

```text
Please use the processed artifacts in $PROJECT_DIR to prepare a first-pass rough cut plan.

I want:
- a proposed sequence
- which clips should carry narration
- which silent clips should be used as B-roll
- where screenshots are enough
- which sections feel weak or need new A-roll
```

More prompt patterns live in [`docs/WORKFLOWS.md`](./docs/WORKFLOWS.md).

## Toolkit primitives

These are the commands that the harness uses under the hood:

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

If you want direct command examples, see [`docs/WORKFLOWS.md`](./docs/WORKFLOWS.md).

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
