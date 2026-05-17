---
name: media-render-pipeline
description: |
  Use when producing a finished video end-to-end from raw source media.
  This skill covers the full render → verify → iterate workflow:
  transcribe → pack → reason → EDL → render → verify → iterate.
  It is the single entry-point skill for end-to-end video production,
  delegating to sub-skills for ingestion, subtitle pipeline, and
  rough-cut assembly where appropriate.
---

# Media Render Pipeline

Use this skill when a project needs a finished, broadcast-ready video produced
from raw source media — from initial transcript through final render with
self-evaluation and iteration.

This is the **top-level orchestration skill**. It coordinates the sub-skills
and toolkit commands into a single coherent production pipeline.

## Sub-skills

| Sub-skill | Pipeline step(s) |
|---|---|
| `media-corpus-ingest` | Inventory (Step 1) |
| `media-subtitle-pipeline` | Inventory → Transcribe → Pack (Steps 1–2) |
| `media-rough-cut-assembly` | Execute → Render (Steps 5, 8) |

Delegate to the appropriate sub-skill when a step's work falls entirely within
its scope. This skill adds the conversation, strategy, self-evaluation, and
iteration layers that the sub-skills do not cover.

## Worker/subagent protocol

If the harness supports workers, use them for independent, bounded side work to
isolate intermediate context:
transcript/contact-sheet batches, candidate-select analysis by source, overlay
animation slots, or verification samples. The main thread owns the strategy,
EDL, user-facing decisions, and final integration.

Workers are not a parallel-processing instruction. For RAM-heavy media work,
run one worker task at a time and consume its compact handoff before starting
the next one.

Worker prompts must be self-contained and define a disjoint artifact scope
such as one source file, one transcript shard, one animation slot, or one
verification window. Ask workers to return only durable handoff data:

- files created or modified
- key timestamps, selected ranges, or verification findings
- render commands run and output paths
- blockers, assumptions, and follow-up commands

Do not import raw transcripts, frame-by-frame notes, or exploratory reasoning
into the main thread unless needed for a specific decision. Persist bulky
intermediate context in `$PROJECT_DIR` artifacts and keep the main thread to
the synthesis needed for strategy, EDL edits, and user review.

## Project workspace

- `$PROJECT_DIR` — the current media project directory (set by the agent at
  session start; typically the working directory or the path passed by the user).
- All outputs go inside `$PROJECT_DIR` (Hard Rule 12).
- Source files are never modified (Hard Rule 12).

Expected project output structure:

```
$PROJECT_DIR/
├── <source files, untouched>
├── inventory/
├── transcripts/
│   ├── <name>.json           ← cached word-level transcripts
│   └── <name>_packed.md      ← phrase-level transcript for agent reasoning
├── subtitles/
├── edit/
│   ├── project.md            ← session memory (append each session)
│   ├── edl.json              ← edit decision list
│   ├── animations/slot_<id>/ ← per-animation source + render + reasoning
│   ├── clips_preview/       ← preview-grade extracts (created by EDL renderer with --preview)
│   ├── clips_graded/         ← full-grade extracts (populated by EDL renderer on final render; do not create manually)
│   ├── master.srt            ← output-timeline subtitles
│   ├── verify/               ← debug frames / timeline PNGs from self-eval
│   ├── preview.mp4
│   └── final.mp4
└── rough-cuts/
```

## The 8-step process

### Step 1: Inventory

Gather and catalogue all source media.

1. `ffprobe` every source to get duration, codec, resolution, and audio
   properties.
2. Classify sources: spoken media vs silent/visual-only media vs still images.
3. For spoken media, delegate transcription to the `media-subtitle-pipeline`
   skill:
   - Run `media-subtitle` (single file) or `media-batch-subtitle` (multiple
     files).
   - Use `--skip-existing` to avoid re-transcribing cached sources (Hard Rule 9).
4. For silent media, delegate to the `media-corpus-ingest` skill for contact
   sheets.
