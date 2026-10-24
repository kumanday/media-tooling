# Install and update media-tooling

This page is written so that a person or a coding agent can follow it from top to
bottom. Run the steps in order and stop at the first one that fails.

**Agents:**
- Ask the user for anything marked *ask*.
- Never write API keys or voice IDs into files, and never print their values.
- Leave existing project files alone, apart from the managed block that
  `media-tooling-init` maintains in `AGENTS.md`.

## Requirements

- macOS or Linux, with Python 3.12 or newer available to `uv` (uv can fetch it).
- [`uv`](https://docs.astral.sh/uv/) and `ffmpeg`/`ffprobe` on `PATH`.
- Optional: Node.js 22 or newer for HyperFrames.

On macOS with Homebrew:

```bash
brew install uv ffmpeg
```

Elsewhere, install `ffmpeg` with the system package manager, and `uv` with:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Install

1. **Install the commands, with the ElevenLabs extra.** Narration, scoring and
   ElevenLabs transcription need the extra.

   ```bash
   uv tool install "media-tooling[elevenlabs] @ git+https://github.com/kumanday/media-tooling"
   ```

   If uv reports that `media-tooling` is already installed, follow
   [Update](#update) instead. If the shell can't find the commands afterwards,
   run `uv tool update-shell` and open a new shell.

2. **Make the skills visible to coding agents.** This links the toolkit skills
   into `~/.agents/skills`, which Codex and other agents read, and from
   `~/.claude/skills` to those entries for Claude Code. If Claude Code isn't
   installed, it links the shared store only. Antigravity reads only its own
   folders, so the skills are also linked into `~/.gemini/skills`,
   `~/.gemini/antigravity/skills` and `~/.gemini/antigravity-cli/skills`,
   pointing at the Claude Code store (for example
   `~/.gemini/skills/media-tts -> ../../.claude/skills/media-tts`). A folder is
   linked only when its parent exists. `--antigravity-dir DIR` (repeatable)
   replaces those folders and `--no-antigravity` skips them.

   ```bash
   media-tooling-link-skills
   ```

   It never deletes a real file or directory. An existing entry that isn't a
   symlink is reported as `skipped`. Re-run with `--force` to rename it to
   `<name>.bak-<time>` and link in its place. A Claude Code or Antigravity link
   that points somewhere else but still works is reported as `kept` and left
   alone; `--force` repoints it. `--dry-run` shows what would change.

3. **Provide credentials through the environment** (*ask* the user for values,
   or for the dotenv file that holds them).

   - `ELEVENLABS_API_KEY`: narration (`media-tts`, `media-tts-frames`), scoring
     (`media-video-music`) and ElevenLabs transcription.
   - `ELEVENLABS_VOICE_ID_EN`: the default narration voice. Other languages
     pass a voice explicitly, for example `--voice-id "$ELEVENLABS_VOICE_ID_ES"`.

   Keep them in the shell profile or in a dotenv file outside any repository.
   Load a dotenv file for one command with `set -a; source <file>; set +a`.

4. **Optional: HyperFrames,** for HTML-rendered motion graphics, overlays and UI
   captures:

   ```bash
   npm install -g hyperframes@latest
   ```
   ```bash
   hyperframes skills update
   ```

5. **Set up each project workspace** (*ask* the user where the project lives):

   ```bash
   media-tooling-init "$PROJECT_DIR"
   ```

   This creates the standard directories and writes a managed block in
   `$PROJECT_DIR/AGENTS.md` that points at the installed skills. An existing
   `AGENTS.md` keeps everything outside that block.

## Verify

```bash
media-tts-frames --help
```
```bash
media-tooling-link-skills --dry-run
```

The first command should print usage. The second should report every entry as
`current`. Then open a new agent session in the project directory and check that
it lists the `media-*` skills, for example `media-tts`.

## Update

```bash
uv tool upgrade --reinstall media-tooling
```
```bash
media-tooling-link-skills
```

Then refresh each project's managed block, which leaves other files untouched:

```bash
media-tooling-init --agents-only "$PROJECT_DIR"
```

Use `--reinstall`: the install comes from a Git branch, and a plain
`uv tool upgrade` reports "Nothing to upgrade" without fetching new commits. The
upgrade keeps the extras chosen at install time. Re-running
`media-tooling-link-skills` repairs links if the tool environment moved, for
example after a Python upgrade.

## Developer checkout

To change media-tooling itself, install from a clone in editable mode:

```bash
git clone https://github.com/kumanday/media-tooling "$HOME/dev/media-tooling"
```
```bash
uv tool install --editable "$HOME/dev/media-tooling[elevenlabs]"
```
```bash
media-tooling-link-skills
```

The links then point into the clone, so `git pull` updates both code and skills.
Re-run the `uv tool install --reinstall --editable …` command only when a
release adds new commands. See [DEVELOPMENT.md](DEVELOPMENT.md) for the quality
gates.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `command not found: media-…` | `uv tool update-shell`, then open a new shell |
| `media-tts` says `requests` is missing | the extra wasn't installed: `uv tool install --reinstall "media-tooling[elevenlabs] @ git+https://github.com/kumanday/media-tooling"` |
| an agent doesn't list the `media-*` skills | run `media-tooling-link-skills` and start a new agent session |
| `skipped` entries from `media-tooling-link-skills` | a real directory has that skill's name; inspect it, then re-run with `--force` |
| `Could not locate the packaged media-tooling skills` | reinstall the tool; the package is incomplete |
