# Setup

## User install

Install `uv` and `ffmpeg`, then install `media-tooling` as a command provider:

```bash
brew install uv ffmpeg
uv tool install /absolute/path/to/media-tooling
```

If you prefer one-off execution instead of a persistent tool install, use `uvx` with the same package source:

```bash
uvx --from /absolute/path/to/media-tooling media-tooling-init "$HOME/projects/my-project-media"
```

The transcription backend depends on the workstation:

- Apple Silicon macOS installs `lightning-whisper-mlx`
- other systems install `faster-whisper`

## Initialize a project workspace

Create one workspace per production:

```bash
export PROJECT_DIR="$HOME/projects/my-project-media"
media-tooling-init "$PROJECT_DIR"
cd "$PROJECT_DIR"
```

`media-tooling-init` does two things:

- creates the standard project directories
- writes or refreshes a managed block in `AGENTS.md` that points at the central toolkit skills

If `AGENTS.md` already exists, the command updates only its managed block and preserves the rest of the file.

## Recommended project workspace

```text
$PROJECT_DIR/
  AGENTS.md
  assets/
    audio/
    reference/
  transcripts/
  subtitles/
  inventory/
  analysis/
  storyboards/
  rough-cuts/
    assemblies/
    generated-clips/
    manifests/
    specs/
```

## Optional shell helpers for repo checkouts

If you are working from a local checkout and want the convenience shell helpers:

```bash
cd /absolute/path/to/media-tooling
./scripts/install-shell-helpers.sh
source ~/.zshrc
```

Helpers:

- `extract`
- `subtitle`

## Developer checkout

If you are changing `media-tooling` itself, use a repo checkout instead of a tool install:

```bash
git clone <toolkit-repo> "$HOME/dev/media-tooling"
cd "$HOME/dev/media-tooling"
./scripts/bootstrap-macos.sh
```

The bootstrap script installs `uv`, `ffmpeg`, Python 3.12, the local environment, and the shell helpers.

## Operational notes

- spoken media belongs in the subtitle pipeline
- silent screen recordings belong in the contact-sheet pipeline
- large media batches are more stable when processed sequentially
- project artifacts should stay in the project workspace, not the toolkit repository
- subtitle commands accept `--backend auto|mlx|faster-whisper`
