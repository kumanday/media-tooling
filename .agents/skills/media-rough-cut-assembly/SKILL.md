---
name: media-rough-cut-assembly
description: Use when building a rough cut from a storyboard, shot list, or EDL spec. Covers EDL-based rendering (the primary path), color grading, audio fades, loudness normalization, and self-evaluation — plus the simpler card/image/clip workflow for quick assemblies.
---

# Media Rough-Cut Assembly

Use this skill when a project has a storyboard, shot list, transcript-based select points, or EDL spec and needs a production-quality rough cut with grading, fades, normalization, and self-evaluation.

## Toolkit boundary

Keep the reusable assembly engine in `media-tooling`.

Keep project-specific items in `$PROJECT_DIR`, outside the toolkit repo or install directory:

- storyboards, shot lists, episode outlines
- EDL JSON specs and source media
- rough-cut JSON specs (card/image/clip mode)
- output assemblies

The toolkit provides the engine. The project workspace provides the sequence definition.

## Primary workflow: EDL-based rendering

The EDL (Edit Decision List) renderer is the recommended path for any assembly that involves spoken-word source material, per-segment grading, or production-quality output.

### Workflow

```
storyboard → EDL spec → media-edl-render → [media-verify] → iterate
```

1. Read the storyboard, transcript, and clip notes.
2. Identify word-boundary cut points from transcripts (use `media-pack-transcript` to prepare packed transcripts for LLM-based selection).
3. Write a project-local EDL JSON spec defining source files, time ranges, and per-segment options.
4. Run `media-edl-render` against the EDL spec.
5. Run `media-verify` on the rendered output for self-evaluation at cut boundaries *(planned — not yet implemented; use manual review until available)*.
6. Iterate: adjust cut points, grade settings, or segment order in the EDL, then re-render and re-verify.

## EDL JSON format

An EDL JSON document describes which time ranges to extract from which source files and how to process each segment.

### Required top-level keys

| Key | Type | Description |
|------|------|-------------|
| `version` | `int` | Schema version. Must be `1`. |
| `sources` | `list[str]` or `dict[str,str]` | Source video file paths. List matched by basename; dict maps logical names to paths. |
| `ranges` | `list[dict]` | Ordered list of time ranges to extract. |

### Range object keys

| Key | Required | Type | Description |
|------|----------|------|-------------|
| `source` | yes | `str` | Source name matching a `sources` key or basename. |
| `start` | yes | `float` | Start time in seconds. |
| `end` | yes | `float` | End time in seconds (must be > start). |
| `grade` | no | `str` | Per-segment grade: `"auto"`, a preset name, or a raw ffmpeg filter string. |
| `beat` | no | `str` | Human-readable beat/chapter label. |
| `quote` | no | `str` | Quoted text for this segment. |
| `reason` | no | `str` | Why this segment was selected. |

### Optional top-level keys

| Key | Type | Description |
|------|------|-------------|
| `grade` | `str` | Default grade for ranges that omit `grade`. Same values as per-range `grade`. |
| `subtitles` | `str` or `dict` | SRT path (string) or dict with `path`, `style`, `force_style`. |

### Example EDL JSON

```json
{
  "version": 1,
  "sources": {
    "demo": "source/demo-take-1.mov",
    "interview": "source/interview-raw.mp4"
  },
  "grade": "auto",
  "subtitles": {
    "style": "bold-overlay",
    "path": "subs/master.srt"
  },
  "ranges": [
    {
      "source": "interview",
      "start": 12.480,
      "end": 18.960,
      "beat": "Hook",
      "quote": "The biggest mistake teams make…",
      "reason": "Strong opening statement"
    },
    {
      "source": "demo",
      "start": 45.200,
      "end": 62.800,
      "beat": "Demo",
      "grade": "neutral_punch"
    },
    {
      "source": "interview",
      "start": 134.320,
      "end": 148.640,
      "beat": "Takeaway",
      "grade": "auto"
    }
  ]
}
```

## Commands

### `media-edl-render` — Render from EDL spec

The primary rendering command. Reads an EDL JSON spec and produces a final assembled video with per-segment grade, 30 ms audio fades, subtitle burning, and two-pass loudness normalization.

```bash
media-edl-render edl.json -o final.mp4
```

**Flags:**

| Flag | Description |
|------|-------------|
| `-o`, `--output` | Output video path (required). |
| `--preview` | Preview mode: 1080p, medium preset, CRF 22 — fast, evaluable for QC. |
| `--draft` | Draft mode: 720p, ultrafast, CRF 28 — cut-point verification only. |
| `--build-subtitles` | Build master.srt from transcripts + EDL offsets before compositing. |
| `--no-subtitles` | Skip subtitle burning even if the EDL references subtitles. |
| `--no-loudnorm` | Skip loudness normalization. |
| `--ffmpeg-bin` | Path to ffmpeg binary. Default: `ffmpeg`. |
| `--ffprobe-bin` | Path to ffprobe binary. Default: `ffprobe`. |