5. After transcription, pack each transcript into its own per-source markdown:
   ```bash
   for json_file in "$PROJECT_DIR/transcripts"/*.json; do
     base="$(basename "$json_file" .json)"
     media-pack-transcript "$json_file" \
       -o "$PROJECT_DIR/transcripts/${base}_packed.md"
   done
   ```
   Each source gets a `<name>_packed.md` beside its `.json`. For a single source,
   this is the primary reading view. For multiple sources, read each individually
   or concatenate if a combined view is needed.
6. Optionally sample one or two `media-timeline-view` composites for a visual
   first impression. Do **not** scan the entire source — use timeline view only
   at decision points.

### Step 2: Pre-scan

One pass over the packed transcript(s) to identify:

- Verbal slips, obvious mis-speaks, or phrasings to avoid.
- Silence gaps that may indicate natural edit points.
- Speaker transitions or overlaps.
- Any technical issues (long pauses, clipping, background noise).

Produce a plain list of observations. Feed this into the conversation in
Step 3 and the editor brief in Step 5.

### Step 3: Converse

Describe what you see in plain English. Ask questions *shaped by the material*.
The right questions are different for every project — do not use a fixed
checklist.

Collect from the user:

- Content type and target audience (but never *assume* content type —
  Anti-pattern 13)
- Target length, aspect ratio, and delivery format
- Aesthetic or brand direction
- Pacing feel
- Must-preserve moments and must-cut moments
- Animation and overlay preferences
- Color grade preferences
- Subtitle needs (chunking, case, placement)

Generalize processing for any spoken-media content. Do not assume the video
is a "podcast", "interview", "tutorial", etc. (Anti-pattern 13).

### Step 4: Propose strategy

Write 4–8 sentences covering:

- Shape of the final piece (opening hook, arc, close)
- Take choices and cut direction
- Animation/overlay plan (if applicable)
- Color grade direction
- Subtitle style
- Target duration estimate

**Wait for user confirmation before proceeding.** This is Hard Rule 11. Never
execute edits without explicit approval of the strategy.

If the user requests changes, update the strategy and re-confirm.

### Step 5: Execute

Produce the edit decision list and build the video.

1. **Produce `edl.json`** — Write the EDL JSON in `$PROJECT_DIR/edit/edl.json`
   using word-boundary cut points from the packed transcript:
   - Cut at word boundaries, never inside a word (Hard Rule 6).
   - Pad every cut edge with 30–200ms working window (Hard Rule 7).
   - Each range entry includes `source`, `start`, `end`, `beat`, `quote`,
     `reason`, and optional `grade`.
2. **Drill into `media-timeline-view`** at ambiguous moments where visual
   context would change the editing decision.
3. **Build animations in isolated slots** (if applicable) — when the harness
   supports workers, assign each worker exactly one
   `$PROJECT_DIR/edit/animations/slot_<id>/` directory and run worker tasks
   sequentially. Each worker reports the render path, duration, placement
   assumptions, commands run, and files changed.
   **Note:** `media-edl-render` does not yet composite overlays. Animations
   must be composited manually via ffmpeg overlay filter after rendering, or
   omitted until renderer support is added.
4. **Specify grade per-segment in the EDL** — add `grade` on ranges or
   top-level so the renderer applies it during extraction, never post-concat
   (Anti-pattern 1, Anti-pattern 6). No manual grading step is needed;
   the EDL renderer handles grading automatically when it reads `edl.json`.
5. **Render a preview** via `media-edl-render --preview`:
   ```bash
   media-edl-render "$PROJECT_DIR/edit/edl.json" \
     -o "$PROJECT_DIR/edit/preview.mp4" \
     --preview \
     --build-subtitles \
     --ffmpeg-bin "$(command -v ffmpeg)" \
     --ffprobe-bin "$(command -v ffprobe)"
   ```

   The EDL renderer enforces Hard Rules 1–7 automatically:
   - Per-segment extract with padding (Rule 7), grade (Rule 2), and 30ms fades
     (Rule 3).
   - Lossless concat via concat demuxer (Rule 2).
   - Master SRT with output-timeline offsets (Rule 5).
   - Subtitles burned **last** in filter chain (Rule 1).
   - Two-pass loudness normalization (−14 LUFS / −1 dBTP / LRA 11).

   Preview mode uses 720p with faster encode settings. Do **not** render
   full-quality yet — that happens in Step 8 after user approval.

