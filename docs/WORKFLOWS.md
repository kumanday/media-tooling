# Workflows

This guide shows how to use the toolkit once you already have raw media for a project.

The examples fit agent harnesses that can inspect local files, run commands, and write project artifacts.

Subtitle commands accept `--backend auto|mlx|faster-whisper`. In normal use, `auto` is the right choice.

## Core workflow

1. Gather the source corpus.
2. Split spoken media from silent media and still images.
3. Generate transcripts and subtitles for spoken media.
4. Generate contact sheets for silent media.
5. Build inventories, analysis notes, storyboards, rough-cut specs, and rough-cut assemblies.

## Media types

### Spoken media

Use the subtitle pipeline for:

- podcasts
- interviews
- narrated tutorials
- course lessons
- product walkthroughs with voice

Typical outputs:

- `assets/audio/`
- `transcripts/`
- `subtitles/`

### Silent or visual-first media

Use the contact-sheet pipeline for:

- screen recordings
- silent demos
- product flows without narration

Typical outputs:

- `assets/reference/`
- `inventory/`
- `analysis/`

### Still images

Inventory these directly and use them in:

- articles
- thumbnails
- chapter cards
- storyboards

## Prompt patterns for an agent harness

Prompts work best when they include:

- where the source files are
- what kind of media you have
- what artifacts you want back
- where outputs should be written
- any constraints such as sequential processing

## Example 1. Ingest a mixed corpus

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

## Example 2. Process a podcast episode

```text
I have a podcast episode with:
- one long spoken recording
- one clean audio export
- three short promo clips

Please:
1. decide which files belong in the subtitle pipeline
2. generate transcripts and SRTs
3. create an inventory of strong segments for:
   - the full episode
   - short clips
   - quote graphics
4. write the results into analysis and inventory files inside $PROJECT_DIR
```

## Example 3. Process tutorial material

```text
I have tutorial materials that include:
- narrated lesson recordings
- silent screen captures of product flows
- screenshots for reference

Please ingest the corpus and produce:
- transcripts and subtitles for narrated recordings
- contact sheets for silent recordings
- a storyboard suggestion for:
  - one long tutorial
  - three short promo clips
  - one companion article
```

## Example 4. Build a shot list after ingestion

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

## Example 5. Prepare a rough cut

```text
Please use the processed artifacts in $PROJECT_DIR to prepare a first-pass rough cut plan.

I want:
- a proposed sequence
- which clips should carry narration
- which silent clips should be used as B-roll
- where screenshots are enough
- which sections feel weak or need new A-roll
```

## Example 6. Assemble a rough cut from an approved spec

```text
The storyboard and clip choices in $PROJECT_DIR are already approved.

Please:
1. create or update a JSON rough-cut spec in rough-cuts/specs/
2. use the media-rough-cut assembly skill from the toolkit
3. generate readable placeholder cards with target windows and placeholder durations
4. build the generated clips, manifest, and assembly
5. keep the toolkit reusable and keep project sequencing outside the toolkit repo
```

## Example 7. Prepare final subtitles

```text
The final edit is done.

Please help me:
1. review the existing subtitles
2. identify which ones need manual correction
3. produce a checklist for final upload:
   - title
   - description links
   - chapter timestamps
   - subtitle review
```

## Command examples

These commands are the building blocks that the prompt patterns usually trigger.

### Single spoken file

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

### Batch spoken media

```bash
cd "$TOOLKIT_DIR"
uv run media-batch-subtitle \
  --inputs-file "$PROJECT_DIR/inventory/spoken-sources.txt" \
  --audio-dir "$PROJECT_DIR/assets/audio" \
  --transcripts-dir "$PROJECT_DIR/transcripts" \
  --subtitles-dir "$PROJECT_DIR/subtitles" \
  --backend auto \
  --model small \
  --language en \
  --ffmpeg-bin "$(command -v ffmpeg)" \
  --skip-existing
```

### Single silent file

```bash
cd "$TOOLKIT_DIR"
uv run media-contact-sheet \
  "/path/to/silent-video.mov" \
  --ffmpeg-bin "$(command -v ffmpeg)" \
  --ffprobe-bin "$(command -v ffprobe)"
```

### Batch silent media

```bash
cd "$TOOLKIT_DIR"
uv run media-batch-contact-sheet \
  --inputs-file "$PROJECT_DIR/inventory/silent-sources.txt" \
  --output-dir "$PROJECT_DIR/assets/reference" \
  --ffmpeg-bin "$(command -v ffmpeg)" \
  --ffprobe-bin "$(command -v ffprobe)" \
  --skip-existing
```

### Rough cut from a JSON spec

```bash
cd "$TOOLKIT_DIR"
uv run media-rough-cut \
  --spec "$PROJECT_DIR/rough-cuts/specs/episode-v1.json"
```
