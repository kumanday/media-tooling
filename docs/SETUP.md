# Setup

## User install

Install `uv` and `ffmpeg`, then install `media-tooling` as a command provider:

```bash
brew install uv ffmpeg
uv tool install git+https://github.com/kumanday/media-tooling
```

If you prefer one-off execution instead of a persistent tool install, use `uvx` with the same package source:

```bash
uvx --from git+https://github.com/kumanday/media-tooling media-tooling-init "$HOME/projects/my-project-media"
```

For private access or SSH-based installs, use `git+ssh://git@github.com/kumanday/media-tooling`.

The transcription backend depends on the workstation:

- Apple Silicon macOS installs `lightning-whisper-mlx`
- other systems install `faster-whisper`

## Optional Hyperframes install

Install Hyperframes when project workflows need HTML-rendered video, animated overlays, website/UI captures, GIFs, or batch-rendered motion graphics.

From a media-tooling checkout:

```bash
./scripts/install-hyperframes.sh
hyperframes doctor
```

Manual install:

```bash
brew install node ffmpeg
npm install -g hyperframes@latest
hyperframes telemetry disable
hyperframes doctor
```

Hyperframes requires Node.js 22 or newer plus FFmpeg and FFprobe. See [docs/HYPERFRAMES.md](HYPERFRAMES.md) for the project workflow.

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

The bootstrap script installs `uv`, `ffmpeg`, Node.js, Hyperframes, Python 3.12, the local environment, and the shell helpers.

## Operational notes

- spoken media belongs in the subtitle pipeline
- silent screen recordings belong in the contact-sheet pipeline
- large media batches are more stable when processed sequentially
- project artifacts should stay in the project workspace, not the toolkit repository
- subtitle commands accept `--backend auto|mlx|faster-whisper`