### Step 6: Self-eval

Before presenting the output to the user, verify your own work.

1. **Run `media-timeline-view` on the rendered output** (not the sources) at
   every cut boundary (±1.5s window). Save images to `$PROJECT_DIR/edit/verify/`.
   `media-timeline-view` works on any MP4 — source files and rendered output
   alike.
2. **Check each boundary image for:**
   - Visual discontinuity / flash / jump at the cut
   - Waveform spike at the boundary (audio pop that slipped past the 30ms fade)
   - Subtitle hidden behind an overlay (Hard Rule 1 violation; only applicable
     if overlays were manually composited post-render)
   - Overlay misaligned or showing wrong frames (Hard Rule 4; only applicable
     if overlays were manually composited post-render)
3. **Sample additional points:** first 2s, last 2s, and 2–3 mid-points — check
   grade consistency, subtitle readability, and overall coherence.
4. **Verify duration** matches the EDL expectation:
   ```bash
   ffprobe -v error -show_entries format=duration \
     -of csv=p=0 "$PROJECT_DIR/edit/preview.mp4"
   ```
5. **If anything fails:** fix the EDL → re-render (`--preview`) → re-eval.
6. **Cap at 3 self-eval passes.** If issues remain after 3 passes, flag them
   explicitly to the user instead of continuing to iterate.

Only present the preview to the user once self-eval passes, or after 3 passes
with remaining issues clearly documented.

### Step 7: Preview

Present the preview render to the user for review. The preview was produced
in Step 5 using `--preview` mode (720p, faster encode) and verified in Step 6.
Walk the user through the key moments and transitions.

### Step 8: Iterate + Persist

After the user reviews the preview:

1. **Address feedback** — make requested changes to the EDL, re-render the
   preview (`--preview`), re-run self-eval, and present the revised preview
   to the user. Repeat until the user approves.
2. **Final render** — once approved, produce the full-quality render:
   ```bash
   media-edl-render "$PROJECT_DIR/edit/edl.json" \
     -o "$PROJECT_DIR/edit/final.mp4" \
     --build-subtitles \
     --ffmpeg-bin "$(command -v ffmpeg)" \
     --ffprobe-bin "$(command -v ffprobe)"
   ```
3. **Persist session memory** — append to `$PROJECT_DIR/edit/project.md`:

   ```markdown
   ## Session YYYY-MM-DD

   ### Strategy
   Current approach and goals.

   ### Decisions
   Key choices made and their rationale.

   ### Reasoning log
   Significant inference chains or trade-off evaluations.

   ### Outstanding items
   Unfinished work, open questions, or next actions.
   ```

4. On the next session startup, read `edit/project.md` and summarize the last
   session in one sentence to re-establish context.

## Session memory protocol

All strategy, decisions, and reasoning must persist across sessions in
`$PROJECT_DIR/edit/project.md`.

- **On startup:** Read `project.md` if it exists. Summarize the last session
  in one sentence before asking whether to continue.
- **After each session:** Append a timestamped entry with strategy, decisions,
  reasoning log, and outstanding items.
- **Never overwrite** previous session entries — only append.

This ensures continuity when the same project is revisited across sessions.

## Hard Rules (production correctness — non-negotiable)

These 12 rules are enforced by code guardrails where possible and must never be
violated regardless of aesthetic preference. Full rationale and enforcement
details are in `docs/hard-rules.md` (available in the media-tooling repository;
not bundled when the skill is deployed standalone).

| # | Rule | Enforced by |
|---|------|-------------|
| 1 | Subtitles applied **last** in filter chain | `burn_subtitles.py` |
| 2 | Per-segment extract + lossless concat (never single-pass filtergraph) | `rough_cut.py` |
| 3 | 30ms audio fades at every segment boundary | `edl_render.py` |
| 4 | Overlay PTS shift (`setpts=PTS-STARTPTS+T/TB`) | Not yet enforced |
| 5 | Master SRT uses output-timeline offsets | `edl_render.py` |
| 6 | Never cut inside a word | `edl_render.py` |
| 7 | Pad cut edges (30–200ms working window) | `edl_render.py` |
| 8 | Word-level verbatim ASR only (never phrase-mode SRT) | `subtitle.py` |
| 9 | Cache transcripts (never re-transcribe unchanged sources) | `subtitle.py` |
| 10 | Isolated worker handoffs for animation slots | Agent orchestration |
| 11 | **Strategy confirmation before execution** | This skill (Step 4) |
| 12 | All outputs in project directory, never clobber source | This skill |

