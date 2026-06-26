# Exporting Media Tooling

This guide turns the toolkit into something you can hand to another editor on a different Mac.

## The simplest export path

Put `media-tooling` in its own Git repository.

That repository should include:

- `README.md`
- `pyproject.toml`
- `uv.lock`
- `src/`
- `shell/`
- `scripts/`
- `docs/`
- `.gitignore`

That repository should not include:

- `.venv/`
- `.cache/`
- project-specific transcripts, subtitles, or rough cuts

Those exclusions are already covered in `.gitignore`.

## Recommended repository shape

```text
media-tooling/
  docs/
  scripts/
  shell/
  src/
  .gitignore
  README.md
  pyproject.toml
  uv.lock
```

## Suggested export workflow

1. Copy `media-tooling/` into its own clean directory if needed.
2. Initialize a Git repository.
3. Commit only the reusable toolkit files.
4. Push the repository to GitHub.
5. Ask the editor to clone the repository and run the bootstrap script.

Example:

```bash
export SOURCE_DIR="$HOME/path/to/current/media-tooling"
export EXPORT_DIR="$HOME/dev/media-tooling"

mkdir -p "$EXPORT_DIR"
cd "$SOURCE_DIR"
git archive HEAD | tar -x -C "$EXPORT_DIR"

cd "$EXPORT_DIR"
git init -b main
git add .
git commit -m "Initial media-tooling export"
```

If you use GitHub CLI, the next step can be:

```bash
cd "$EXPORT_DIR"
gh repo create your-org/media-tooling --private --source=. --push
```

On another Mac:

```bash
git clone <your-new-repo-url> "$HOME/dev/media-tooling"
cd "$HOME/dev/media-tooling"
./scripts/bootstrap-macos.sh
```

## What another editor will need

The editor needs:

- a Mac
- Homebrew
- access to the repository
- source media files on his machine

The bootstrap script installs:

- `uv`
- `ffmpeg`
- Python 3.12 through `uv`
- the local virtual environment
- the `extract` and `subtitle` shell helpers

## How to keep projects separate

The toolkit repository should stay reusable.

Each production should live in its own workspace outside the repository. Examples:

- `$HOME/projects/podcast-episode-12-media`
- `$HOME/projects/client-shorts-media`
- `$HOME/projects/interview-series-media`

That keeps transcripts, subtitles, inventories, and rough cuts out of the toolkit repo.

## DaVinci Resolve layer export

For layered handoff, keep project-specific alpha plates and WAV stems in the
project workspace, then write a small manifest and export FCPXML:

```bash
media-fcpxml-export "$PROJECT_DIR/edit/resolve/layer-manifest.json" \
  -o "$PROJECT_DIR/edit/resolve/project.fcpxml"
```

Minimal manifest:

```json
{
  "project": "Layered Resolve Export",
  "sequence": {"width": 1920, "height": 1080, "fps": 30, "duration_frames": 767},
  "layers": [
    {"name": "Background", "path": "assets/background.mov", "kind": "video", "lane": 0, "duration_frames": 767},
    {"name": "Keyword Text", "path": "assets/keyword_text.mov", "kind": "video", "lane": 5, "offset_frames": 42, "duration_frames": 725},
    {"name": "Voice", "path": "assets/voice.wav", "kind": "audio", "lane": -1, "role": "dialogue", "duration_frames": 767}
  ]
}
```

`track`/`file` manifests are also accepted (`V1`, `V2`, `A1`, etc.). Media
paths resolve relative to the manifest.

## Recommended next step

After the repository exists, test it on a second machine with a small sample project. That is the fastest way to catch path assumptions, missing dependencies, or shell setup issues.
