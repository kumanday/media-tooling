# Command reference

Every `media-*` command the toolkit installs, grouped by stage. The [README](../README.md#toolkit-commands)
has the one-line summary. Each command's `--help` lists its flags, and [WORKFLOWS.md](WORKFLOWS.md#command-examples)
has runnable examples.

Most people never call these directly: they ask for an outcome, and the [skills](SKILLS.md) run the commands.

## Project setup

- `media-tooling-init`
  Creates the standard project directories and writes or refreshes the managed `AGENTS.md` block for a media
  project workspace. If `AGENTS.md` already exists, it updates only its managed block instead of overwriting the
  file. When a local profile applies, it also adds a block for your private rules (see [LOCAL-CONFIG.md](LOCAL-CONFIG.md)).
- `media-tooling-link-skills`
  Links the installed skills, and your private skills from your local config folder, into `~/.agents/skills`,
  `~/.claude/skills` and Antigravity's `~/.gemini/` skill folders so coding agents discover them. Re-run it after
  each upgrade.

## Transcripts and subtitles

- `media-subtitle`
  Generates transcript `.txt`, subtitle `.srt`, and structured `.json` from a single audio or video file.
- `media-batch-subtitle`
  Processes a manifest of spoken-media files sequentially.
- `media-pack-transcript`
  Converts a verbose JSON transcript into a compact, phrase-level Markdown file for agent reasoning.
- `media-translate-subtitles`
  Generates translation template windows from a source `.srt`, then renders translated subtitles back into
  target-language cue breaks without inheriting the source cue boundaries.
- `media-burn-subtitles`
  Burns SRT subtitles into a single video file. Subtitles are applied last in the filter chain.
- `media-batch-burn-subtitles`
  Batch-burns subtitles into a manifest of video files.

Transcription uses a platform-appropriate backend: `lightning-whisper-mlx` on Apple Silicon macOS, and
`faster-whisper` on other workstations. The subtitle commands accept `--backend auto|mlx|faster-whisper`; `auto`
is the right choice in normal use.

For MLX runs, `media-subtitle` performs a timestamp sanity check after transcription. It probes the media
duration and compares it to the transcript's last segment end time. If the duration is near the observed `10x`
MLX compression pattern, it corrects the timestamps and records the correction in the JSON metadata. Pass
`--disable-timestamp-correction` for the raw backend timestamps. [WORKFLOWS.md](WORKFLOWS.md#timestamp-sanity-check)
lists the metadata fields to inspect.

For translated subtitles, don't translate cue by cue from an English `.srt`. Use `media-translate-subtitles` to
group source cues into larger translation windows, then re-segment the translated text inside those windows.

## Visual review

- `media-contact-sheet`
  Generates a contact sheet from a single silent or visual-first video. A contact sheet is one image made from
  frames sampled across the video, so you can see its progression without scrubbing through it.
- `media-batch-contact-sheet`
  Processes a manifest of silent or visual-only videos sequentially.
- `media-timeline-view`
  Generates a filmstrip and waveform composite PNG for visual inspection at editing decision points.

## Assembly and finishing

- `media-rough-cut`
  Builds a first-pass rough cut from a project-local JSON spec of cards, image holds, and clip extracts. A rough
  cut is a fast first assembly for checking structure, pacing, sequencing and missing material before real editing.
- `media-edl-render`
  Renders an assembled video from an EDL JSON spec with per-segment grading, audio fades, overlays, subtitle
  burning, and two-pass loudness normalization.
- `media-grade`
  Applies automatic or preset color grading to a video file.
- `media-loudnorm`
  Two-pass loudness normalization targeting −14 LUFS, −1 dBTP and LRA 11.
- `media-verify`
  Self-evaluates a rendered video against its EDL spec, checking cut boundaries, duration, grade consistency, and
  audio pops.
- `media-fcpxml-export`
  Exports a layered media manifest as FCPXML for DaVinci Resolve import (see [EXPORTING.md](EXPORTING.md)).

## Narration and sound

- `media-tts`
  Generates narration audio from a text, Markdown, or SRT script. ElevenLabs is the current backend (default model
  `eleven_v4`).
- `media-tts-frames`
  Generates per-frame narration clips with word timings and the `audio_meta.json` that HyperFrames workflows (such
  as `faceless-explainer`) consume, from their `SCRIPT.md`.
- `media-teleprompter`
  Builds a karaoke teleprompter web page from word timings (a `media-subtitle` transcript, a narration
  `timing.json` or an `audio_meta.json`) and an optional Markdown script. One line scrolls right to left in a band
  at the top of the screen, and each word reaches a reading line when the reference take speaks it. Spelled-out
  numbers can be shown as digits (English and Spanish).
- `media-video-music`
  Optional: scores a finished video with ElevenLabs video-to-music (separate music and SFX stems), then mixes the
  stems under the narration. The mix measures the narration, sets the music and SFX gains relative to it, ducks the
  music under the voice, normalizes loudness with one linear gain and a true-peak limiter, and prints the measured
  margins.

## Motion graphics and generated media

- `media-generated`
  Reviewed generation requests to TTV providers, verified imports, immutable take selections and reproducible EDL
  renders (see [generated-media.md](generated-media.md)).
- `media-cloud-render`
  Renders a HyperFrames project on Google Cloud Run in parallel chunks, billed to the GCP project its render
  profile names, so client and personal work stay apart (see [CLOUD-RENDER.md](CLOUD-RENDER.md)).
- `media-raea-timing` (pilot)
  Converts `media-tts-frames` `audio_meta.json` or a narration `timing.json` into the words, scene windows and
  voice placements a raea composition reads (see [RAEA.md](RAEA.md)).
- `hyperframes` (optional, installed separately)
  Renders HTML/CSS/JS compositions for animated overlays, title cards, UI captures, GIFs, PNG sequences, batch
  variants, or standalone graphic segments (see [HYPERFRAMES.md](HYPERFRAMES.md)).

## Shell helpers

Optional zsh helpers for working from a repo checkout (see [SETUP.md](SETUP.md#optional-shell-helpers-for-repo-checkouts)):

- `extract`: extracts the audio track from a video as `.m4a`.
- `subtitle`: a convenience wrapper for `media-subtitle`. It accepts the same `--backend` values.