**Hard Rule 11 is especially critical for this skill:** the propose-strategy
step (Step 4) must receive explicit user confirmation before any edits are
executed. This is not optional. See Anti-pattern 11.

## Anti-patterns (things that consistently fail)

Avoid these 13 patterns at all times. They produce broken or low-quality output
regardless of style. Full explanations are in `docs/hard-rules.md` (available in
the media-tooling repository; not bundled when the skill is deployed standalone).

| # | Anti-pattern | Related Hard Rule |
|---|-------------|-------------------|
| 1 | Hierarchical pre-computed codec formats (ProRes intermediate, etc.) | Rule 2 |
| 2 | Hand-tuned moment-scoring functions | — |
| 3 | Whisper SRT output (loses sub-second gap data) | Rule 8 |
| 4 | Running Whisper locally on CPU | — |
| 5 | Burning subtitles before compositing overlays | Rule 1 |
| 6 | Single-pass filtergraph with overlays | Rule 2 |
| 7 | Linear animation easing (always use cubic) | — |
| 8 | Hard audio cuts with no fade | Rule 3 |
| 9 | Typing text centered on partial string | — |
| 10 | Using workers for parallel media processing instead of context isolation | Rule 10 |
| 11 | Editing before confirming strategy with user | Rule 11 |
| 12 | Cutting inside a word | Rule 6 |
| 13 | Assuming content type (always generalize) | — |

## Pipeline summary

```
Inventory → Pre-scan → Converse → Propose strategy → Execute → Self-eval → Preview → Iterate + Persist
   (1)        (2)        (3)           (4)            (5)       (6)       (7)           (8)
```

Steps 1–3: Understand the material and the user's intent.
Step 4: Get explicit confirmation (Hard Rule 11).
Step 5: Build the edit (EDL + preview render).
Step 6: Self-evaluate before showing the user (max 3 passes).
Step 7: Present the preview to the user.
Step 8: Iterate on feedback and persist session memory.

## Toolkit commands

| Command | Pipeline step |
|---------|--------------|
| `media-subtitle` | Step 1 (transcribe) |
| `media-batch-subtitle` | Step 1 (batch transcribe) |
| `media-pack-transcript` | Step 1 (pack) |
| `media-timeline-view` | Steps 1, 5, 6 (on-demand visual drill-down) |
| `media-edl-render` | Steps 5, 8 (render with EDL) |
| `media-burn-subtitles` | Step 5 (subtitle burning, usually via EDL render) |
| `media-grade` | Step 5 (standalone grading outside EDL workflow; not needed when using `media-edl-render`) |
| `media-loudnorm` | Step 5 (standalone normalization outside EDL workflow; not needed when using `media-edl-render`) |
| `media-rough-cut` | Step 5 (alternative: card/image/clip assembly) |

## EDL JSON format

```json
{
  "version": 1,
  "sources": {"C0103": "/abs/path/C0103.MP4", "C0108": "/abs/path/C0108.MP4"},
  "ranges": [
    {
      "source": "C0103",
      "start": 2.42,
      "end": 6.85,
      "beat": "HOOK",
      "quote": "the thing that changed everything",
      "reason": "Cleanest delivery, stops before slip at 38.46.",
      "grade": "neutral_punch"
    },
    {
      "source": "C0108",
      "start": 14.30,
      "end": 28.90,
      "beat": "SOLUTION",
      "quote": "you just flip the switch",
      "reason": "Only take without the false start."
    }
  ],
  "grade": "warm_cinematic",
  "overlays": [
    {"file": "edit/animations/slot_1/render.mp4", "start_in_output": 0.0, "duration": 5.0}
  ],
  "subtitles": {"style": "bold-overlay"},
  "total_duration_s": 87.4
}
```

