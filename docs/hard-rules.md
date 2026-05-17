# Production Hard Rules and Anti-patterns

This document codifies the 12 hard rules and 13 anti-patterns derived from
video-use production experience. These rules are non-negotiable for
broadcast-quality output and are enforced by code guardrails in the
media-tooling toolkit.

---

## Hard Rules

### Rule 1: Subtitles applied last in filter chain

**Rationale:** When subtitles are burned into video before overlays or other
video filters are applied, subsequent compositing operations can hide or
partially obscure the captions. The subtitles filter must always be the
terminal filter in any `-vf` or `-filter_complex` chain.

**Enforcement:** `burn_subtitles.py` — `validate_subtitles_last()` raises
`ValueError` if a subtitles or overlay filter is found in user-supplied
extra filters.

### Rule 2: Per-segment extract + lossless concat

**Rationale:** A single-pass filtergraph that processes all segments in one
ffmpeg invocation is fragile, non-debuggable, and prevents per-segment
processing (grading, fades, etc.). The correct approach is to extract each
segment independently (with `-ss`/`-to`), then assemble them with the concat
demuxer (`-f concat -safe 0 -i <manifest>`).

**Enforcement:** `rough_cut.py` — `validate_concat_demuxer_usage()` raises
`AssemblyMethodError` if a concat assembly command contains single-pass
filtergraph indicators (`-filter_complex`, `-lavfi`, `xfade`, `acrossfade`).

### Rule 3: 30ms audio fades at every segment boundary

**Rationale:** Hard audio cuts at segment join points produce audible clicks
and pops. A 30ms fade-in/fade-out at every boundary eliminates these
artifacts without perceptibly affecting content.

**Enforcement:** To be enforced in `edl_render.py` when created.

### Rule 4: Overlay PTS shift

**Rationale:** When compositing overlays with `overlay=`, the overlay video
stream starts at PTS=0 from the container start. To make overlay frame 0 land
at the intended time window, apply `setpts=PTS-STARTPTS+T/TB` to the overlay
stream before the overlay filter.

**Enforcement:** To be enforced in `edl_render.py` when created.

### Rule 5: Master SRT uses output-timeline offsets

**Rationale:** When assembling segments from different source timestamps into
a continuous output, subtitle timestamps must be recalculated relative to the
output timeline: `output_time = word.start - segment_start + segment_offset`.
Using source-timeline offsets produces subtitles that drift out of sync.

**Enforcement:** To be enforced in `edl_render.py` when created.

### Rule 6: Never cut inside a word

**Rationale:** Cutting in the middle of a spoken word produces garbled audio
that sounds broken to listeners. Cut points must always land on inter-word
silence gaps (word boundaries).

**Enforcement:** To be enforced in `edl_render.py` when created.

### Rule 7: Pad cut edges (30-200ms working window)

**Rationale:** ASR timestamps can drift by 50-100ms. Padding each cut edge
with 30-200ms of surrounding context absorbs this drift and ensures clean
word boundaries are preserved.

**Enforcement:** To be enforced in `edl_render.py` when created.

### Rule 8: Word-level verbatim ASR only

**Rationale:** Phrase-mode SRT generation loses the sub-second timing data
needed for accurate word-boundary cut-point selection. Word-level timestamps
are the minimum viable granularity for speech-aware editing.

**Enforcement:** `subtitle.py` — resegmentation logic always uses word-level
timestamps when available.

### Rule 9: Cache transcripts

**Rationale:** Re-transcribing unchanged source files wastes significant time
and compute. Always check source modification timestamps against cached
transcript timestamps before re-running transcription.

**Enforcement:** `subtitle.py` — `--skip-existing` flag skips re-transcription
when outputs already exist.

### Rule 10: Worker context isolation for animations

**Rationale:** Animation slots can create a lot of scene-specific scratch
reasoning and render artifacts. When the harness supports workers, use them to
keep that intermediate context out of the main thread. Media rendering is
RAM-heavy, so worker tasks should run sequentially.

**Enforcement:** To be enforced in overlay/animation rendering modules when
created.

### Rule 11: Strategy confirmation before execution

**Rationale:** Making irreversible edits without user approval leads to wasted
effort and user frustration. Always present the editing strategy (EDL, cut
points, selections) for confirmation before executing.

**Enforcement:** Enforced via AGENTS.md template guidance for agent workflows.

### Rule 12: All outputs in project directory, never clobber source

**Rationale:** Overwriting source media files is irreversible and breaks
reproducibility. All generated artifacts must be written into the project
directory (`$PROJECT_DIR`), leaving source files untouched.

**Enforcement:** Enforced via AGENTS.md template guidance; all CLI commands
write to project subdirectories by default.

---

## Anti-patterns

### Anti-pattern 1: Hierarchical pre-computed codec formats

**Why it fails:** Intermediate ProRes or other high-bitrate codec files balloon
storage requirements and introduce generational loss with each re-encode. The
concat demuxer with stream-copy or light re-encode is faster, smaller, and
preserves quality.

**Correct approach:** Use `-f concat` with stream-copy (`-c copy`) or
lightweight re-encode (`-c:v libx264 -preset veryfast -crf 20`).

### Anti-pattern 2: Hand-tuned moment-scoring functions

**Why it fails:** Ad-hoc scoring heuristics for identifying "best moments" are
brittle, don't generalize across content types, and require constant manual
tuning.

**Correct approach:** Use LLM-based reasoning on packed transcripts to select
moments based on semantic understanding of content.

