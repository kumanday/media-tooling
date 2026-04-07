# Media Tooling Usage Examples

This guide shows how to use the toolkit with an agent harness once you already have raw media for a project.

The examples fit Codex and other harnesses that can inspect local files, run commands, and write project artifacts.

## Core workflow

The workflow has five stages:

1. collect the raw media
2. split spoken media from silent media
3. generate transcripts, subtitles, and contact sheets
4. analyze the corpus
5. build storyboards, shot lists, and rough cuts

## Recommended project workspace

Create one workspace per production.

Example:

```text
$PROJECT_DIR/
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

## Example 1: Ingest a mixed corpus

Use this when a project has spoken interviews, silent screen recordings, and screenshots.

Prompt:

```text
I have a new media project in $PROJECT_DIR.

Source folders:
- spoken videos: /path/to/spoken
- silent screen recordings: /path/to/silent
- screenshots: /path/to/images

Please:
1. inventory the corpus
2. separate spoken, silent, and image assets
3. generate manifests for batch processing
4. process spoken media into transcripts and SRT subtitles
5. process silent videos into contact sheets
6. produce short analysis notes for what looks promising

Keep reusable code in the toolkit repo and project outputs in $PROJECT_DIR.
Process sequentially to avoid RAM spikes.
```

## Example 2: Process a podcast episode

Prompt:

```text
I have a podcast episode with:
- one full camera recording
- one clean audio export
- three short promo clips

Please:
1. decide which files should go through the subtitle pipeline
2. generate transcripts and SRTs
3. create an inventory of key segments that look useful for:
   - the full episode
   - short clips
   - quote graphics
4. write the results into analysis and inventory files inside $PROJECT_DIR
```

## Example 3: Process tutorial footage

Prompt:

```text
I have tutorial materials for a coding course.

The folder includes:
- narrated lesson recordings
- silent screen captures of product flows
- screenshots for reference

Please ingest the corpus and produce:
- transcripts and subtitles for narrated recordings
- contact sheets for silent recordings
- a storyboard suggestion for:
  - one long tutorial
  - three short promo clips
  - one article or README companion
```

## Example 4: Build a shot list after ingestion

Use this after transcripts and contact sheets already exist.

Prompt:

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

## Example 5: Prepare a rough cut

Prompt:

```text
Please use the processed artifacts in $PROJECT_DIR to prepare a first-pass rough cut plan.

I want:
- a proposed sequence
- which clips should carry narration
- which silent clips should be used as B-roll
- where screenshots are enough
- which sections feel weak or need new A-roll
```

## Example 6: Prepare YouTube subtitles

Prompt:

```text
The final edit is done.

Please help me:
1. review the existing subtitles
2. identify which ones need manual correction
3. produce a checklist for final YouTube upload:
   - title
   - description links
   - chapter timestamps
   - subtitle review
```

## Practical prompt pattern

Prompts work best when they include:

- where the source files are
- what kind of media you have
- what artifacts you want back
- where the outputs should be written
- any constraints such as sequential processing

## A simple default prompt

```text
I have a new media project at $PROJECT_DIR with spoken videos, silent screen recordings, and screenshots.

Please ingest the corpus, create the right manifests, process the files with the reusable media-tooling project, and write all project artifacts into $PROJECT_DIR.

I want:
- transcripts and SRTs for spoken media
- contact sheets for silent media
- inventory files
- analysis notes
- a short storyboard suggestion

Use sequential processing. Do not put project outputs inside the toolkit repo.
```