- `sources`: **dict** mapping short names to absolute paths. Use a dict when
  short names are needed for range references, or when multiple sources share
  the same basename. A **list** of absolute paths is accepted as a shorthand
  when all basenames are unique (matched by full basename including extension;
  duplicates rejected),
  but dict is preferred for clarity. When using list form, `ranges[].source`
  references the full basename including extension (e.g.,
  `"/path/C0103.MP4"` → `"C0103.MP4"`).
- `ranges`: ordered list of segments to include. Each requires `source`,
  `start`, `end`. Optional: `beat`, `quote`, `reason`, `grade`.
- `grade`: top-level default grade preset or raw ffmpeg filter. Overridden by
  per-range `grade`.
- `overlays`: rendered animation clips with placement in the output timeline.
  Paths are resolved relative to `$PROJECT_DIR`. **Note:** overlay compositing
  is not yet implemented in `media-edl-render`; animations built in Step 5.3
  must be composited manually via ffmpeg overlay filter in a post-render step,
  or omitted until renderer support is added. The `overlays` field in the EDL
  is accepted but silently ignored by the current renderer.
- `subtitles`: string (path) or dict with optional keys `style`, `path`,
  `force_style`. `style` is the most common; `path` and `force_style` are
  only needed when overriding defaults.
- `version`: required schema version, currently `1`.
- `total_duration_s`: informational only — expected total duration for the
  agent's reference. The renderer does not validate this field; verify actual
  duration via `ffprobe` (Step 6.4).

## Animation guidance (when requested)

When the user wants overlay animations, follow these principles:

- **Get palette and visual language from the conversation.** Never assume
  defaults. If the user hasn't specified, propose a palette in Step 4 and
  wait for confirmation.
- **Tool options:**
  - PIL + PNG sequence + ffmpeg — simple overlay cards, counters, typewriter
    text, bar reveals. Fast to iterate.
  - Manim — formal diagrams, state machines, equations, graph morphs.
  - Remotion — typography-heavy, brand-aligned, web-adjacent layouts.
- **Duration rules:**
  - Sync-to-narration: 3–14s (5–7s typical for simple cards).
  - Beat-synced accents: 0.5–2s.
  - Hold final frame ≥ 1s before cut.
  - Over voiceover: ≥ narration_length + 1s.
- **Easing:** Always cubic (`ease_out_cubic` for reveals, `ease_in_out_cubic`
  for draws). Never linear (Anti-pattern 7).
- **Typing text:** Center on the FULL string's bounding box, not
  character-by-character (Anti-pattern 9).
- **Animation workers:** When supported by the harness, use workers to isolate
  per-slot scratch context. Each prompt must be self-contained since workers
  have no parent context. Run render-heavy worker tasks sequentially; the main
  thread should receive the slot path, render path, duration, and integration
  notes, not the worker's full exploratory reasoning.

## Subtitle styles

Subtitles have three dimensions: **chunking** (1/2/3/sentence per line),
**case** (UPPER/Title/Natural), and **placement** (bottom margin). The right
combination depends on content and audience.

Worked styles — pick, adapt, or invent:

- **`bold-overlay`** — short-form, fast-paced social content. 2-word chunks,
  UPPERCASE, break on punctuation, `MarginV=35`.
- **`natural-sentence`** — narrative, documentary, education. 4–7 word chunks,
  sentence case, break on natural pauses, `MarginV=60–80`, larger font.

Hard rules for subtitles: applied LAST (Rule 1), output-timeline offsets
(Rule 5).

## Guardrails

- Never execute edits without user confirmation of the strategy (Hard Rule 11).
- Never cut inside a word (Hard Rule 6).
- Never burn subtitles before overlays (Hard Rule 1).
- Never use a single-pass filtergraph for multi-source assembly (Hard Rule 2).
- Never assume content type — look at the material first, ask second, edit last
  (Anti-pattern 13).
- Cap self-evaluation at 3 passes; flag remaining issues to the user.
- All outputs go in `$PROJECT_DIR`; never clobber source files (Hard Rule 12).
- Use `media-timeline-view` only at decision points — not as a default scan
  step.
- Cache transcripts; never re-transcribe unless the source changed (Hard Rule 9).
- Persist session memory in `$PROJECT_DIR/edit/project.md` after every session.
