---
name: media-tts
description: Use whenever a video or media project needs narration or voiceover, including inside HyperFrames workflows such as faceless-explainer or product-launch-video. Generates ElevenLabs narration (eleven_v4) as one file or as per-frame clips with word timings and audio_meta.json.
---

# Media TTS

`media-tts` and `media-tts-frames` are the standard way to synthesize narration
in any project, including inside upstream HyperFrames workflows.

- **No local substitutes:** don't write a project-local TTS script, and don't
  call the ElevenLabs API directly.
- **Override upstream defaults:** don't switch to a workflow's built-in
  providers (HeyGen, Kokoro) or to the model an upstream reference names (for
  example `eleven_multilingual_v2` in HyperFrames' `media-use` TTS notes), unless
  the user asks for them.
- **Missing features:** if these commands lack something a workflow needs, extend
  media-tooling and add a test.

## Credentials

Install the optional backend and provide credentials through the environment:

```bash
uv tool install --reinstall "media-tooling[elevenlabs] @ git+https://github.com/kumanday/media-tooling"
media-tooling-link-skills  # ~/.agents, ~/.claude and Antigravity's ~/.gemini skill folders
export ELEVENLABS_API_KEY="..."
export ELEVENLABS_VOICE_ID_EN="..."
```

The full install, update and verification steps are in the toolkit's
`docs/INSTALL.md`.

- **Where keys go:** never write a key or voice ID into scripts, project files or
  generated artifacts. A project may keep them in a dotenv file outside the
  repository and load it into the environment for the command:
  `set -a; source <file>; set +a`.
- **Voice selection:** `--voice-id`, then `ELEVENLABS_VOICE_ID_EN`, then
  `ELEVENLABS_VOICE_ID`. For another language, pass that voice explicitly, for
  example `--voice-id "$ELEVENLABS_VOICE_ID_ES"`.
- **Voices in another account:** if the voice lives in another account, override
  the key for that one command: `ELEVENLABS_API_KEY="$ELEVENLABS_API_KEY_ALT"`.

## Model and delivery

- **Model:** `eleven_v4` is the default for both commands. Override it only when
  the user asks, with `--model` or `ELEVENLABS_MODEL_ID`. Check that a run used
  the model you expect: `media-tts-frames` prints it per frame.
- **Speed:** `eleven_v4` ignores `--speed`. Control pacing with the script
  (sentence length, punctuation) and with pauses placed by the timing step.
- **Tags:** at most one subtle audio tag per paragraph or line (`[thoughtful]`,
  `[curious]`, `[warm]`, `[confident]`). Lowercase tags in square brackets are
  spoken as delivery cues. `media-tts-frames` keeps them out of word timings
  and captions.
- **Pronunciation:** spell out what the voice misreads, such as an acronym it
  reads as a word ("A-P-I"). With `media-tts-frames`, write `[API|A-P-I]`
  inline, or pass `--pronunciations map.json` (`{"Rust": "rast"}`) for every
  occurrence; the voice says the spoken form and captions keep the written one.
- **Cues:** with `media-tts-frames`, put `{@name}` in the spoken text where a
  visual should land ("the graph {@edge} gains an edge"). It is not spoken; the
  frame's `audio_meta.json` entry gets `cues[]` (`name`, frame-relative `t`, and
  the `following` words). Frame builders time each reveal to its cue. Moving a
  cue re-times it from the cached alignment without re-voicing.
- **Re-voicing:** re-voice the whole script when wording changes so delivery
  stays consistent. `media-tts-frames` re-voices only lines whose text changed,
  using neighbouring lines as context.

## One narration file: `media-tts`

```bash
media-tts "$PROJECT_DIR/script.md" --output "$PROJECT_DIR/assets/audio/narration.mp3"
```

The input is text, Markdown or SRT; an SRT is flattened in cue order. Use
`--overwrite` or `--skip-existing`.

For word timings, transcribe the take with `media-subtitle --backend
elevenlabs`. For a narrated HyperFrames film built from one take, run
`media-motion-graphics/scripts/narration_timing.py` on that transcript to get
placed voice segments, scene windows and captions. Then use `media-loudnorm`, or
mux the narration through the rough-cut or render workflow.

## Per-frame narration for HyperFrames workflows: `media-tts-frames`

Upstream HyperFrames workflows (`faceless-explainer`, `product-launch-video` and
the others that share their audio model) read narration from `audio_meta.json`.
`media-tts-frames` produces it from the workflow's own `SCRIPT.md`:

```bash
media-tts-frames SCRIPT.md --hyperframes . --voice-id "$ELEVENLABS_VOICE_ID_ES" --language es \
  [--pronunciations pronunciations.json] [--tail 0.6] [--last-tail 1.6]
node <workflow-skill>/scripts/audio.mjs sync-durations --audio-meta ./audio_meta.json --storyboard ./STORYBOARD.md
```

- **Input:** `SCRIPT.md` in the upstream shape, one `## Line N — label (Frame N)`
  section per frame with the spoken text in an indented block. `**Key:**` rows
  are ignored.
- **Output:**
  - `assets/voice/NN.mp3`;
  - a cache, `assets/voice/.media-tts-frames.json`;
  - `audio_meta.json` with `voices[]`: `frame`, `path`, `duration_s` (clip plus
    tail), `source: "host"`, and frame-relative `words[]` with `id`, `text`,
    `start` and `end`. These timings come from ElevenLabs character alignment,
    so no transcription pass is needed. Frames with cue markers also get
    `cues[]`. Existing `bgm`, `bgm_pending` and `sfx` entries are kept.
- **In the workflow:** this replaces the voice part of the workflow's audio step.
  When the storyboard has `music: none`, or music comes from
  `media-video-music`, skip the workflow's audio generation entirely. Captions,
  assembly and duration sync then read `audio_meta.json` as usual.
- **Checks:** `--dry-run` reports what would be voiced without calling the API;
  `--only 2,5` re-voices selected frames. Spot-check pronunciation by
  transcribing a clip with `media-subtitle --backend elevenlabs`.
- **Built frames:** if frames were already built against an older take,
  re-time them instead of rebuilding them:
  `media-motion-graphics/scripts/retime_frames.py --old-audio-meta old.json
  --new-audio-meta audio_meta.json --frames-dir compositions/frames`.
  Run `--dry-run --audit` first: cue tables (`--time-keys cue,q`), helpers whose
  start is not their last argument (`--helper wipe:1`) and other duration
  variables (`--duration-var D`) need flags, and the audit lists what was not moved.

## Music and sound effects (optional)

Add background music or sound effects only when the user asks for them. For a
finished, picture-locked video, `media-video-music` scores the edit and can
return separate music and SFX stems. See the `media-motion-graphics` playbook,
section 9.

`media-video-music mix` sets the stem levels from the narration it measures.
By default the music bed sits 20 dB under the voice while it speaks (at least
12 dB under at the 10th percentile) and the loudest effect sits 8 dB under
speech level. One linear gain then brings the mix to -14 LUFS, a limiter holds
the true-peak ceiling, and the command prints the margins it measured.
HyperFrames renders carry the narration near -25 LUFS while video-to-music
stems arrive near -13 LUFS, so a fixed gain that suited one film can bury the
voice in the next. Pass `--music-db` or `--sfx-db` only to override a measured
gain on purpose. Report the printed margins with the delivery, and say whether
anyone has listened to the mix.
