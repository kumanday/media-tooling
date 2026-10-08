---
name: media-motion-graphics
description: Plan and revise reference-led product videos, branded motion graphics, and animated overlays using HyperFrames inside a media-tooling workspace. Use for storyboard alternatives, scene stills, or director notes on an existing composition.
---

# Motion graphics in a media-tooling workspace

Use HyperFrames' installed skills for authoring and rendering. This skill connects
those workflows to project assets, reference analysis, and media-tooling assembly.

## Start with upstream capabilities

1. Read the composition's `BRIEF.md`, `STORYBOARD.md`, `DECISIONS.md`, and
   design spec before asking for information. Read `edit/project.md` for shared
   project context when the user's scope permits it. An independent pilot uses
   only its own slot's records and the current toolkit guidance.
2. Check `hyperframes --version` and command help. Use the current upstream
   `/hyperframes` router and its selected workflow. For standalone skill installs,
   `hyperframes skills update` installs the core set; the router loads creation
   workflows on demand. Plugin installs use the plugin's update mechanism.
   If required skills or commands are missing, report the gap and use the setup
   instructions in the toolkit's `docs/HYPERFRAMES.md`. Do not invent upstream
   commands or reconstruct missing skills from memory.
3. Load only the domains needed: `hyperframes-creative` for brand and storyboard
   design, `hyperframes-registry` for reusable treatments, `hyperframes-core` and
   `hyperframes-keyframes` for timing and seekable motion, and `hyperframes-cli`
   for checks, snapshots, preview, and rendering.

Keep compositions under `$PROJECT_DIR/edit/hyperframes/<slot>/`. Bind the upstream
project root to that directory, including any `videos/<project>` subdirectory a
workflow requires. Keep capture, media manifests, scripts, and renders beneath
that root. Reuse existing composition roots when editing. Media-tooling owns
source processing, EDL assembly, subtitle burning, grading, and delivery checks.
Use installed upstream scripts and formats; do not copy their implementation into
this skill. Honor the user's requested review mode and existing approvals; do not
repeat intake or approvals for settled decisions.

## Review mode

Record `review-mode: revision` or `review-mode: auto` in the composition's
`BRIEF.md` as a media-tooling extension. Default to `revision`. An explicit request
to operate autonomously selects `auto`; record the request and agreed scope in
`DECISIONS.md` in the composition slot. This setting changes the review process, not the authoring
workflow. Use upstream's autonomous/skip-checkpoint configuration where supported
and keep this review step alongside its authoring contracts.

In `revision`, the user chooses the direction and reviews the branded storyboard
and final preview. In `auto`, choose the direction that best fits the brief, build
the static storyboard sheet, and replace these human checkpoints with visual
review. Carry the user's existing permission to produce the agreed deliverable
through local preview and render; do not ask for per-scene or final-render approval
again. Publication or messaging requires its own authorization.

For auto review, capture the static sheet's scene cells using a browser screenshot
facility, in readable batches with stable scene IDs. Do not run HyperFrames
`snapshot` against the storyboard sheet: it is not a timed composition. Pass the
actual images to an available multimodal LLM (the current agent's image input is
sufficient), together with the brief, transcript excerpts, brand constraints,
scene IDs, and durations. Inspect every scene; text-only feedback does not count.
Ask for concrete feedback on copy accuracy, legibility at delivery size, graphic
placement relative to speaker and subtitles, brand consistency, and reading time.
Request a pass/revise result and scene-specific changes. This is an approximation
of creative review, not proof that pacing or audio works.

Save image paths, reviewer/model identity when available, feedback, and disposition
in `review.md` beside the storyboard. Apply targeted corrections, then repeat
visual review once (two review passes total). Proceed when no blocking issue
remains. If visual input is unavailable or a blocking issue survives the second
pass, save the artifacts and report the blocker; do not call the item approved.
Optional style suggestions need not prevent delivery. Reuse the same process on
representative frames extracted from the draft encode to check storyboard fidelity
and visibility before final delivery. Watch or inspect short boundary clips for
motion and sound. Keep corrections within the brief and retain the technical gates.

