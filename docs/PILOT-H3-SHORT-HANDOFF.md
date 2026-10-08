# Pilot handoff: motion-graphics workflow findings (h3-short, 2026-10-03)

**To:** the agent maintaining `feat/motion-graphics-workflow`
**From:** the production agent that ran the first end-to-end pilot
**Scope:** findings, fixes already applied in this tree, and upstream
recommendations (code / docs / skills), plus a proposed review-mode feature.

---

## 1. What the pilot did

One 59.8s 9:16 short produced end-to-end from real material: a 66-minute
podcast episode (The AI First Show, `A37MNT2xok8`), Direction A "data cards"
approved via the storyboard-revision loop, motion graphics authored with
HyperFrames 0.8.116 as an alpha overlay, composited through `media-edl-render`
with burned subtitles (EN + ES variants), loudnorm, and `media-verify`.

Production artifacts live in a separate project workspace
(`/Users/magos/dev/trilogy/writing/`): composition at
`edit/hyperframes/h3-short/` (BRIEF.md, frame.md, STORYBOARD.md,
storyboard.html, index.html, chunks/), assembly at `edit/h3-short/`
(edl.json, edl-es.json, master.srt, master.es.srt, previews). The pilot
rendered two delivery previews: `preview.mp4` (EN) and `preview-es.mp4` (ES),
both `media-verify` 3/3 at true 1080x1920.

Environment: hyperframes 0.8.116 (was 0.7.1 — upgraded; 0.7.1 predates the
workflow commands), Node 25, Homebrew ffmpeg 8.1, Apple M3 Max.

## 2. Changes already applied in this tree (uncommitted)

All are on `feat/motion-graphics-workflow` alongside the workflow changes.
Full media-tooling suite green after each change.

1. **`src/media_tooling/subtitle.py`** — two changes:
   - ElevenLabs backend pin `scribe_v1` → `scribe_v2` (diarized, word-level).
   - **Word-level persistence fix (important):** `media-subtitle` used word
     timestamps internally for subtitle cue alignment but never wrote them to
     the transcript JSON — for *any* backend. Consequences downstream:
     `media-pack-transcript` produced "Packed 0 phrases" (its word-flattening
     found nothing), and EDL word-boundary cutting had no word data. Now every
     persisted cue carries its real ASR words (`word/start/end` + `speaker`
     stamp); evenly-stretched pseudo words remain timing aids only and are
     never persisted.
2. **`src/media_tooling/pack_transcript.py`** — `extract_words` now inherits
   the segment-level `speaker_id` onto words that lack their own, so diarized
   JSONs pack into speaker-tagged phrases.
3. **`src/media_tooling/edl_render.py`** — **portrait preview fix:** the
   per-segment scale anchored width (`scale=1920:-2` preview, `1280:-2`
   draft) for every orientation, blowing a 1080x1920 portrait source up to
   1920x3414 in preview/draft. Now probes source orientation and anchors
   height for portrait (`scale=-2:1920` preview, `-2:1280` draft). Landscape
   behavior unchanged. Found by ffprobing the output, not by looking at
   frames — the 1.78x upscale was invisible because overlay and footage
   scaled together.
4. **`tests/test_subtitle.py`, `tests/test_pack_transcript.py`** — regression
   coverage for the above: word persistence through cue split and tiny-block
   merge, speaker stamping, and pack-time speaker inheritance.

Suggested commit split: (a) subtitle/pack word-persistence + tests,
(b) portrait scaling fix, (c) scribe_v2 pin (or fold c into a).

## 3. Issues encountered, with evidence

Each item: what happened, why, and where the prevention belongs.

### 3.1 WebM alpha silently flattened (render cycle burned)

`hyperframes render --format webm` produced an opaque (black-base) VP9 even
with a fully transparent page. The CLI's own `AlphaAdvisory` explains it: this
platform's ffmpeg/libvpx-vp9 build cannot emit the alpha sidecar, and the
advisory fires only **after** encode. The guaranteed path — `--format mov`
(ProRes 4444) — worked immediately (349 MB for 60s, alpha verified via
`yuva444p` and pixel sampling).

