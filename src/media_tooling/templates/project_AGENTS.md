{{MANAGED_BLOCK_START}}
# Media Tooling Project Context

Treat this directory as `$PROJECT_DIR` and keep project artifacts inside it.

Read these central media-tooling skills before routing media-processing work:
{{SKILL_PATHS}}

Use installed toolkit commands from this project directory:
- spoken media: `media-subtitle` or `media-batch-subtitle`
- silent or visual-first video: `media-contact-sheet` or `media-batch-contact-sheet`
- rough-cut assembly: `media-rough-cut`
- burn subtitles: `media-burn-subtitles` or `media-batch-burn-subtitles`
- translate subtitles: `media-translate-subtitles`
- pack transcript for reasoning: `media-pack-transcript`
- timeline visual drill-down: `media-timeline-view`
- EDL-driven render: `media-edl-render`
- color grading: `media-grade`
- loudness normalization: `media-loudnorm`
- output verification: `media-verify`

Operational defaults:
- use sequential processing to reduce resource contention. Have patience for long media jobs
- use `--skip-existing` for resumable batches
- re-run `media-tooling-init` after reinstalling or relocating the toolkit so these skill paths stay current

## Session Memory Protocol

Persist strategy, decisions, and reasoning across sessions in `edit/project.md`.

On startup, read `edit/project.md` and summarize the last session in one sentence to re-establish context.

After each session, append a timestamped entry to `edit/project.md` using this format:

```
## Session YYYY-MM-DD

### Strategy
Current approach and goals for this project.

### Decisions
Key choices made and their rationale.

### Reasoning log
Significant inference chains or trade-off evaluations.

### Outstanding items
Unfinished work, open questions, or next actions.
```

## Hard Rules (non-negotiable for broadcast-quality output)

These 12 production rules are enforced by code guardrails and must never be violated:

1. **Subtitles applied last in filter chain** — Overlays hide captions if subtitles are burned before compositing. Always apply the subtitles filter as the final step.
2. **Per-segment extract + lossless concat** — Never use a single-pass filtergraph for multi-segment assembly. Extract each segment independently, then concat with the demuxer.
3. **30ms audio fades at every segment boundary** — Hard cuts produce audible pops. Always apply 30ms fade-in/fade-out at segment join points.
4. **Overlay PTS shift** — Use `setpts=PTS-STARTPTS+T/TB` so overlay frame 0 lands at the overlay window start time, not the container start.
5. **Master SRT uses output-timeline offsets** — Compute `output_time = word.start - segment_start + segment_offset`. Never use source-timeline offsets in the final SRT.
6. **Never cut inside a word** — Cut points must land on word boundaries (inter-word silence gaps). Mid-word cuts produce garbled audio.
7. **Pad cut edges (30-200ms working window)** — Absorb 50-100ms timestamp drift by padding each cut edge with 30-200ms of surrounding context.
8. **Word-level verbatim ASR only** — Never use phrase-mode SRT generation. Word-level timestamps are required for accurate cut-point selection.
9. **Cache transcripts** — Never re-transcribe unless the source file has changed. Check modification timestamps before re-running.
10. **Parallel sub-agents for animations** — Animation rendering must use parallel workers, never sequential processing.
11. **Strategy confirmation before execution** — Present the editing strategy to the user for approval before making irreversible edits.
12. **All outputs in project directory, never clobber source** — Write all generated files into `$PROJECT_DIR`. Never overwrite or modify source media files.

## Anti-patterns (things that consistently fail)

Avoid these 13 patterns — they have been proven to produce broken or low-quality output:

1. **Hierarchical pre-computed codec formats** — Intermediate ProRes files balloon storage and add re-encode generational loss. Use stream-copy or lossless concat instead.
2. **Hand-tuned moment-scoring functions** — Ad-hoc scoring heuristics for "best moments" are brittle and don't generalize. Use LLM-based reasoning on packed transcripts instead.
3. **Whisper SRT output** — Raw Whisper `.srt` loses sub-second gap data needed for accurate word-boundary editing. Always use the word-level JSON output.
4. **Running Whisper locally on CPU** — CPU transcription is 10-50x slower than GPU/MLX. Use hardware-accelerated backends whenever available.
5. **Burning subtitles before compositing overlays** — Violates Hard Rule 1. Overlays will hide or partially obscure burned captions.
6. **Single-pass filtergraph with overlays** — Violates Hard Rule 2. Multi-source compositing in one filtergraph is fragile and non-debuggable.
7. **Linear animation easing** — Linear easing looks robotic and amateurish. Always use cubic easing (ease_out_cubic for reveals, ease_in_out_cubic for draws).
8. **Hard audio cuts (no fade)** — Violates Hard Rule 3. Produces audible clicks/pops at every join point.
9. **Typing text centered on partial string** — Centering should use the full string bounding box, not character-by-character positioning. Partial-string centering causes misalignment.
10. **Sequential sub-agents for animations** — Violates Hard Rule 10. Animations must render in parallel to meet time budgets.
11. **Editing before confirming strategy with user** — Violates Hard Rule 11. Always get explicit approval of the editing plan before making cuts.
12. **Cutting inside a word** — Violates Hard Rule 6. Always cut at word boundaries to preserve speech clarity.
13. **Assuming content type** — Never assume a file is "podcast", "interview", etc. Always generalize processing to work for any spoken-media content.
{{MANAGED_BLOCK_END}}
