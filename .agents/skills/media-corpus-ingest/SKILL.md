---
name: media-corpus-ingest
description: Use when ingesting a new corpus of local media into a project workspace for videos, podcasts, shorts, tutorials, courses, articles, demos, or other productions. This skill covers the reusable pattern for inventories, spoken-media transcripts and subtitles, silent-video contact sheets, screenshot indexing, and distilled analysis artifacts while keeping reusable tooling separate from project-specific outputs.
---

# Media Corpus Ingest

Use this skill when a project needs a structured media-ingest pass.

Project workspace:

- `$PROJECT_DIR` (the current media project directory)

Command posture:

- prefer installed `media-*` commands from `$PROJECT_DIR`
- keep project outputs in `$PROJECT_DIR`
- do not write artifacts back into the toolkit repository or install directory

## Distinguish media types first

### Spoken media

Use:

- `media-subtitle`
- `media-batch-subtitle`

Typical outputs:

- `assets/audio/`
- `transcripts/`
- `subtitles/`

### Silent or visual-only media

Use:

- `media-contact-sheet`
- `media-batch-contact-sheet`

Typical outputs:

- `assets/reference/`
- `inventory/`
- `analysis/`

### Still images

Inventory them directly into project-specific TSVs and analysis notes.

## Recommended project structure

When setting up a project workspace, prefer:

- `inventory/`
- `analysis/`
- `assets/audio/`
- `assets/reference/`
- `transcripts/`
- `subtitles/`
- `storyboards/`
- `rough-cuts/`

## Workflow

1. Inventory the corpus first.
2. Split spoken videos from silent videos and screenshots.
3. Process spoken videos sequentially into transcripts and subtitles.
4. Process silent videos sequentially into contact sheets.
5. Write inventory TSVs and a short processing note.
6. Distill the corpus into editorial buckets in `analysis/`.
7. Bubble up only the useful synthesis into the main thread.

## Worker/subagent use

If the harness supports workers, use them to isolate intermediate context for
inventory or analysis passes over disjoint source groups. Workers are for
context isolation, not throughput. Run media-heavy transcription and
contact-sheet work sequentially to avoid RAM and I/O pressure.

Give each worker a self-contained source list and output directory. Ask it to
return only:

- files created or modified
- sources skipped or failed
- short editorial findings worth preserving
- follow-up commands needed by the main thread

Keep raw transcripts, frame dumps, and scratch reasoning in project artifacts.
The main thread should receive the manifest and distilled notes, not the
intermediate processing context from every source.

## Operational rules

- Prefer sequential processing for media-heavy workloads.
- Use `--skip-existing` for resumable runs.
- Do not transcribe silent screen recordings just because they are videos.
- Treat contact sheets as planning aids, not as exact timestamp maps.
- Keep reusable code in the toolkit and project artifacts in the project workspace.

## Example spoken-media batch

```bash
media-batch-subtitle \
  --inputs-file "$PROJECT_DIR/inventory/spoken-sources.txt" \
  --audio-dir "$PROJECT_DIR/assets/audio" \
  --transcripts-dir "$PROJECT_DIR/transcripts" \
  --subtitles-dir "$PROJECT_DIR/subtitles" \
  --model small \
  --language en \
  --ffmpeg-bin "$(command -v ffmpeg)" \
  --skip-existing
```

## Example silent-media batch

```bash
media-batch-contact-sheet \
  --inputs-file "$PROJECT_DIR/inventory/silent-sources.txt" \
  --output-dir "$PROJECT_DIR/assets/reference" \
  --ffmpeg-bin "$(command -v ffmpeg)" \
  --ffprobe-bin "$(command -v ffprobe)" \
  --skip-existing
```

## Deliverables to favor

- inventory TSVs
- processing notes
- distilled analysis notes
- reference contact sheets

These are usually more useful than pushing raw media details into the main conversation.
