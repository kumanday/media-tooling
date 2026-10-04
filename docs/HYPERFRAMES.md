# Hyperframes

Hyperframes is the optional HTML-rendered video path for media-tooling projects.
Use it when a video needs browser-native motion graphics: animated captions, lower thirds, title cards, UI motion, data visuals, website captures, transparent overlays, GIFs, or batch-rendered variants.

Keep using media-tooling for transcription, contact sheets, packed transcripts, EDL assembly, grading, loudness normalization, subtitle burning, and output verification.

## Install

From a media-tooling checkout:

```bash
./scripts/install-hyperframes.sh
hyperframes doctor
hyperframes skills update
```

For a manual install:

```bash
brew install node ffmpeg
npm install -g hyperframes@latest
hyperframes telemetry disable
hyperframes doctor
hyperframes skills update
```

Hyperframes requires Node.js 22 or newer plus FFmpeg and FFprobe. The motion
workflow uses the current upstream skills and CLI commands. The examples were
checked against CLI 0.8.116 and upstream commit
[`237a984`](https://github.com/heygen-com/hyperframes/tree/237a984bb8d97f8dff7a5464c78851d633747f54).
Check `hyperframes --version` and command help before using them in an older project.

For standalone agent skills, `hyperframes skills update` installs the core set
and refreshes already installed skills; the upstream router installs creation
workflows on demand. For a HyperFrames plugin, use its plugin update mechanism.
Read the upstream `/hyperframes` skill first, then the selected creation workflow
and required domains. See the [upstream skill catalog](https://github.com/heygen-com/hyperframes#skills). For agent runs, use these environment variables to keep CLI output predictable:

```bash
export HYPERFRAMES_NO_TELEMETRY=1
export HYPERFRAMES_NO_UPDATE_CHECK=1
export HYPERFRAMES_NO_AUTO_INSTALL=1
```

`hyperframes doctor` may report Docker as unavailable when Docker Desktop is not running. That only matters when using `hyperframes render --docker`; normal browser-based renders do not require Docker.

## Explicit Use

Create a composition inside the project workspace, not in the media-tooling repository:

```bash
mkdir -p "$PROJECT_DIR/edit/hyperframes"
hyperframes init "$PROJECT_DIR/edit/hyperframes/lower-third" \
  --example blank \
  --resolution landscape \
  --non-interactive
cd "$PROJECT_DIR/edit/hyperframes/lower-third"
```

Edit the generated HTML/CSS/JS using the upstream composition and motion skills.
Use `hyperframes lint .` for early feedback. Check the composition, review the
preview, and render once approved:

```bash
hyperframes check . --snapshots --at-transitions
hyperframes preview . --port 3002 --no-open
hyperframes render . \
  --format mov \
  --output "$PROJECT_DIR/edit/hyperframes/lower-third/render.mov" \
  --quality delivery
```

Use `--format mov` (ProRes 4444) for reliable alpha overlays. WebM alpha depends
on the local FFmpeg/libvpx encoder; the pilot encountered an opaque WebM despite
a transparent page. Verify encoded alpha pixels and composite a draft over a
contrasting background before assembly. Set page and composition backgrounds to
`transparent`; the `blank` example starts with an opaque background. Use `--format mp4` for standalone segments, `--format gif` for docs and PR previews, and `--format png-sequence` for handoff to tools such as After Effects.

Add a rendered Hyperframes overlay to an EDL with `overlays[].source`:

```json
{
  "version": 1,
  "sources": {"main": "source/main.mp4"},
  "ranges": [
    {"source": "main", "start": 12.4, "end": 22.9, "beat": "Hook"}
  ],
  "overlays": [
    {
      "source": "hyperframes/lower-third/render.mov",
      "start": 0.8,
      "end": 6.8,
      "position": {"x": 0, "y": 0},
      "z_order": 10,
      "duration_type": "sync"
    }
  ],
  "subtitles": {"style": "bold-overlay"}
}
```

Overlay paths resolve relative to the EDL directory, usually `$PROJECT_DIR/edit`.
`media-edl-render` composites overlays before burning subtitles and applies the overlay PTS shift required by the production hard rules.

Then render and verify:

```bash
media-edl-render "$PROJECT_DIR/edit/edl.json" \
  -o "$PROJECT_DIR/edit/preview.mp4" \
  --preview \
  --build-subtitles

media-verify "$PROJECT_DIR/edit/preview.mp4" \
  --edl "$PROJECT_DIR/edit/edl.json"
```

## Implicit Use

An agent may invoke Hyperframes as part of a broader media-tooling workflow when the request asks for:

- animated lower thirds, callouts, counters, title cards, chapter cards, or kinetic captions
- HTML/CSS/JS-native motion, brand typography, responsive layouts, website captures, or UI walkthroughs
- alpha overlays to be composited by `media-edl-render`
- GIFs, PNG sequences, or batch-rendered variants from variable data
- graphic-heavy standalone intro, outro, bumper, or explainer segments

An agent should not reach for Hyperframes for ordinary cuts, ASR, contact sheets, static cards that Pillow can handle, subtitle translation, color grading, loudness normalization, or final EDL verification.

## Validation Checklist

Before a Hyperframes render is used in a media-tooling output:

- Run `hyperframes check . --snapshots --at-transitions`, read its findings, and inspect the PNGs
- Confirm the browser audit ran; skipped browser checks are incomplete verification
- Review playback for reading time, transition continuity, and audio synchronization
- Render the intended delivery format with `hyperframes render .`
- If the render is part of an EDL, run `media-edl-render` and `media-verify`
- Keep all composition files and renders under `$PROJECT_DIR/edit/hyperframes/<slot>/`


## Reference-led motion workflow

Use the packaged [media-motion-graphics skill](../.agents/skills/media-motion-graphics/SKILL.md)
for product videos, branded graphics, storyboard alternatives, scene stills, and
director notes. It connects the project to upstream HyperFrames authoring:

| Need | Upstream capability |
| --- | --- |
| Choose a creation workflow or resume an existing project | `hyperframes` router |
| Product capture and promo planning | `product-launch-video` |
| Brand design and static storyboard sketches | `hyperframes-creative` and shared review loop |
| Named effects, components, and transitions | `hyperframes-registry` with `catalog` / `add` |
| Seekable timing and camera moves | `hyperframes-core` and `hyperframes-keyframes` |
| Runtime, layout, motion, and contrast checks | `hyperframes-cli` with `check` |
| Stills from the built composition | `snapshot --at` |

The toolkit keeps the following artifacts in the project:

- `analysis/motion-references.md`: reference URLs/paths, timecoded observations,
  and the proposed pacing, type, camera, transition, and sound adaptations.
- `storyboards/motion-directions.md`: 2-3 distinct options when direction is open.
- `edit/hyperframes/<slot>/`: the upstream composition root, or the parent of its
  required `videos/<project>` directory. Keep `BRIEF.md`, `frame.md`,
  `STORYBOARD.md`, `storyboard.html`, assets, composition source, and snapshots
  in the owning upstream project; retain its formats and relative paths.
- `edit/project.md`: chosen direction and significant revision decisions.

Use real product screens and supplied brand assets. Analyze reference layouts
with contact sheets and inspect selected moments with timeline views or playable
clips. Record which motion properties were observed; identify inaccessible
references explicitly. Search HyperFrames' catalog before building a named
visual treatment from scratch.

Use upstream's branded static `storyboard.html` sketch pass before animation,
one key frame per scene. Include real copy, fonts, colors, and available assets;
label missing assets. This pass uses static HTML cells and does not invoke the
render CLI. Carry confirmed placement and hierarchy into the animated build.
A user can explicitly skip this review or request the storyboard as the deliverable.

After building, capture representative moments from the actual composition:

```bash
# Run inside the owning HyperFrames composition root.
# Choose times from this composition's scene IDs and timing, rather than a grid.
hyperframes snapshot . --at 1.5,4.0,7.25 --describe false
hyperframes check . --snapshots --at-transitions
```

Inspect the PNGs against the confirmed layouts and watch the preview for pacing
and sound. `--describe false` keeps snapshots local without optional vision-model
analysis. `check` includes lint and the browser audits; `inspect` is deprecated
upstream. Motion intent sidecars let the check verify scene-specific assertions.
Follow the selected review mode for final preview and rendering within the user's authorization.
For a standalone MP4, verify duration, resolution, fps, and audio against the brief.
For overlays or assembled segments, return to media-tooling's EDL render and
verification workflow.

## Director notes

Use stable scene IDs and output timestamps to locate revisions. Edit existing
source and shared timing values, preserve approved layouts, and update affected
storyboard and motion intent records. Review the changed scene and neighboring
seams before checking the assembled composition.

For example, a 1.4-second zoom slowed to 0.7x speed takes 2 seconds. Decide whether
the extra 0.6 seconds replaces hold time or shifts later beats; keep fixed voice
or music cues synchronized. A hard visual cut removes the transition at the named
boundary while preserving appropriate audio fades. A button push-in targets the
real button's bounds through a visual wrapper so timing and text remain stable.


## Autonomous review

Set `review-mode: auto` in the composition's `BRIEF.md` when the user requests
autonomous production; default to `review-mode: revision` for human review.
This is a media-tooling extension alongside the upstream brief fields. Use the
upstream autonomous configuration for authoring, and run the toolkit's visual
review step before continuing. Existing permission to produce the agreed video
covers local previews and final rendering; publishing needs separate permission.

Capture readable images of every static storyboard cell with a browser screenshot
facility. Pass those actual images to an available multimodal LLM along with the
brief, transcript excerpts, brand constraints, scene IDs, and durations. The
current agent can serve as the reviewer when it accepts image input. Ask for a
pass/revise decision and scene-specific feedback on copy accuracy, legibility,
speaker/subtitle placement, brand consistency, and reading time. Record the images,
feedback, and disposition in `review.md` next to the storyboard.

Apply targeted corrections and review once more, with a maximum of two review
passes. Continue when blocking findings are resolved. Unavailable visual review
or persistent blocking issues stop delivery with artifacts preserved. Optional
style suggestions are advisory. This mode needs no separate service or rubric
configuration.

## Encoded-output checks and overlay offsets

Timed `class="clip"` elements with `data-start` / `data-duration` own scene
visibility; GSAP adds polish inside their windows. Check the actual draft encode
at scene midpoints and immediately around entries/exits. The pilot found GSAP
visibility differences between snapshots and rendered video, so clean snapshots
and `check` results alone cannot establish render parity. In auto mode, send
sampled draft frames through the same multimodal review before delivery; inspect
boundary clips for timing and sound. Use distinct iteration output paths.

Each EDL source overlay starts at source time zero by default. Optional
`source_start` selects a source offset in seconds:

```json
{
  "source": "hyperframes/product/render.mov",
  "source_start": 14,
  "start": 14,
  "end": 28,
  "duration_type": "sync"
}
```

This plays source 14s-28s at output 14s-28s. Reusing a file without the offset
replays its beginning. `source_start` is a finite non-negative number for video
sources; images and generated cards do not support seeking. `duration_type: sync`
limits each window to 3-14s, and `beat` to 0.5-2s. Omit the optional type for a
full-length overlay. See the rough-cut assembly skill for an all-intra chunk
recipe when using older toolkit versions.

Before using ASR text in graphics, follow the subtitle skill's project glossary
and cached-transcript correction pass. Preserve real word timestamps and speaker
labels; regenerate downstream subtitle and packed artifacts from verified copy.
