# Narrated films with generated shots (HyperFrames + TTV + fal.ai)

A method for narrated films that mix four kinds of material:

- generated shots from TTV Pipeline on fal.ai (MiniMax H3 image-to-video);
- real footage: screen captures of a product or app, recordings, data views;
- graphics built in a HyperFrames composition, which owns copy, layout, captions
  and timing;
- a TTS narrator, such as an ElevenLabs voice clone.

It fits product films, explainers, case studies, launch videos and their short
vertical cuts. Each section names the script in `../scripts/` that does the step.
The approval and review rules in `SKILL.md` and `docs/generated-media.md` still
apply. This playbook adds the production method on top of them.

## 1. Plan the film

- **Structure:** one narration paragraph per scene. Give each scene one point,
  shown with the most direct material available: a real capture, a document, a
  chart built from data. As a guide, 3-4 minutes is about 8 scenes, and a 60-100 s
  vertical cut is 5-7.
- **A generated-shot thread:** let generated shots share one invented world, with
  one setting, light and palette, and use them to open chapters. They then form a
  visible thread through the film. Keep each to 5-6 s; H3 takes run 5 or 6 s.
- **Bridges:** a bridge shot starts from a generated keyframe and ends on a real
  frame of the footage that follows (section 5), so the cut into real material is
  invisible. Examples: a generated night sky whose stars become the points of a
  data visualization; a generated workbench that resolves into an app's first
  screen.
- **No speech in generated shots.** The narrator carries the words. Generate
  ambient sound and Foley separately (section 9).
- **State what verification found.** When a check flags something, say so and
  show it rather than implying a pass. Label placeholder footage on screen until
  the real material replaces it.
- **Review:** record the agreed review mode in `BRIEF.md`. A common split: the
  user reviews the script and storyboard, then the slot runs in
  `review-mode: auto`.
- **Budget:** record the user's budget and provider permission in `DECISIONS.md`
  before any paid generation. fal reports billable units rather than dollars, so
  USD stays unknown in the ledger (`media-generated cost`). Compare units with
  fal's current pricing.

## 2. Storyboard to TTV request

Export the reviewed scenes as `storyboards/storyboard-N/storyboard-N.source.json`
(shape in `docs/generated-media.md`). Points that matter:

- **Intent:**
  - `intent.entry_state` is the keyframe prompt. Write it as a still, with style
    and constraints, for example "Photographic film still, cinematic, fine film
    grain ... No people, no readable text, letters, numbers or logos."
  - `intent.summary` describes the motion and ends with the sound policy, for
    example "No speech, no voices, no music."
  - `intent.exit_state` describes the last frame. For a bridge, describe the
    real frame the shot must land on.
- **References:** `reference_assets` carry `role: first_frame` or `last_frame`,
  a `rights_note` saying where the image came from, and its SHA-256. Record every
  crop or extraction that produced a reference in
  `generation/references/derivations.json` (source, crop box, output hash).
- **Continuity:** use `continuity.mode: continue_from_previous` for chains of
  generated shots, and `independent` for standalone shots and bridges.
- **Delivery:** 1920×1080 or 1080×1920.
- **Revisions:** every change is a new storyboard revision with a
  `revision-note.md`, added to `motion_review.evidence` with its hash.

## 3. Keyframes

- **Default provider:** OpenAI `gpt-image-2.5-sunburst` through TTV's
  `image_generation_gateway`. The key comes from the env var named in
  `api_key_env`. Native 16:9 is `2560x1440` at `quality: high`. Any size works if
  both sides are divisible by 16 and the longest edge is at most 3840.
- **Gateways:** for an OpenAI-compatible gateway, add `base_url`, and add
  `default_headers` only when the gateway documents them; one gateway broke
  multipart image requests when sent an empty metadata header. Probe a new
  gateway at zero cost with an invalid size: it must reject the size, not the
  credentials.
- **Gemini (`gemini-3-pro-image`, `image_size: 2K`):** also works. Make sure the
  delivery aspect ratio is requested, and check for square canvases or
  pillarboxing; derive a clean crop if needed.
- **Review before video:** run a keyframe-only approval (`ttv_round.py execute
  --mode keyframes`), make a contact sheet of the keyframes, and review it
  before generating video.