**Recommendation (code):** probe libvpx alpha capability before encoding when
`--format webm` is requested (the same probe `AlphaAdvisory` already runs can
gate the job) and fail fast with the MOV suggestion, or auto-fallback.
**Recommendation (docs):** HYPERFRAMES.md's alpha note should state the
ffmpeg caveat and lead with MOV for guaranteed alpha.

### 3.2 EDL overlay windows replay the source from frame 0

An overlay spanning the whole short cannot be expressed: sync overlays are
capped at 14s, and each `overlays[]` window plays its source from the source's
frame 0. Our single 59.8s overlay rendered as every window showing the first
14 seconds. Workaround: split the MOV into five bounded chunks with ffmpeg and
reference one chunk per window.

**Recommendation (code):** add `source_start` (source-side offset) to
`overlays[]`, and/or auto-chunk long overlay sources at the schema level.
**Recommendation (docs/skill):** media-rough-cut-assembly should state the
frame-0 rule explicitly and include the chunk-split recipe
(`ffmpeg -ss N -i render.mov -t 14 -c copy chunk-N.mov`), since ProRes
all-intra splits cleanly.

### 3.3 GSAP visibility state diverges between snapshot and render paths

GSAP-timeline-driven opacity (enter/exit tweens) behaved correctly in
`hyperframes snapshot` and `check --snapshots --at-transitions` (runtime
audit: 0 issues) but **silently failed in the actual render** — a card frozen
visible past its exit, later scenes never appearing. Runtime clip gating
(`class="clip"` + `data-start`/`data-duration`) was reliable in every path.
Final authoring rule we adopted: **clip gating owns visibility; GSAP owns
polish only**, so a GSAP failure degrades to hard cuts, never stuck graphics.

**Recommendation (skill/docs):** put this rule in media-motion-graphics
("authoring contracts" section) and in the upstream composition guidance:
verify visibility with a *draft render*, not snapshots alone.
**Recommendation (code, upstream):** investigate the render capture path
(experimental-fast-capture / beginFrame) for timeline-seek state divergence;
`check` passing while the render is wrong means the check gate does not cover
render parity. A "render smoke" verification (draft render + sampled-frame
probe against scene expectations) would close the gap.

### 3.4 Portrait preview scaling (fixed, see §2.3)

**Recommendation (code):** add a portrait-source regression test to
`tests/test_edl_render.py` (the suite already builds video fixtures).

### 3.5 ASR proper-noun mishears reach burned subtitles

Scribe v2 with an `--initial-prompt` glossary still misheard: "Seed" + "Dance"
(for Seedance), "CDAN's" (Seedance), "Barb" (Barr), "sloths" (Unsloth). The
subtitles inherit transcript errors verbatim, and one error ("2.0" split at
its period by the translate re-segmenter) produced a fragment cue.

**Recommendation (docs/skill):** media-subtitle-pipeline should document a
per-show glossary convention (initial-prompt text stored in project config)
and a post-ASR project-dictionary correction pass applied to the cached
transcript before any subtitle/pack use.
**Recommendation (code):** media-translate-subtitles should not treat a '.'
between digits as a sentence break (we patched cues by hand; a
digits-aware rule + regression test fixes it for everyone).
**Toolkit note:** Scribe inserts whitespace-only spacer words between content
words; any word-merge or dictionary-correction pass must skip spacers when
checking adjacency (this bit our first merge attempt).

### 3.6 Minor friction

- `hyperframes render` has no `--overwrite`; outputs must be removed first.
- The `blank` example scaffolds an opaque `background: #0a0a0a`; overlay
  compositions must set `background: transparent` and it is easy to miss.
  **Recommendation (docs/skill):** state it in the overlay recipe, or offer
  `--example overlay` scaffolding transparent by default.
