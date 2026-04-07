# Media Tooling

Media Tooling helps an agent harness turn raw media into production artifacts.

## What it does

Media Tooling gives an agent harness a repeatable media-processing pipeline:

1. Extract audio from spoken video when needed.
2. Generate timestamped transcripts from spoken audio or video.
3. Produce `.srt` subtitles and structured transcript metadata.
4. Generate contact sheets for silent screen recordings and visual demos.
5. Use transcripts, contact sheets, and screenshots to write inventories, analysis notes, shot lists, storyboards, and rough-cut specs.
6. Assemble first-pass rough cuts from reusable project-local specs.

It covers:

- transcripts for spoken audio and video
- `.srt` subtitles
- contact sheets for silent screen recordings and demos
- project workspaces for inventories, analysis, storyboards, and rough cuts
- reusable rough-cut assembly from JSON specs

It fits podcasts, interviews, tutorials, courses, product videos, shorts, reels, and YouTube uploads.

Transcription uses a platform-appropriate backend:

- Apple Silicon macOS: `lightning-whisper-mlx`
- other workstations: `faster-whisper`

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

## Workflow layers

The toolkit works through three layers:

- prompts
  You describe the source material, the output you want, and any constraints such as sequential processing.
- skills
  The harness uses toolkit-local skills to decide which processing path fits the corpus. The main skills are [`media-corpus-ingest`](./.agents/skills/media-corpus-ingest/SKILL.md), [`media-subtitle-pipeline`](./.agents/skills/media-subtitle-pipeline/SKILL.md), and [`media-rough-cut-assembly`](./.agents/skills/media-rough-cut-assembly/SKILL.md).
- toolkit commands
  The skills call the command-line tools that extract audio, generate transcripts and subtitles, build contact sheets, or assemble rough cuts.

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

### Build a rough cut from a project spec

```text
The storyboard and clip choices are already approved in $PROJECT_DIR.

Please:
1. convert the approved sequence into a project-local rough-cut JSON spec
2. use the media-rough-cut skill and command from the toolkit
3. generate placeholder cards with explicit target windows and placeholder durations
4. build the generated clips, concat manifest, and first-pass assembly
5. keep the toolkit reusable and keep all project-specific sequencing in $PROJECT_DIR
```

More prompt patterns live in [`docs/WORKFLOWS.md`](./docs/WORKFLOWS.md).

## Toolkit primitives

These are the commands that the skills use under the hood:

- [`media-corpus-ingest`](./.agents/skills/media-corpus-ingest/SKILL.md)
  Uses the subtitle and contact-sheet commands to ingest a mixed media corpus into a project workspace.
- [`media-subtitle-pipeline`](./.agents/skills/media-subtitle-pipeline/SKILL.md)
  Uses the subtitle commands for spoken-media processing.
- [`media-rough-cut-assembly`](./.agents/skills/media-rough-cut-assembly/SKILL.md)
  Uses a project-local JSON spec to assemble cards, image holds, extracted clips, manifests, and first-pass rough cuts.

- `media-subtitle`
  Generate transcript `.txt`, subtitle `.srt`, and structured `.json` from a single audio or video file.
- `media-batch-subtitle`
  Process a manifest of spoken-media files sequentially.
- `media-contact-sheet`
  Generate a contact sheet from a single silent or visual-first video.
- `media-batch-contact-sheet`
  Process a manifest of silent or visual-only videos sequentially.
- `media-rough-cut`
  Build a first-pass rough cut from a project-local JSON spec of cards, image holds, and clip extracts.

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
- [`.agents/skills/media-corpus-ingest/SKILL.md`](./.agents/skills/media-corpus-ingest/SKILL.md)
- [`.agents/skills/media-rough-cut-assembly/SKILL.md`](./.agents/skills/media-rough-cut-assembly/SKILL.md)