## References and brand

Collect the brief, audience, message, delivery size/duration, logo, fonts, colors,
real product screenshots or source components, and 1-2 style references when
available. Reuse supplied information. A missing reference is not a blocker:
record a proposed visual direction using upstream design guidance.

Write `<composition-root>/motion-references.md` with each reference's URL or
local path and timecoded observations. Separate observed features from proposed
adaptations. Record shot/hold lengths, type scale and hierarchy, entry/exit motion,
easing, zoom or crop behavior, transition continuity, and sound cues where relevant.
Use contact sheets for layout and `media-timeline-view` at selected moments for
motion evidence. Inspect playable clips when judging pacing or sound. A still
image cannot establish motion. If a URL cannot be viewed, record the limitation
and work from available evidence without inventing an analysis.

Translate the findings into the upstream `BRIEF.md`, design spec (`frame.md` or
its supported equivalent), and storyboard direction. Keep the product's own
colors, fonts, copy, and interface as the visual source of truth. Prefer captured
screens and actual product assets; rebuild only the moving region when useful.
Use `hyperframes-registry` to search for named effects or transitions before
hand-authoring them. Keep references as direction; use project assets in the film.

## Choose a direction and review stills

When creative direction is open, propose 2-3 meaningfully different storyboard
options in `<composition-root>/motion-directions.md`: vary the narrative,
layout, or pacing, with beat durations and asset choices. A selected direction or
a targeted edit can go straight to its existing storyboard.

Write the selected plan into the upstream `STORYBOARD.md` format with stable scene
IDs, intended motion, and source assets. Use upstream's plan/sketch/build review
loop. Default to a branded static `storyboard.html` sheet, one key frame per scene,
before animation. Show actual copy, typography, colors, and available product
assets; label stand-ins for missing assets. Follow upstream's sketch recipe,
which makes static HTML cells without running render or snapshot commands.
In auto mode, select the direction and visually review the sheet as defined above.
Carry confirmed layouts into the build and revise only the scenes named in notes.
Respect an explicit request to skip stills or to stop at the storyboard.

After building the composition, use `hyperframes snapshot --at <times> --describe false` for each
scene's representative moment and compare those images with the confirmed sheet.
These stills come from the actual seekable composition. Enable optional vision
analysis only when it is part of the requested workflow.
Inspect transition boundaries too; snapshots verify layout, while playback
verifies pacing and sound. Record scene IDs and snapshot times in `STORYBOARD.md`
using its supported fields or prose, preserving the upstream format.

## Director notes on existing source

Use the upstream timeline and editing contracts to locate the named scene or
output timestamp. Patch the existing composition and shared parameters. Preserve
approved copy, assets, layouts, and unrelated motion. Update affected storyboard
and motion intent sidecars with the change; do not restart the creative workflow.

Translate notes into concrete timing, crop, easing, or transition edits:

| Note | Edit and timing consequence |
| --- | --- |
| Slow this zoom to 0.7x speed | New duration = old duration / 0.7. Decide whether to use available hold time or shift later beats; preserve fixed narration/music cues. |
| Hard cut at 4.2s | Set the scene boundary to 4.2s and remove the visual transition there; retain appropriate audio fades. |
| Push in on the button | Animate a crop/visual wrapper toward the real button's bounds; keep the timed clip and text layout stable. |
| Hold the result longer | Extend the hold using available scene time, or update later starts and total duration if the brief permits it. |

For ambiguous speed notes, distinguish speed from duration; use context or ask
one focused question when the choice changes synchronization. Centralize reusable
motion values where the composition supports it. Review the affected scene and
both adjacent seams first, then check the assembled composition before delivery.

## Overlay authoring and render parity