- Archive API/auth: `api/v1/publication` requires auth via direct curl
  (homepage og: meta works for brand scraping). Not a toolkit issue;
  recorded for completeness.

### 3.7 Confirmations (worked as designed)

Subtitles burned last compositing correctly (Hard Rule 1); 30 ms fades and
edge padding held; two-pass loudnorm hit −14 LUFS; `media-verify` duration/
grade checks matched; EDL overlay PTS shift composites alpha ProRes cleanly;
word-boundary cutting from the (now word-level) transcript is sound.

## 4. Feature request: two storyboard review modes

The pilot validated the human loop, but mass batch production needs an
automated one. Proposal: make review mode an explicit parameter of the
media-motion-graphics skill (e.g., `review-mode: revision | auto`), sharing
one pipeline and differing only in who inspects the stills.

### 4.1 `revision` mode (human-in-the-loop; what the pilot ran)

1. Agent proposes 2-3 directions (`storyboards/motion-directions.md`).
2. Human selects a direction.
3. Agent produces the branded static `storyboard.html` key-frame sheet
   (one frame per scene, real copy/assets) and **stops for approval**.
4. Approved layouts carry into the animated build; director notes are
   targeted edits to stable scene IDs; approved copy/layout/motion preserved.

This mode is already implemented de facto; it only needs to be named and
documented as the default.

### 4.2 `auto` mode (machine-inspected, for batch)

Replace steps 2-3's human judgment with a bounded self-review loop:

1. **Rubric gate (one-time, per project):** the operator pre-approves a
   rubric in project config — layout keep-clear zones (e.g., "no graphics
   over the speaker's face band"), brand palette/type conformance, minimum
   reading time per card, subtitle-zone reservation, copy accuracy rules,
   speaker-gate (which diarized speaker must be present).
2. **Self-review of stills:** after generating the storyboard sheet, the agent
   captures stills of each cell (the sheet is static HTML; per-cell frames
   from the source footage are already extracted for it) and inspects them —
   vision pass against the rubric: overlap with the keep-clear band, legible
   type at final scale, palette match, copy matches the brief/transcript.
3. **Bounded revision passes:** rubric violations become director notes to
   itself in the same scene-ID targeted-edit discipline (max N passes, e.g.
   2, then proceed or quarantine).
4. **Build gate:** existing `snapshot` + `check --snapshots --at-transitions`,
   plus a draft-render smoke (see 3.3) and snapshot-vs-storyboard comparison
   by vision before the delivery render.
5. **Batch guardrails:** per-episode ASR glossary, budget caps (render
   minutes, TTS/transcription credits), a decision manifest (which rubric
   checks ran, what was auto-revised) for post-hoc human audit, and
   quarantine: any item that fails its final gate goes to a review queue
   instead of publication.
6. **Human gate moves to publication:** Hard Rule 11 becomes per-batch
   policy approval ("produce 5 shorts from this episode under this rubric")
   rather than per-short approval.

**Implementation note:** the auto mode needs no new rendering infrastructure —
it reuses the still/snapshot machinery and adds (a) the rubric schema in
project config, (b) the vision-inspection + bounded-revision loop definition
in the skill, (c) the manifest/quarantine conventions. The pilot's
storyboard.html + per-scene footage frames are exactly the inputs the
auto-inspection consumes.

## 5. Small docs fixes worth folding in

- HYPERFRAMES.md: alpha caveat (webm vs mov) near the `--format` guidance;
  note the blank example's opaque background for overlays.
- media-rough-cut-assembly SKILL.md: overlay frame-0 rule + chunk recipe;
  portrait note now that the renderer handles it.
- media-motion-graphics SKILL.md: visibility authoring rule (clip gating vs
  GSAP polish; draft-render verification), the two review modes (§4), and the
  glossary/correction convention reference.
- media-render-pipeline SKILL.md: overlay chunk recipe pointer for
  long overlays.
