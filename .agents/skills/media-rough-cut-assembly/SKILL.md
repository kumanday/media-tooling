---
name: media-rough-cut-assembly
description: Use when building a first-pass rough cut from an existing storyboard, shot list, or segment spec. This skill covers reusable rough-cut assembly with placeholder cards, image holds, clip extraction, and final concat while keeping project-specific sequencing in the project workspace.
---

# Media Rough-Cut Assembly

Use this skill when a project already has a storyboard, a shortlist of clips, or a rough segment plan and now needs a reusable assembly pass.

## Toolkit boundary

Keep the reusable assembly engine in `media-tooling`.

Keep project-specific items in `$PROJECT_DIR`, outside the toolkit repo or install directory:

- storyboards
- shot lists
- launch or episode outlines
- exact clip selections
- rough-cut JSON specs
- output assemblies

The toolkit should provide the engine.
The project workspace should provide the sequence definition.

## Main command

- `media-rough-cut`

This command reads a JSON spec and builds:

- placeholder cards
- image holds
- extracted clips
- a concat manifest
- a rough-cut assembly

## Expected project outputs

Use a project workspace such as:

- `storyboards/`
- `clip-library/`
- `rough-cuts/specs/`
- `rough-cuts/generated-clips/`
- `rough-cuts/manifests/`
- `rough-cuts/assemblies/`

Do not write these outputs into `media-tooling`.

## Recommended workflow

1. Read the storyboard and clip notes.
2. Decide which segments are:
   - `card`
   - `image`
   - `clip`
3. Write a project-local JSON spec.
4. Run `media-rough-cut` against that spec.
5. Review the resulting assembly and note what should be tightened manually.

## Segment types

### Card

Use for:

- narration placeholders
- chapter transitions
- sections that still need A-roll

Include:

- `header`
- `meta`
  Usually target window and placeholder duration.
- `body`
  Brief recording or narration guidance.

### Image

Use for:

- screenshots
- diagrams
- static dashboards
- UI stills

Include:

- `input`
- `duration`

### Clip

Use for:

- spoken demo excerpts
- silent screen recording excerpts
- workflow proof clips

Include:

- `input`
- `start`
- `end`

## Example command

```bash
media-rough-cut --spec "$PROJECT_DIR/rough-cuts/specs/episode-v1.json"
```

## Guardrails

- Treat silent `.mov` excerpt timing as a planning pass unless the project already has exact selects.
- Keep placeholder copy short enough to be readable on-screen.
- Include explicit timing metadata on cards whenever a storyboard already defines chapter windows.
- Prefer a reusable JSON spec over a one-off shell script when the same pattern could apply to future projects.
