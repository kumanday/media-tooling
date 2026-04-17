# Media-Tooling × Video-Use: Integration Plan

## Comparison & Contrast

| Dimension | media-tooling | video-use |
|---|---|---|
| **Positioning** | CLI toolkit → planning/production artifacts | Conversation-driven video editing skill |
| **Transcription** | Whisper (MLX / faster-whisper), local | ElevenLabs Scribe exclusively (cloud API) |
| **Pipeline** | Classify → Transcribe → Subtitle → Contact Sheet → Rough Cut | Transcribe → Pack → LLM Reasons → EDL → Render → Self-Eval |
| **Project scaffolding** | `media-tooling-init` with 11 dirs, AGENTS.md template | None (manual `edit/` dir) |
| **Batch processing** | Manifest-based, sequential | 4-worker parallel (transcription only) |
| **Translation** | Full translation workflow (windows + resegmentation) | None |
| **Contact sheets** | ffmpeg fps+tile for silent video | None (uses filmstrip+waveform instead) |
| **Rough cuts** | JSON spec: card/image/clip segments, Pillow-rendered cards | EDL-driven: per-segment extract + concat |
| **Color grading** | None | Auto-grade (signalstats) + 3 presets + custom ffmpeg |
| **Audio fades** | None | 30ms fades at every cut boundary |
| **Loudness norm** | None | Two-pass loudnorm → -14 LUFS / -1 dBTP / LRA 11 |
| **Subtitle burning** | Generates .srt only (not burned into video) | Burns into video, 2-word UPPERCASE default, customizable |
| **Overlays/animations** | None | PIL / Manim / Remotion, parallel sub-agents |
| **Self-evaluation** | None | timeline_view on rendered output at every cut |
| **Visual inspection** | Contact sheets (tiled frames) | Filmstrip + waveform + word labels + silence gaps |
| **Transcript for LLMs** | .txt + .json (verbose) | Packed phrase-level ~12KB markdown (efficient) |
| **Session memory** | None | project.md appended every session |
| **Filler removal** | None | LLM identifies from transcript, cuts at word boundaries |
| **Production rules** | None codified | 12 Hard Rules + 13 anti-patterns |
| **Packaging** | Proper Python package (hatchling, 7 CLI entry points) | pip install -e ., scripts in helpers/ |

---

## Plan: Incorporate High-Value Missing Functionality

Ordered by impact-to-effort ratio.

### Phase 1: Transcript & Visual Intelligence

*Makes everything downstream better.*

#### 1. Packed transcript format

Add a `media-pack-transcript` command that converts `.json` metadata into phrase-level `takes_packed.md` format. Group words on silence ≥0.5s or speaker change, with `[start-end]` time prefixes.

This is the single highest-value addition: it transforms raw transcripts from ~100KB JSON into ~12KB LLM-consumable markdown, making agent reasoning about video content dramatically more effective.

**New files:**

- `src/media_tooling/pack_transcript.py` — core logic
- `tests/test_pack_transcript.py`

**New CLI entry point:** `media-pack-transcript`

**Reference:** `video-use/helpers/pack_transcripts.py`

---

#### 2. Filmstrip + waveform visual composite

Add a `media-timeline-view` command that produces a PNG composite for any time range containing:

- N evenly-spaced frames
- RMS audio envelope
- Word labels
- Silence gap shading
- Time ruler

