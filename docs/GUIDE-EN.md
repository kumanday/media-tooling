# Practical Guide to Media Tooling and Codex

This guide is for someone who already knows video production, works with audio and visual source material, and uses ChatGPT for ideation, but has less experience with the terminal, Codex, or agent harnesses.

The goal is to turn a large set of audio, video, and image files into a working package that is easy to search, review, classify, and edit.

## macOS installation

The fastest setup path is the toolkit bootstrap script.

```bash
git clone <toolkit-repo> "$HOME/dev/media-tooling"
cd "$HOME/dev/media-tooling"
./scripts/bootstrap-macos.sh
```

That script installs:

- `uv`
- `ffmpeg`
- Python 3.12 through `uv`
- the local project environment
- the `extract` and `subtitle` shell helpers in `~/.zshrc`

Manual installation is also fine:

```bash
brew install uv ffmpeg
uv python install 3.12
cd "$HOME/dev/media-tooling"
uv sync
./scripts/install-shell-helpers.sh
source ~/.zshrc
```

## What this toolkit is for

Media Tooling prepares source material. It organizes files, generates transcripts, creates subtitles, summarizes silent videos through contact sheets, and gives you a clean base for storyboards, scripts, and rough cuts.

It works well for:

- podcasts
- interviews
- tutorials
- courses
- product videos
- shorts
- reels
- YouTube uploads

The final edit stays human. The toolkit reduces repetitive setup work and leaves clearer editorial artifacts behind.

## How to think about the system

There are two layers.

### Reusable toolkit

This is where the reusable code lives.

Example location:

- `$HOME/dev/media-tooling`

### Project workspace

Each production should have its own workspace.

Examples:

- `$HOME/projects/podcast-episode-12-media`
- `$HOME/projects/python-course-media`
- `$HOME/projects/client-shorts-media`

That workspace holds the project artifacts:

- transcripts
- subtitles
- inventories
- analysis notes
- storyboards
- rough cuts
- editorial notes

Simple rule:

- the toolkit holds tools
- the workspace holds results

## Media types

### Spoken media

If a file contains dialogue, narration, or useful speech, generate:

- a transcript
- `.srt` subtitles

That makes it easier to search for quotes, find strong moments, review content without watching the full recording, and publish captions.

### Silent media

If a file is a screen recording or visual demo without useful speech, a contact sheet is usually the best first step.

A contact sheet is a single image made from sampled frames across a video. It gives you a quick visual overview of the clip and helps you decide whether it deserves manual review.

### Still images

Still images are usually inventoried directly. They work well for:

- articles
- thumbnails
- chapter cards
- visual reference

## Shell helpers

After installation, these helpers should be available in your shell.

### `extract`

Extracts `.m4a` audio from a video.

Example:

```bash
extract "/path/to/video.mp4"
```

### `subtitle`

Generates transcript, subtitles, and metadata from audio or video.

Example:

```bash
subtitle "/path/to/video.mp4" --output-dir "$PROJECT_DIR/transcripts"
```

## Recommended workflow

### 1. Create the project workspace

Use a simple structure like this:

```text
my-project-media/
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

### 2. Gather the corpus

Collect:

- spoken videos
- silent videos
- audio files
- screenshots
- context notes

### 3. Separate by type

Sort the source material into:

- spoken
- silent
- still images

That makes the next step much easier.

### 4. Process spoken media

For videos or audio with speech:

- generate transcripts
- generate subtitles

Typical output locations:

- `assets/audio/`
- `transcripts/`
- `subtitles/`

### 5. Process silent media

For silent screen recordings or demos:

- generate contact sheets
- create an inventory
- write a short note about likely editorial use

### 6. Analyze the corpus

Once the technical artifacts exist, move into editorial work:

- which clips deserve manual review
- which pieces fit a long-form video
- which pieces fit short clips
- which material belongs in an article or README

### 7. Build a storyboard and shot list

The storyboard organizes the narrative.

The shot list organizes the source usage.

A useful shot list often includes:

- file
- in time
- out time
- duration
- clip purpose
- editorial notes

### 8. Create a rough cut

A rough cut helps you test:

- structure
- order
- proportion between A-roll and B-roll
- narrative gaps

### 9. Edit the final version

This is where the editor does the detailed work:

- choose the best exact segment
- trim silence
- adjust pace
- treat color and audio
- export the final piece

## Concrete Codex examples

### Example 1. Full ingest of a mixed project

```text
I have a new media project in $PROJECT_DIR.

Sources:
- spoken videos: /path/to/spoken
- silent screen recordings: /path/to/silent
- screenshots: /path/to/images

Please:
1. inventory the corpus
2. separate spoken, silent, and image assets
3. create manifests for batch processing
4. generate transcripts and SRT subtitles for spoken media
5. generate contact sheets for silent media
6. write short analysis notes into $PROJECT_DIR/analysis

Use sequential processing and keep project outputs out of the toolkit repo.
```

### Example 2. Podcast episode

```text
I have a podcast episode with:
- one long spoken recording
- one clean audio export
- three short promo clips

I want:
1. transcripts and SRT subtitles
2. a shortlist of strong moments
3. suggestions for:
   - the full episode
   - short clips
   - quote graphics
4. a shot list with timestamps
```

### Example 3. Tutorial or course material

```text
I have tutorial materials that include:
- narrated lessons
- silent screen demos
- supporting screenshots

I want:
- transcripts and subtitles for narrated material
- contact sheets for silent material
- a storyboard proposal for:
  - one long video
  - three short clips
  - one companion article
```

### Example 4. Rough cut preparation

```text
The corpus in $PROJECT_DIR has already been processed.

Please review:
- transcripts/
- subtitles/
- assets/reference/
- analysis/

Then prepare:
1. a short list of the strongest clips
2. a proposed sequence
3. a note on what still needs to be recorded
```

## Exporting the toolkit to another Mac

The cleanest path is to keep `media-tooling` in its own Git repository.

The repository should include:

- `README.md`
- `pyproject.toml`
- `uv.lock`
- `src/`
- `shell/`
- `scripts/`
- `docs/`
- `.gitignore`

The repository should leave out:

- `.venv/`
- `.cache/`
- `mlx_models/`
- project-specific artifacts

The export walkthrough lives in:

- `docs/EXPORTING.md`

## Expected result

A good run leaves the project in this state:

- organized source corpus
- ready transcripts
- base subtitles
- visual reference for silent clips
- usable inventories
- analysis notes
- a clear storyboard
- an initial rough cut

At that point, far more energy can go into editorial judgment and less into repetitive setup.