## 4. Video passes

`scripts/ttv_round.py` runs one file-handoff round:
1. `plan` is free. It prints prompts, models and variants for review.
2. `execute` records the approval, runs the job and imports the result.

The runtime config goes to TTV through a pipe, so keys stay in the environment.

- **Drafts:** `minimax/h3-max-turbo/image-to-video` at `768P` (observed: about
  8 fal units per 5 s).
- **Finals:** `minimax/h3-max/image-to-video` at `1080P` (observed: 16 units per
  5 s, 19.2 per 6 s).
- **Resolution** comes from the runtime config (`--resolution`), not from the plan.
- **Comparison reels:** when choosing a keyframe source or video model, build a
  side-by-side reel per shot (for example two keyframe sources × two video
  models) before deciding.
- **Takes run slightly long:** a "6 s" take can measure 6.6 s. Use the measured
  length when a bridge must land on its last frame.

Selections are immutable. `media-generated select` refuses an existing
`edit_revision_id`, so a corrected trim needs a new edit ID. Keep each draft in
`rough-cuts/manifests/drafts/`.

## 5. Bridges onto real frames

1. **Capture first.** Capture the real footage the bridge will cut into
   (section 8).
2. **Choose the frame.** Take its first frame and crop it to a region free of UI
   chrome and small text. Generated motion lands best on simple, high-contrast
   content, so hide labels, toolbars and tooltips in that capture when they
   aren't the point.
3. **Scale and record.** Scale the crop to the delivery size and save it under
   `generation/references/` with a derivation record.
4. **Request it.** Make a new storyboard revision with that image as
   `last_frame`, then run `media-generated regenerate <storyboard> <edit> --scene
   <id>`, send, and run a Max round. Compare the take's final frame with the
   reference before using it.
5. **Join it in the composition.** Start the capture 0.3 s before the take ends,
   with a 0.3 s fade-in over it. Start the capture scaled so the crop fills the
   frame, then animate to scale 1, so the shot opens out into the full interface.
   For a crop at (x0, y0, w, h) in a 1920×1080 frame:

   ```
   s  = 1920 / w
   ox = x0 * s / (s - 1)      # transform-origin x, px
   oy = y0 * s / (s - 1)      # transform-origin y, px
   tl.fromTo(cam, {scale: s}, {scale: 1, duration: 2.6, ease: "power2.inOut"}, t)
   ```
6. **Show the frame match** when the film is about how it was made: put the
   take's own last frame beside the capture's first frame.

## 6. Revisions and continuity

- **Regenerate only the changed scene,** from a new storyboard revision. Every
  other take keeps its ID and hash.
- **Supply the boundary:** a `continue_from_previous` scene regenerated alone
  needs the previous take's last frame as its `first_frame`, with
  `source_take_id`. Otherwise TTV fails with "Continuity needs a supplied or
  successfully generated previous boundary".
- **Resolve downstream shots:** shots that continued from the old take need a
  continuity decision (`accept_stale`, `use_boundary` or `regenerate`) before
  selection compiles.
- **Verify generated sequences on their own** (`media-generated render <edit>
  --preview --no-loudnorm`). A planned lighting change, such as a bright interior
  cutting to a dark exterior, will fail `grade_consistency`. Trim the shot or
  state it; automatic grading may not resolve it.

## 7. Narration

Narration always goes through media-tooling: `media-tts` for one take, or
`media-tts-frames` for per-frame clips with word timings and `audio_meta.json`.
That holds inside upstream HyperFrames workflows too (see the `media-tts`
skill). The single-take method below suits a long continuous film built in its
own composition. `media-tts-frames` suits frame-based workflows such as
`faceless-explainer`.

- **Two files:**
  - `script.md` is the caption source: plain text, one paragraph per scene,
    numbers in words.
  - `script.tts.txt` is the same text plus at most one subtle ElevenLabs v4 tag
    per paragraph (`[thoughtful]`, `[curious]`, `[warm]`, `[confident]`).
- **Pronunciation:** spell what the voice misreads, such as an acronym it reads
  as a word ("A-P-I"). Use the convention that works in each language.