This gives agents on-demand visual inspection at decision points without dumping 30K frames. It complements (doesn't replace) contact sheets — contact sheets for inventory, timeline_view for editing decisions.

**New files:**

- `src/media_tooling/timeline_view.py` — core logic
- `tests/test_timeline_view.py`

**New CLI entry point:** `media-timeline-view`

**Dependencies:** `numpy`, `pillow` (already have pillow), `librosa` or stdlib `wave` module

**Reference:** `video-use/helpers/timeline_view.py`

---

### Phase 2: Render-Quality Production

*Makes output broadcast-ready.*

#### 3. Subtitle burning

Add a `media-burn-subtitles` command that burns SRT into video with customizable styles.

- Default style (`bold-overlay`): 2-word UPPERCASE chunks, white-on-black-outline, MarginV=35
- `natural-sentence` mode: 4-7 word chunks, sentence case, break on natural pauses, larger font
- Custom style passthrough

**Critical rule:** Apply **last** in any filter chain (Hard Rule 1) — otherwise overlays hide captions.

**New files:**

- `src/media_tooling/burn_subtitles.py` — core logic
- `tests/test_burn_subtitles.py`

**New CLI entry point:** `media-burn-subtitles`

**Reference:** `video-use/helpers/render.py` (build_master_srt + subtitles filter)

---

#### 4. Color grading

Add a `media-grade` command with:

- **Auto-grade mode** (default): Samples N frames via ffmpeg `signalstats`, computes mean brightness, RMS contrast, saturation. Emits bounded correction (max ±8% on any axis). Goal: "make it look clean without looking graded." No creative color shift.
- **Presets:**
  - `subtle`: Barely perceptible cleanup (contrast=1.03, sat=0.98)
  - `neutral_punch`: Light contrast + subtle S-curve, no hue shifts
  - `warm_cinematic`: +12% contrast, crushed blacks, -12% sat, warm shadows + cool highs, filmic curve
  - `none`: Straight copy
- **Custom:** `--filter '<raw ffmpeg>'` accepts any ffmpeg filter string

**Critical rule:** Applied **per-segment during extraction** (not post-concat) to avoid double-encoding.

**Mental model:** ASC CDL (slope=highlights, offset=shadows, power=midtones, global saturation).

**New files:**

- `src/media_tooling/grade.py` — core logic
- `tests/test_grade.py`

**New CLI entry point:** `media-grade`

**Reference:** `video-use/helpers/grade.py`

---

#### 5. Audio fades + loudness normalization

**Audio fades:** Add 30ms afade in/out at every segment boundary in rough-cut assembly. Integrate into `rough_cut.py`.

**Loudness normalization:** Add a `media-loudnorm` command for two-pass loudnorm targeting:

- -14 LUFS (integrated loudness)
- -1 dBTP (true peak)
- LRA 11 (loudness range)

This is the social media standard (YouTube, Instagram, TikTok, X, LinkedIn). Preview mode uses one-pass approximation for speed.

**New files:**

- `src/media_tooling/loudnorm.py` — core logic
- `tests/test_loudnorm.py`

**Modified files:**

- `src/media_tooling/rough_cut.py` — add 30ms afade at segment boundaries

**New CLI entry point:** `media-loudnorm`

**Reference:** `video-use/helpers/render.py` (apply_loudnorm_two_pass, extract_segment)

---

### Phase 3: Smart Editing & Self-Correction

*Makes output reliable.*

#### 6. EDL-based word-boundary editing

Extend `rough_cut.py` (or add a new `media-edl-render` command) to accept an EDL JSON spec with:

- Word-aligned cut points
- Padding (30-200ms working window at cut edges, absorbs 50-100ms timestamp drift)
- Per-segment grade/fade/subtitle directives
- Source references with start/end times

This replaces the current card/image/clip spec with a speech-aware editing model. Keep the card/image/clip spec as a fallback.

**EDL JSON format:**

```json
{
  "version": 1,
  "sources": ["source1.mp4"],
  "ranges": [
    {
      "source": "source1.mp4",
      "start": 12.340,
      "end": 18.920,
      "beat": "opening hook",
      "quote": "the thing that changed everything",
      "reason": "strong opening statement",
      "grade": "neutral_punch"
    }
  ],
  "overlays": [],
  "subtitles": { "style": "bold-overlay" },
  "total_duration_s": 180.0
}
```

**New files:**

- `src/media_tooling/edl_render.py` — core logic
- `tests/test_edl_render.py`

**New CLI entry point:** `media-edl-render`

**Reference:** `video-use/helpers/render.py` (full EDL render pipeline)

---

#### 7. Self-evaluation

Add a `media-verify` command that:

- Runs timeline_view on rendered output at every cut boundary (±1.5s window)
- Checks for: visual discontinuity/flash/jump, waveform spike (audio pop), subtitle hidden behind overlay, overlay misalignment
- Samples: first 2s, last 2s, 2-3 mid-points for grade consistency, subtitle readability, overall coherence
- Verifies duration matches EDL expectation via ffprobe
- Max 3 self-eval passes — then flag remaining issues to user
- Only presents preview once self-eval passes

**New files:**

- `src/media_tooling/verify.py` — core logic
- `tests/test_verify.py`

**New CLI entry point:** `media-verify`

**Reference:** `video-use/helpers/timeline_view.py` + SKILL.md self-eval section

---

#### 8. Session memory

Add a `project.md` convention to the project template that the agent appends to each session with:

- Strategy
- Decisions
- Reasoning log
- Outstanding items

On startup, the last session is summarized in one sentence.

**Modified files:**

- `src/media_tooling/templates/project_AGENTS.md` — add memory protocol
- `src/media_tooling/project_init.py` — add `edit/project.md` to scaffolded dirs

---

### Phase 4: Optional Enhancements

*When API key or advanced needs are present.*

#### 9. ElevenLabs Scribe as transcription backend

Add `--backend elevenlabs` to `media-subtitle` that uses ElevenLabs Scribe API for:

- Word-level timestamps
- Speaker diarization (`speaker_id`)
- Audio event tagging (`(laughter)`, `(applause)`, `(sigh)`)

Keep Whisper as the default (free, local). Make ElevenLabs opt-in via `ELEVENLABS_API_KEY` env var.

**Modified files:**

- `src/media_tooling/subtitle.py` — add ElevenLabs backend dispatch

**New dependency:** `requests` (when ElevenLabs backend selected)

**Reference:** `video-use/helpers/transcribe.py`

---

#### 10. Overlay/animation compositing

Add overlay support to the EDL renderer:

- PTS-shifted (`setpts=PTS-STARTPTS+T/TB`) video overlays with enable-between time windows
- Start with PIL-based overlay cards (already have Pillow as a dep)
- Add Manim as optional sub-skill with its own `.agents/skills/manim-video/SKILL.md`

**Duration rules from video-use:**

- 3-14s for sync-to-narration
- 0.5-2s for beat-synced accents
- Hold final frame ≥ 1s
- Over voiceover ≥ narration_length + 1s

**Easing:** Always cubic (ease_out_cubic for reveals, ease_in_out_cubic for draws). Never linear.

**Modified files:**

- `src/media_tooling/edl_render.py` — add overlay compositing

**New skill:** `.agents/skills/manim-video/SKILL.md`

**Reference:** `video-use/skills/manim-video/SKILL.md` + 13 reference docs

---

## Implementation Notes

### Hard Rules (codify into skills and code guardrails)

These 12 production rules from video-use are non-negotiable for broadcast-quality output:

1. Subtitles applied **last** in filter chain
2. Per-segment extract + lossless concat (never single-pass filtergraph)
3. 30ms audio fades at every segment boundary
4. Overlay PTS shift (`setpts=PTS-STARTPTS+T/TB`) so frame 0 lands at overlay window start
5. Master SRT uses **output-timeline** offsets (`output_time = word.start - segment_start + segment_offset`)
6. Never cut inside a word
7. Pad cut edges (30-200ms working window)
8. Word-level verbatim ASR only (never phrase-mode SRT)
9. Cache transcripts (never re-transcribe unless source changed)
10. Parallel sub-agents for animations
11. Strategy confirmation before execution
12. All outputs in project directory, never clobber source

### Anti-patterns (add to project AGENTS.md template)

13 things that consistently fail, from video-use:

1. Hierarchical pre-computed codec formats (ProRes intermediate, etc.)
2. Hand-tuned moment-scoring functions
3. Whisper SRT output (loses sub-second gap data)
4. Running Whisper locally on CPU
5. Burning subtitles before compositing overlays
6. Single-pass filtergraph with overlays
7. Linear animation easing
8. Hard audio cuts (no fade)
9. Typing text centered on partial string
10. Sequential sub-agents for animations (must be parallel)
11. Editing before confirming strategy with user
12. Cutting inside a word
13. Assuming content type (always generalize)

### Batch support

Every new command should get a `media-batch-*` wrapper following the existing manifest pattern in `batch_subtitle.py` / `batch_contact_sheet.py`.

### Skill updates

- **`media-subtitle-pipeline`** — cover packing + timeline_view
- **`media-rough-cut-assembly`** — cover EDL rendering + grading + fades + loudnorm + self-eval
- **New: `media-render-pipeline`** — full render → verify → iterate workflow

### CLI entry points to add to `pyproject.toml`

```toml
[project.scripts]
media-pack-transcript = "media_tooling.pack_transcript:main"
media-timeline-view = "media_tooling.timeline_view:main"
media-burn-subtitles = "media_tooling.burn_subtitles:main"
media-grade = "media_tooling.grade:main"
media-loudnorm = "media_tooling.loudnorm:main"
media-edl-render = "media_tooling.edl_render:main"
media-verify = "media_tooling.verify:main"
```

### Dependencies to add to `pyproject.toml`

```toml
dependencies = [
    # existing...
    "numpy>=1.26",
]
```

Optional (ElevenLabs backend):

```toml
[project.optional-dependencies]
elevenlabs = ["requests>=2.31"]
animations = ["manim>=0.20"]
```
