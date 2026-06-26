# Hyperframes

Hyperframes is the optional HTML-rendered video path for media-tooling projects.
Use it when a video needs browser-native motion graphics: animated captions, lower thirds, title cards, UI motion, data visuals, website captures, transparent overlays, GIFs, or batch-rendered variants.

Keep using media-tooling for transcription, contact sheets, packed transcripts, EDL assembly, grading, loudness normalization, subtitle burning, and output verification.

## Install

From a media-tooling checkout:

```bash
./scripts/install-hyperframes.sh
hyperframes doctor
```

For a manual install:

```bash
brew install node ffmpeg
npm install -g hyperframes@latest
hyperframes telemetry disable
hyperframes doctor
```

Hyperframes requires Node.js 22 or newer plus FFmpeg and FFprobe. For agent runs, use these environment variables to keep CLI output predictable:

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

Edit the generated HTML/CSS/JS, then validate and render:

```bash
hyperframes lint .
hyperframes inspect . --at-transitions
hyperframes preview . --port 3002 --no-open
hyperframes render . \
  --format webm \
  --output "$PROJECT_DIR/edit/hyperframes/lower-third/render.webm" \
  --quality high
```

Use `--format webm` or `--format mov` for alpha-capable overlays. Use `--format mp4` for standalone segments, `--format gif` for docs and PR previews, and `--format png-sequence` for handoff to tools such as After Effects.

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
      "source": "hyperframes/lower-third/render.webm",
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

- Run `hyperframes lint .`
- Run `hyperframes inspect . --at-transitions`
- Render the intended delivery format with `hyperframes render .`
- If the render is part of an EDL, run `media-edl-render` and `media-verify`
- Keep all composition files and renders under `$PROJECT_DIR/edit/hyperframes/<slot>/`