- **One take:** voice the whole script with `media-tts --model eleven_v4`.
  `eleven_v4` ignores `--speed`, so pacing comes from the timing script's gaps,
  not the voice.
- **Word timings:** transcribe the take with `media-subtitle --backend
  elevenlabs --language <code>`. The transcript writes numbers as digits ("$42",
  "18"), and the timing script interpolates those words. Listen wherever it
  reports a real word difference.
- **Re-voice the whole script** when a paragraph changes, so delivery stays
  consistent.
- **Second-language cut:** write its own script; it can be shorter where the
  audience needs less detail. Use that language's voice, with a separate key if
  the voice lives in another account:

  ```bash
  ELEVENLABS_API_KEY="$ELEVENLABS_API_KEY_<ALT>" media-tts script.tts.txt -o out.mp3 \
    --model eleven_v4 --voice-id "$ELEVENLABS_VOICE_ID_ES"
  ```

`scripts/narration_timing.py` turns the take into placed voice segments, scene
windows, output-time word clocks and caption groups (see its docstring). Tune
`--gaps` and `--scene-lead` per boundary. A chapter that opens on a generated
shot needs a scene lead of 2-4 s, so the shot plays before the first word. Use
`--caption-chars 46` for landscape and 28 for portrait.

### Surgical voice edits (media-tts-frames takes)

Once a per-frame take is approved, small notes (a longer pause, a dropped
phrase, one added sentence) don't need a re-voice, which would change the
delivery of the whole line. These scripts edit the clip in place and keep
`audio_meta.json` and the media-tts-frames cache coherent, so a later
`media-tts-frames` run is a cache hit and writes the same timings back. Each
copies the originals into `--backup` first; join points land on the quietest
10 ms of an inter-word gap, never inside a word, with 30 ms fades. See each
script's docstring.

1. **Holds:** `scripts/insert_holds.py --backup qa/voice-backup 2:launch:1.5
   4:today#2:2.0` adds 1.5 s of silence after "launch" in frame 2 and 2 s after
   the second "today" in frame 4. The text and cache hash don't change.
2. **Cuts:** edit `SCRIPT.md` first, keep the old copy, then `scripts/splice_takes.py
   --backup qa/voice-backup --tts-args "<media-tts-frames options>" cut 3 Well,
   today --old-script qa/SCRIPT.before.md` removes "Well," up to the gap before
   "today". The hash, words, cues and `duration_s` are rebuilt for the new text.
3. **Appends:** voice only the new sentence with `media-tts-frames` in a scratch
   root (same frame number, voice and options), add it to the frame's line in
   `SCRIPT.md`, then `scripts/splice_takes.py --backup qa/voice-backup --tts-args
   "<options>" append 5 qa/scratch-frame-05 --gap 0.75`.
4. **Frames:** run `scripts/retime_frames.py` with the backup's
   `audio_meta.json` as `--old-audio-meta`, so built frames follow the edited take.
5. **Storyboard:** when the composition keeps a scene source (`SOURCE.md`, one
   `## Scene N — Title` block with fields, `### Visual` and `### Narration`),
   `scripts/storyboard_from_source.py` rebuilds every `STORYBOARD.md` frame
   block from it and the new `audio_meta.json`: durations, voiceover, the cue
   timeline and `@cue [t=..]` marks in the visual direction. It keeps the
   frontmatter (with the new total), "Video direction", and each frame's `src`
   and `status`.

`--tts-args` must repeat the options the take was voiced with (voice, model,
language, settings, pronunciations, `--tail`): the cut refuses to run when the
cached hash doesn't match.

## 8. Real footage capture

- **Browser:** use Playwright with Google Chrome (`channel: 'chrome'`, headless)
  at 1920×1080, `deviceScaleFactor: 2`. For WebGPU pages, add
  `--enable-unsafe-webgpu --enable-gpu --ignore-gpu-blocklist`. Playwright's
  headless shell has no WebGPU adapter; Chrome's headless mode does.
- **Drive the app through its own API or URL state** when it has one
  (`window.app.*`, query parameters, a command palette), rather than through
  pixel coordinates. That gives exact, repeatable states. Save the app's state
  description beside each still if it offers one.