`--preview` and `--draft` are mutually exclusive. `--build-subtitles` and `--no-subtitles` are mutually exclusive.

**Pipeline stages (obeys Hard Rules 1, 2, 3, 5, 6, 7):**

1. Validate EDL JSON schema.
2. Per-segment extract with word-boundary padding (30–200 ms), per-segment color grade, and 30 ms audio fades at both edges.
3. Lossless concat via ffmpeg concat demuxer.
4. Build master SRT with output-timeline offsets (if `--build-subtitles`).
5. Burn subtitles LAST in filter chain (Hard Rule 1).
6. Two-pass loudness normalization (−14 LUFS / −1 dBTP / LRA 11).

> **Note:** Hard Rule 4 (overlay PTS shift) is not yet exercised by the EDL renderer since overlay compositing is not in the current pipeline scope.

### `media-grade` — Apply color grade

Applies a color grade via ffmpeg filter chain. Two modes: **auto** (default) and **preset**.

```bash
# Auto mode (default): analyzes clip and applies subtle bounded correction
media-grade input.mp4 -o graded.mp4

# Preset mode: apply a named grade
media-grade input.mp4 -o graded.mp4 --preset neutral_punch

# Analyze only (no output written)
media-grade --analyze input.mp4

# List available presets
media-grade --list-presets

# Print filter string for a preset
media-grade --print-preset warm_cinematic
```

**Auto mode** (default) analyzes the clip via ffmpeg `signalstats`, computes mean brightness, luminance range, and saturation, then emits a bounded correction filter. All adjustments are capped at ±8% on every axis (parameters in [0.92, 1.08]). No color shift — only addresses underexposure, flatness, and desaturation. Goal: "make it look clean without looking graded."

**Presets:**

| Preset | Description |
|--------|-------------|
| `subtle` | Barely perceptible cleanup. Light contrast + slight desat. No color shift. |
| `neutral_punch` | Minimal corrective: light contrast + subtle S-curve. No color shifts. |
| `warm_cinematic` | **Opt-in creative only.** +12% contrast, crushed blacks, −12% sat, warm shadows, filmic curve. Too aggressive for standard content. |
| `none` | Flat — no grade. Sentinel for "skip grading this source." |

**Flags:**

| Flag | Description |
|------|-------------|
| `-o`, `--output` | Output video path. |
| `--preset` | Grade preset name. Omit for auto mode. |
| `--filter` | Raw ffmpeg filter string. Overrides `--preset`. |
| `--start` | Start time (seconds) for auto-grade analysis window. |
| `--duration` | Duration (seconds) for auto-grade analysis window. |
| `--analyze` | Analyze and print auto-grade filter without writing output. |
| `--print-preset` | Print filter string for a named preset and exit. |
| `--list-presets` | List available presets and exit. |

### `media-loudnorm` — Loudness normalization

Two-pass ffmpeg loudnorm targeting social-media standard: **−14 LUFS / −1 dBTP / LRA 11** (matches YouTube, Instagram, TikTok, X, LinkedIn).

```bash
# Two-pass (default, most precise)
media-loudnorm final.mp4 -o final-normalized.mp4

# Single-pass preview (faster, less precise)
media-loudnorm final.mp4 -o final-normalized.mp4 --preview
```

Pass 1 measures integrated loudness, true peak, and loudness range. Pass 2 applies linear normalization using measured values. If measurement fails, falls back to single-pass preview mode automatically.

The EDL renderer runs loudnorm automatically as the final pipeline stage. Use `media-loudnorm` standalone when you need to normalize a pre-existing file or re-normalize after manual edits.

**Flags:**

| Flag | Description |
|------|-------------|
| `-o`, `--output` | Output path (required). |
| `--preview` | Single-pass approximation. Faster, less precise. |
| `--ffmpeg-bin` | Path to ffmpeg binary. Default: `ffmpeg`. |
| `--ffprobe-bin` | Path to ffprobe binary. Default: `ffprobe`. |

### `media-verify` — Self-evaluation at cut boundaries *(planned)*

> **Status:** `media-verify` is a planned command (task 010). It does not yet have a CLI entry point or implementation. The checks and interface described below reflect the intended design. Until it is implemented, skip the verify step and rely on manual review of rendered output.

Inspects rendered video output at every cut boundary, checking for production errors before presenting the result. Catches visual discontinuities, audio pops, hidden subtitles, overlay misalignment, and duration mismatches.

```bash
media-verify final.mp4 --edl edl.json
```

**Checks performed:**

- Visual discontinuity/flash/jump at cut boundaries
- Waveform spikes indicating audio pops at cuts
- Output duration matches EDL expectation via ffprobe
- Grade consistency sampling (first 2s, last 2s, 2–3 mid-points)
- Subtitle readability at sampled points