Set page and composition backgrounds to `transparent` for alpha overlays; the
blank scaffold starts opaque. Use timed `class="clip"` elements with `data-start`
and `data-duration` to own scene visibility. GSAP can polish entry/exit motion
inside those windows. The pilot observed snapshot/render divergence with
GSAP-only visibility, so verify the encoded output rather than assuming a clean
snapshot/check proves render parity.

Render a draft to a distinct output path, sample frames immediately before/after
scene entries and exits and at scene midpoints, and inspect the encoded frames
for stuck cards, missing scenes, and lost transparency. For an alpha overlay,
inspect alpha pixels and composite over a contrasting background; a codec/pixel
format label alone is insufficient evidence. Prefer MOV (ProRes 4444) when WebM
alpha is unsupported by the local encoder. Preserve source and approved renders;
use new output names for iterations instead of deleting them preemptively.

For spoken footage, follow `media-subtitle-pipeline`'s project glossary and cached
transcript correction guidance before using transcript copy in the storyboard.

## Generated footage with TTV

Use TTV when a reviewed scene needs generated footage. Export the selected
`STORYBOARD.md` scenes to `$PROJECT_DIR/storyboards/<revision>.json` using the
scene shape in `docs/generated-media.md`. Preserve scene IDs, scene order,
durations, entry/exit intent, references, delivery dimensions, and continuity.
Include a `motion_review` record with review mode, reviewer, disposition, and
paths and SHA-256 hashes of the storyboard, review images, and `review.md`.
Archive those files alongside the JSON revision. Mark `approved: true` only
after the selected review process has passed.

Creative review and spending permission are separate records. Carry the user's
existing permission to use providers and the agreed budget into `DECISIONS.md`;
auto review alone does not authorize paid generation. Review the returned TTV
plan's exact prompts, model, variants, duration, references, and costs before
creating `media-generated approve`. Use a keyframe-only approval and a cited
keyframe result when first/last frames need visual review before video generation.

Import approved results and select their takes through `media-generated`.
Use the imported clips as content layers in HyperFrames; keep text, UI, layout,
crop, timing, and overlays editable in the composition. Director notes on those
elements revise HyperFrames source. Notes that change generated footage create a
new TTV request for the affected scene IDs. Keep neighboring takes and resolve
any stale continuity dependencies. See `docs/generated-media.md` for the handoff
example, selection provenance, and portrait EDL options.

## Verification and handoff

Use `lint` for early feedback and `check --snapshots --at-transitions` for the
final browser gate. Read findings and inspect the generated PNGs; a skipped
browser audit is incomplete verification. Use upstream motion intent sidecars
when applicable. Resolve unintended clipping, unreadable text, frozen animation,
and broken transitions. Review playback for reading time, pacing, and audio sync.
Intentional hard cuts or palette changes need visual judgment when delivery
heuristics flag them.

Use the selected review mode for the final preview/render checkpoint within
existing user permissions. Verify rendered duration, resolution, fps, and audio against the
brief with `ffprobe`. For overlays, hand off source/render paths, actual duration,
alpha format, and placement to `media-rough-cut-assembly`; for standalone videos,
handoff the MP4 directly. Run `media-verify` after EDL integration and inspect its
findings. Persist the chosen direction and significant revision decisions in
the slot's `DECISIONS.md`; maintain current canonical copy in the working artifacts.

Keep runtime dependencies such as GSAP in the composition's assets directory
when reproducible offline rendering is required. Follow the installed upstream
contract for dependency loading and language variants; check current CLI help
instead of guessing option syntax. Evaluate lint's sub-composition suggestions
against the project's size and reuse needs.

A contrast result with zero measured elements is missing coverage. Review
transparent graphics on the actual assembled footage, including source labels
and subtitles. Inspect the first and last encoded frames of the assembly and
short clips at both ends. Match overlay coverage to the padded base duration,
allowing for frame rounding. Review the next speaker's first word against the
cut and padding; audio fades do not establish speaker isolation.

ProRes overlays can be large. Retain source and approved renders. Record which
iteration files are superseded and their sizes in the handoff; clean them up
only under the project's retention policy or the user's instruction.