- **Capture motion frame by frame:** use `scripts/frame_capture.cjs`. A scenario
  file sets cursor moves, clicks, eased scrolling and eased app-state tweens per
  frame (for example zooming a chart or map through the app's viewport function).
  The tool screenshots every frame and encodes at 30 fps. Schedule cues from the
  narration's word times, so one continuous take lines up with the words.
- **Apps that render asynchronously** (map tiles, WebGL scenes): give the scenario
  a `frame` hook. It runs on every frame and is awaited, so the page can set its
  own state from the clip time and wait until it is ready (for example, tiles
  loaded) before the screenshot. A tween's `apply` may also return a promise.
- **Never use the CDP screencast** for delivery footage. It returned a cropped
  1920×993 viewport at 1×, and encoding to 16:9 stretched it about 9%.
- **Hiding UI:** hiding labels, sidebars or toasts (the scenario's `css` and
  `shadowCss`) is a presentation choice. Write it in the capture README.
- **Privacy:** check every frame for paths, tokens, emails and private records
  before use. Keep a README and `hashes.json` per capture directory.
- **Vertical (9:16) versions:** crop the 2× frames directly, so the crops stay
  sharp.

## 9. Sound

- **Mute the H3 audio** in every case. Its own soundtrack can hold music or
  garbled speech.

Music and sound effects are optional. Add them only when the user asks for them;
a narrated film can also ship with narration alone.

- **Scoring a finished video:** use `media-video-music` (ElevenLabs
  video-to-music). It scores the picture-locked edit from its own cuts and
  motion, and with `--sfx` it adds effects on separate stems.

  ```bash
  media-video-music generate renders/film.mp4 --out-dir assets/score --sfx \
    --description "Quiet, modern underscore for a calm narrated film; leave room for the voice; no vocals" \
    --tag minimal --tag ambient
  media-video-music mix renders/film.mp4 --music assets/score/music.mp3 --sfx assets/score/sfx.mp3 \
    -o renders/film-music.mp4 [--lufs -14 --true-peak -1]
  ```

  - **Input:** generate from the final cut, at most 200 MB and 600 s. The stems
    match its length; re-score after any timing change.
  - **What comes back:** the ZIP holds `music.mp3` and `sfx.mp3`. The music
    arrived mastered at about -13 to -16 LUFS. The effects were sparse hits
    around cuts and on-screen events, peaking around -7 dBFS.
  - **Narration audio:** leave `--use-audio-as-reference` off for narrated
    videos. It would read the narration as a musical reference.
  - **Mixing:** `mix` measures the narration and both stems (EBU R128
    momentary loudness) and sets the gains from them. The ducked music bed sits
    20 dB under the voice while it speaks, at least 12 dB under at the 10th
    percentile, with the SFX counted as part of the bed. The loudest effect sits
    8 dB under speech level. The narration keys a sidechain compressor whose
    threshold follows the narration's own loudness. One linear gain brings the
    mix to `--lufs`, and a 4x-oversampled limiter holds `--true-peak`; the encode
    is re-measured and corrected until both hold. The command prints the gains
    and the measured margins, including the bed level in narration pauses.
    `--music-under-db`, `--music-min-under-db` and `--sfx-under-db` change the
    targets. `--music-db` and `--sfx-db` fix a gain instead.
  - **Why the gains are measured:** the old fixed defaults (music -10 dB, SFX
    -4 dB) suited a normally leveled voice. On a narrated explainer the
    HyperFrames render carried the narration at -25.9 LUFS and the music stem
    arrived at -13.2 LUFS. The fixed gains left the bed 0.6 dB under the voice
    while it spoke, 3 dB above speech level in pauses, and SFX hits 7.7 dB above
    speech, and the single-pass dynamic loudnorm lifted the pauses further.
    Whole-file loudness and `media-verify` passed that mix, yet the narration
    was hard to follow. Measured gains on the same film came out at music
    -30.1 dB and SFX -16.9 dB: the bed 20.7 dB under the voice (12.1 dB at the
    10th percentile), 17.1 dB under speech level in pauses, and the loudest SFX
    8.0 dB under speech.
  - **Limiter report:** TTS narration often has a high peak-to-loudness ratio.
    On two narrated films the limiter took up to 5.6 dB and 9.1 dB off the
    loudest peaks to hold -1 dBTP at -14 LUFS. If the reduction sounds
    audible, lower `--lufs`.
  - **Delivery:** deliver the mixed version as a variant
    (`renders/<slot>-music.mp4`) beside the narration-only file.
  - **Inside a HyperFrames workflow:** to place the stems in the composition
    instead, list them in `audio_meta.json` as host audio. The music goes in as
    `bgm` with `source: "host"` and `music: none` in the storyboard. The SFX
    stem goes in as an `sfx` entry on frame 1 at offset 0 for the full length.
- **Prompted cues:** for effects or a bed written to a prompt instead of scored
  from the picture, use `scripts/elevenlabs_sfx.py` (one cue per generated shot,
  on alternating audio tracks) and `scripts/elevenlabs_music.py` (an
  instrumental bed longer than the film). Play the bed at volume 0.15-0.16 and
  carve it under the voice with the HyperFrames audio carve script. Pass
  `--core <dir with node_modules/@hyperframes/core>` when the slot has no
  `node_modules`.
- **Extending a bed:** to extend a reviewed bed without regenerating it, repeat a
  middle section with a 4 s `acrossfade` at matching levels. Check the level
  profile first.

## 10. Composition patterns (HyperFrames)

- **Build from data:** generate `index.html` from `timing.json` and a
  `data.json` that a prep script fills from project records: take IDs and hashes,
  plan and approval fields, cost rows, tables from source documents. Never
  hard-code an ID or number that a record holds.
- **Cue every element to a spoken word:** a `W(prefix, after)` helper returns a
  word's start time from `timing.json`.
- **Media** goes in non-timed wrappers whose opacity the root timeline drives,
  each `<video>` with its own `data-start`, `data-duration` and
  `data-media-start`. Never put a video inside a timed `section.clip`. Stills
  need a timed parent.
- **Text and graphics** go in timed `<section class="clip">` elements.
- **Layering:** captions at z-index 30 and chrome (chapter tag, chips) at 20.
  Chapter tags over full-frame UI captures need a solid backing.
- **Animate with transforms,** not `left`/`top` (lint error).
- **Placeholders:** labeled on screen, and removed when real footage arrives.
- **Portrait safe area:** nothing important above y=150. Captions sit at about
  y 1400-1500, and the right 120 px of the lower half stays clear. Charts and
  cards drawn from data read better on a phone than dense UI captures do.
- **Checks:** `hyperframes lint .`, then `hyperframes snapshot . --at <times>
  --describe false` at narration moments. Inspect the contact sheets, fix, and
  re-snapshot. Then render with `hyperframes render . -o renders/<name>-master.mp4`.

## 11. Finishing and verification

- **Finish:** `scripts/finish_delivery.py` runs `media-loudnorm`, then
  `alimiter` (true peak at or below -1 dBTP; limit 0.74-0.80 gave about
  -1.6 dBTP), measures, and runs `media-verify` through a single-range EDL
  wrapper. Write the delivery to `$PROJECT_DIR/renders/<slot>[-vN|-<lang>].mp4`.
- **`grade_consistency` on a whole film** compares five evenly spaced frames, so
  a multi-scene film can fail by comparing unrelated scenes, such as a dark UI
  capture against a bright exterior. Extract the named worst pair, look at it,
  and report the result honestly.
- **Check joins in the delivered file:** take frame strips across bridge joins,
  `ffmpeg -ss T -t 2.4 -i out.mp4 -vf fps=5,tile=4x3`.

## 12. Variants

- **Language cut:** copy the slot. Put language-specific scene blocks in their
  own file and assemble the build from shared helpers. Re-voice, retime, give it
  its own bed length, and drop brand marks or calls to action when the audience
  requires it.
- **Vertical short (9:16, up to 3 min):** a new slot with its own shorter script.
  Replace internal names and jargon with terms outsiders understand. Use one-line
  captions, data-built charts and portrait crops.
- **Thumbnails:** write an HTML page, render it with `scripts/html_still.cjs`
  at 1080×1920 (Shorts feed) and 1280×720 (search and embeds), and export JPG
  under 2 MB. Use one real visual from the film and one large number or claim.

## 13. Records

Each slot keeps the following:
- `BRIEF.md` (review mode);
- `DECISIONS.md` (every generation round with IDs, every narration take with
  duration and match ratio, every defect and fix);
- `SCRIPT.md` / `STORYBOARD.md` updated to the current cut.

The project keeps:
- `edit/project.md`;
- `storyboards/` revisions with notes;
- `generation/references/derivations.json`;
- the handoff documents and `generation/logs/cost-*.json`;
- a README and hashes per capture directory.

Keep scratch scripts out of temporary directories once they work: move them into
the slot's `tools/` or this skill's `scripts/`.

## 14. Credentials

- **Keys stay in the environment** (`FAL_KEY`/`FAL_API_KEY`, `OPENAI_API_KEY`,
  `GEMINI_API_KEY`, `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID_EN`/`_ES`). Use a
  login shell or a dotenv file outside the repo. Never put them in YAML on disk,
  project files, command lines or logs.
- **Don't print key files:** never print shell rc or `.env` files, even through a
  grep with a masking pattern. Masks miss token formats.
- **To run under a login shell,** use `zsh -lic '...'`. To prove a key exists
  without printing it, use `[ -n "$VAR" ]`.
- **Organization tokens:** use them per command,
  `GH_TOKEN="$GH_TOKEN_<ORG>" gh pr create ...`.

## Pitfalls seen in production

| Symptom | Cause | Fix |
|---|---|---|
| TTV run fails "Continuity needs ... previous boundary" | single-scene regenerate of a `continue_from_previous` scene | supply the previous take's last frame with `source_take_id` |
| `select` refuses a corrected edit | selection IDs are immutable | new `edit_revision_id` |
| Keyframes square or pillarboxed | aspect ratio not requested | request it; derive a crop |
| H3 audio has music or speech | model soundtrack | mute; generated SFX |
| Voice reads an acronym as a word | pronunciation | spell it in the TTS text |
| `--speed` has no effect | `eleven_v4` ignores it | pace with gaps |
| A session wrote its own TTS script, or used an older model | an upstream workflow's TTS step, or a reference naming another model | `media-tts` / `media-tts-frames`; extend media-tooling if a feature is missing |
| A small voice note means re-voicing a whole approved line | no surgical edit path | `scripts/insert_holds.py` for pauses, `scripts/splice_takes.py` for cuts and appended sentences, then `scripts/retime_frames.py` |
| Frames out of sync after re-voicing | cue times hard-coded from the old take | `scripts/retime_frames.py`; for cue tables and helpers whose start is not the last argument add `--time-keys` / `--helper NAME:IDX`, then read `--audit` |
| Map or WebGL capture has missing or blurry tiles | screenshot taken before the app finished loading | `frame_capture.cjs` `frame` hook that awaits the app's readiness |
| Timing reports "no silence before segment" | two sentences voiced without a pause | merged automatically; otherwise re-voice |
| Lint error on animated position | `left`/`top` tweens | transforms |
| Captions hidden behind media | z-index | captions 30, chrome 20 |
| Duplicate audio track warning | adjacent cues on one track | alternate tracks |
| Captured UI stretched and soft | CDP screencast frames | `frame_capture.cjs` |
| WebGPU or WebGL canvas blank in capture | Playwright headless shell | Chrome channel with GPU flags |
| True peak above -1 dBTP after loudnorm | loudnorm overshoot | `alimiter` |
| Music and SFX drown the narration although whole-file LUFS and `media-verify` pass | fixed mix gains against a quiet narration (HyperFrames renders near -25 LUFS, stems near -13 LUFS) | `media-video-music mix` with measured gains; read the margins it prints |
| SVG line draw with `pathLength=1` sits undrawn, then pops in | GSAP rounds px values by default, so a `stroke-dashoffset` tween from 1 to 0 snaps to whole numbers | `autoRound: false` in the tween vars |
| Carve script cannot find `@hyperframes/core` | slot without node_modules | `--core <dir>` |
| `media-verify` grade failure on a whole film | samples unrelated scenes | inspect the pair; report |
| zsh `====` or `$var` loops misbehave | zsh globbing and word splitting | quote, use `${=var}`, or use Python |