**Behavior:**

- Generates `media-timeline-view` PNGs at every cut boundary (±1.5s window)
- Reports structured findings: pass/fail per check with details
- `--max-passes 3` limits re-evaluation attempts (default: 3)
- After max passes, flags remaining issues for manual review

Use `media-verify` after every `media-edl-render` run. If verification fails, adjust the EDL spec and re-render rather than presenting broken output.

**Typical verify-and-iterate loop:**

```bash
# Render
media-edl-render edl.json -o rough-cut.mp4 --preview

# Verify
media-verify rough-cut.mp4 --edl edl.json

# If issues found → fix EDL, re-render, re-verify (up to 3 passes)
```

### `media-rough-cut` — Card/image/clip assembly (simpler alternative)

For assemblies that don't need word-boundary editing, grading, or loudnorm, the simpler `media-rough-cut` command builds a rough cut from a JSON spec of placeholder cards, image holds, and clip extractions.

```bash
media-rough-cut --spec "$PROJECT_DIR/rough-cuts/specs/episode-v1.json"
```

**Segment types:**

| Type | Use for | Keys |
|------|---------|------|
| `card` | Narration placeholders, chapter transitions, sections needing A-roll | `header`, `meta`, `body`, `duration` |
| `image` | Screenshots, diagrams, static dashboards, UI stills | `input`, `duration` |
| `clip` | Spoken demo excerpts, screen recording excerpts, workflow proof clips | `input`, `start`, `end` |

Use `media-rough-cut` when:
- No word-boundary cut-point precision is needed
- No color grading is required
- Placeholder cards are needed for unfinished sections
- Quick assembly from heterogeneous segment types

Prefer `media-edl-render` when:
- Source material is spoken word requiring word-boundary cuts
- Per-segment color grading is needed
- Production-quality output with loudnorm is required
- Self-evaluation at cut boundaries is needed

## Audio fades

The EDL renderer applies **30 ms audio fades** at every segment boundary automatically (Hard Rule 3). This eliminates audible clicks and pops at join points without perceptibly affecting content.

No configuration is needed — fades are always applied during EDL rendering. Segments shorter than 60 ms (twice the fade duration) are exempt.

The `media-rough-cut` command also applies 30 ms fades on clip segments with audio.

## Expected project directory structure

```
$PROJECT_DIR/
├── source/           # Raw source media (never modified)
├── transcripts/      # Word-level JSON transcripts
├── subs/             # SRT subtitle files
├── edl/              # EDL JSON specs
│   └── episode-v1.json
└── output/           # Rendered assemblies
    ├── rough-cut-preview.mp4
    ├── rough-cut-final.mp4
    └── verify/       # media-verify timeline PNGs
```

Do not write project outputs into the `media-tooling` install directory.

## Hard rules and anti-patterns

All production hard rules and anti-patterns are codified in `docs/hard-rules.md`. The most relevant rules for rough-cut assembly:

| Rule | Description | Enforced by |
|------|-------------|-------------|
| 1 | Subtitles applied **last** in filter chain | `burn_subtitles.py`, `edl_render.py` |
| 2 | Per-segment extract + lossless concat (never single-pass filtergraph) | `rough_cut.py`, `edl_render.py` |
| 3 | 30 ms audio fades at every segment boundary | `edl_render.py`, `rough_cut.py` |
| 5 | Master SRT uses output-timeline offsets | `edl_render.py` |
| 6 | Never cut inside a word | `edl_render.py` (word-boundary padding) |
| 7 | Pad cut edges 30–200 ms (working window) | `edl_render.py` |
| 12 | All outputs in project directory, never clobber source | All commands |

**Critical anti-patterns to avoid:**

- Burning subtitles before compositing overlays (Anti-pattern 5, violates Rule 1)
- Single-pass filtergraph with multiple sources (Anti-pattern 6, violates Rule 2)
- Hard audio cuts without fades (Anti-pattern 8, violates Rule 3)
- Cutting inside a spoken word (Anti-pattern 12, violates Rule 6)
- Hierarchical pre-computed codec formats (Anti-pattern 1) — use concat demuxer instead

See `docs/hard-rules.md` for the full list of 12 hard rules and 13 anti-patterns.

## Guardrails

- Treat silent `.mov` excerpt timing as a planning pass unless the project already has exact selects.
- Keep placeholder copy short enough to be readable on-screen.
- Include explicit timing metadata on cards whenever a storyboard already defines chapter windows.
- Prefer a reusable EDL JSON spec over a one-off shell script.
- Run `media-verify` after rendering when available (currently planned, not yet implemented); otherwise rely on manual review.
- Never skip loudness normalization for social-media distribution targets.
- Use `--draft` mode first to verify cut points, then `--preview` for QC, then full render for final output.
