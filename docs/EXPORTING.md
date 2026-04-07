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
- `mlx_models/`
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

rsync -av --exclude '.venv' --exclude '.cache' --exclude 'mlx_models' \
  "$SOURCE_DIR/" "$EXPORT_DIR/"

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

On the editor's Mac:

```bash
git clone <your-new-repo-url> "$HOME/dev/media-tooling"
cd "$HOME/dev/media-tooling"
./scripts/bootstrap-macos.sh
```

## What Diego will need

Diego needs:

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

## Recommended next step

After the repository exists, test it on a second machine with a small sample project. That is the fastest way to catch path assumptions, missing dependencies, or shell setup issues.