### Anti-pattern 3: Whisper SRT output

**Why it fails:** Raw Whisper `.srt` output loses sub-second gap data between
words. This gap information is critical for accurate word-boundary editing.

**Correct approach:** Always use the word-level JSON output from transcription,
then generate SRT from the JSON data using the resegmentation pipeline.

### Anti-pattern 4: Running Whisper locally on CPU

**Why it fails:** CPU-based transcription is 10-50x slower than GPU/MLX
accelerated inference. A 30-minute video can take hours on CPU vs minutes on
accelerated hardware.

**Correct approach:** Use the MLX backend on Apple Silicon or CUDA-enabled
faster-whisper on other platforms. The `media-subtitle` command auto-detects
the best available backend.

### Anti-pattern 5: Burning subtitles before compositing overlays

**Why it fails:** Violates Hard Rule 1. If subtitles are burned before
overlays, the overlay compositing will hide or partially obscure the captions.

**Correct approach:** Always apply subtitles as the last filter in the chain.
Use `media-burn-subtitles` which enforces this ordering, or use the EDL
renderer which composites overlays first, then burns subtitles.

### Anti-pattern 6: Single-pass filtergraph with overlays

**Why it fails:** Violates Hard Rule 2. Multi-source compositing in one
filtergraph is fragile, hard to debug, and prevents per-segment processing.

**Correct approach:** Extract and process each segment independently, then
assemble with the concat demuxer.

### Anti-pattern 7: Linear animation easing

**Why it fails:** Linear easing looks robotic and amateurish. The human eye
expects natural acceleration and deceleration in motion.

**Correct approach:** Always use cubic easing — `ease_out_cubic` for reveals,
`ease_in_out_cubic` for draws and transitions.

### Anti-pattern 8: Hard audio cuts (no fade)

**Why it fails:** Violates Hard Rule 3. Cutting audio without any fade at the
boundary produces audible clicks and pops that are distracting and
unprofessional.

**Correct approach:** Apply 30ms fade-in/fade-out at every segment boundary
using ffmpeg's `afade` filter.

### Anti-pattern 9: Typing text centered on partial string

**Why it fails:** Centering text character-by-character based on a partial
string causes misalignment. The bounding box should be computed for the full
displayed string.

**Correct approach:** Compute centering using the complete string bounding box
before rendering.

### Anti-pattern 10: Using workers as parallel media processors

**Why it fails:** Violates Hard Rule 10. Parallel media or animation rendering
can exhaust RAM and freeze the machine. Workers are for isolating intermediate
context, not for increasing concurrent processing.

**Correct approach:** Run resource-heavy worker tasks sequentially. Each worker
returns a compact handoff with artifacts, commands, assumptions, and
integration notes.

### Anti-pattern 11: Editing before confirming strategy with user

**Why it fails:** Violates Hard Rule 11. Making cuts without user approval
leads to wasted effort when the strategy doesn't match expectations.

**Correct approach:** Always present the editing strategy for confirmation
before executing any irreversible edits.

### Anti-pattern 12: Cutting inside a word

**Why it fails:** Violates Hard Rule 6. Mid-word cuts produce garbled audio
that sounds broken.

**Correct approach:** Always cut at word boundaries using inter-word silence
gaps identified from word-level timestamps.

### Anti-pattern 13: Assuming content type

**Why it fails:** Assuming a file is a "podcast", "interview", "lecture", etc.
leads to pipeline configuration that breaks on edge cases. Content type
assumptions create fragile workflows.

**Correct approach:** Always generalize processing to work for any spoken-media
content. Let the content dictate the workflow, not labels.

---

## Summary Table

| # | Hard Rule | Enforcement Module |
|---|-----------|-------------------|
| 1 | Subtitles applied last in filter chain | `burn_subtitles.py` |
| 2 | Per-segment extract + lossless concat | `rough_cut.py` |
| 3 | 30ms audio fades at every segment boundary | `edl_render.py` (future) |
| 4 | Overlay PTS shift | `edl_render.py` (future) |
| 5 | Master SRT uses output-timeline offsets | `edl_render.py` (future) |
| 6 | Never cut inside a word | `edl_render.py` (future) |
| 7 | Pad cut edges (30-200ms working window) | `edl_render.py` (future) |
| 8 | Word-level verbatim ASR only | `subtitle.py` |
| 9 | Cache transcripts | `subtitle.py` |
| 10 | Worker context isolation for animation slots | Agent orchestration |
| 11 | Strategy confirmation before execution | AGENTS.md template |
| 12 | All outputs in project directory, never clobber source | AGENTS.md template |

| # | Anti-pattern | Related Hard Rule |
|---|-------------|-------------------|
| 1 | Hierarchical pre-computed codec formats | Rule 2 |
| 2 | Hand-tuned moment-scoring functions | — |
| 3 | Whisper SRT output | Rule 8 |
| 4 | Running Whisper locally on CPU | — |
| 5 | Burning subtitles before compositing overlays | Rule 1 |
| 6 | Single-pass filtergraph with overlays | Rule 2 |
| 7 | Linear animation easing | — |
| 8 | Hard audio cuts (no fade) | Rule 3 |
| 9 | Typing text centered on partial string | — |
| 10 | Using workers as parallel media processors | Rule 10 |
| 11 | Editing before confirming strategy with user | Rule 11 |
| 12 | Cutting inside a word | Rule 6 |
| 13 | Assuming content type | — |
