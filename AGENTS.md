# Media Tooling Execution Context

This repository is meant to be used from the repo root.

Treat the repo root as `$TOOLKIT_DIR` when running commands or using the local skills. The reusable engine lives here. Project artifacts do not.

## User posture

- Run toolkit commands from this repo root with `uv run ...`.
- Keep project outputs outside this repository.
- Use the local skills in `.agents/skills/` to choose the right workflow.

## Workflow routing

- spoken media:
  use `media-subtitle` or `media-batch-subtitle`
- silent or visual-only video:
  use `media-contact-sheet` or `media-batch-contact-sheet`
- rough-cut assembly from an approved sequence:
  use `media-rough-cut`

## Skill usage

- `.agents/skills/media-subtitle-pipeline/`
  use for transcripts, subtitles, extracted audio, and transcript metadata
- `.agents/skills/media-corpus-ingest/`
  use for mixed corpora that need inventory plus spoken and silent media processing
- `.agents/skills/media-rough-cut-assembly/`
  use when a project-local storyboard or spec already exists and needs assembly

## Operational defaults

- prefer sequential processing for long media jobs
- use `--skip-existing` for resumable batches
- do not write project-local outputs into `media-tooling`
- summarize useful findings instead of dumping raw transcripts into the main thread

## Developer boundary

Developer-only maintenance notes, quality gates, and repo-internal workflow guidance belong in `docs/DEVELOPMENT.md`, not here.
