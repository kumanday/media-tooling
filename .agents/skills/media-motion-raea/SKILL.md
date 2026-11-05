---
name: media-motion-raea
description: Pilot backend for media-motion-graphics that writes narrated explainers and standalone motion graphics as raea React/TypeScript compositions rendered on the GPU, instead of HyperFrames HTML. Use only when the user asks for raea, or for the raea pilot, on a standalone video (not an alpha overlay).
---

# Motion graphics on raea (pilot)

raea renders a composition written in React and TypeScript: give it frame N and it draws frame N. This pilot
swaps HyperFrames for raea as the authoring and render engine. Everything else in `media-motion-graphics` still
applies: review mode, references and brand, directions and the storyboard sheet, director notes, TTV footage,
narration through `media-tts`, delivery under `$PROJECT_DIR/renders/`. Read that skill first, then use this
one wherever it names a HyperFrames command or file.

Use it for standalone videos. Keep alpha overlays for EDL assembly on HyperFrames: raea 0.1.0-canary.2 renders
a transparent background as opaque black. Measurements, limits and the benchmark are in the toolkit's
`docs/RAEA.md`.

## Set up

1. `raea help` (or `~/.raea/bin/raea help`). If it's missing, run the toolkit's `scripts/install-raea.sh`. It
   pins the release the pilot was checked against and leaves `~/.claude/skills` alone.
2. Read the upstream skill once per session: `~/.raea/share/raea/skills/raea/SKILL.md`. Read guides on demand,
   one at a time, with `raea guide NAME`. A narrated piece needs `craft` (the floor), `motion/animating`,
   `motion/words` and `motion/rendering`. Re-read `craft` before the final render, not before every edit.
3. Do not run `raea brand`, `raea cut`, `sao`, `tokensynth` or `fish` unless the user asks for them. Brand,
   footage cutting and audio already have media-tooling owners.

## Where things go

```
$PROJECT_DIR/edit/raea/<slot>/
  edit.tsx                 # the composition (start from this skill's assets/starter/edit.tsx)
  scenes.json words.json words-<scene>.json   # from media-raea-timing; regenerate, never hand-edit
  media/                   # everything the render reads: voice/, fonts/, plates/, stills
  BRIEF.md STORYBOARD.md DECISIONS.md review.md   # as in media-motion-graphics
  stills/ draft.mp4 master.mp4 render.json check.json
```

raea serves only `media/`. Use `staticFile("voice/01.mp3")`, or import files as modules. Copy plates and stills
in. Don't reference `../` or URLs.

## Narration and timing

Voice the script with `media-tts-frames`, as for HyperFrames, then convert its timing:

```bash
media-raea-timing --audio-meta <voice-root>/audio_meta.json --root "$SLOT" --lead 0.5 --scene-ids hook,point,close
```

For a single-take narration cut by `narration_timing.py`, pass `--timing timing.json` instead. The command
writes the film's words, each scene's words, and `scenes.json` (scene windows in seconds and frames, `{@cue}`
times, voice placements, captions when the input has them). It also copies the voice files into `media/voice/`.
Re-run it whenever the narration changes. Cues follow words, so nothing has to be retimed by hand.

## Authoring rules the pilot learned

These are gotchas from porting a finished HyperFrames short. Most come from browser CSS habits:

- **Frames, not seconds.** Convert once (`Math.round(s * fps)`). Cue with the starter's `useWord(scene)("word")`
  or `cue(scene, "name")`, never with typed frame numbers.
- **`animate` tracks key on Sequence frames and ignore `at`.** Key them where they happen:
  `animate={{ width: grow(at, 18, 240) }}` (the starter's helper). Named moves (`enter=`) do honour `at`.
- **Flex needs `display: "flex"`.** `flexDirection`, `gap` and `alignItems` do nothing without it, and `<span>`
  children flow inline: use `<div>` for laid-out parts.
- **Borders:** `borderStyle` on its own draws every side. Use shorthands (`borderTop: "1px solid ..."`).
- **Box sizing defaults to `content-box`.** Set `boxSizing: "border-box"` on bordered cells in grids.
- **Fonts:** a family that isn't installed silently falls back to a serif, and Google Fonts aren't fetched.
  Put the brand's TTF/OTF files in `media/fonts/` and declare them in the starter's `FACES`. Set `fontFamily` on
  every text style. `fontVariantNumeric` works for lining figures.
- `textTransform` isn't needed: upper-case labels in code.
- Register each scene as its own `<Composition>` (the starter does), so a director note on one scene renders only
  that scene.

## Render, look, check

```bash
raea render edit.tsx --lite --words words.json --at 45,150,300 -o stills/              # stills, one batch
raea render edit.tsx --lite --composition point --words words-point.json --at 0,90 -o stills/point/
raea render edit.tsx --lite --words words.json --manifest render.json -o draft.mp4      # timed draft
raea render edit.tsx --words words.json --quality master --manifest render.json -o master.mp4
raea check master.mp4 --manifest render.json --words words.json [--platform shorts] -o check.json
```

- Always pass `--lite` for stills and drafts. Without it, raea first steps through the whole timeline: about
  16 s before a single still of an 80 s film, against about 4 s with it. On the pilot film the two modes'
  output was frame-identical, but render the master without `--lite`.
- Stills replace `hyperframes snapshot`. Compare them with the storyboard sheet as the parent skill describes.
- `raea check` replaces `hyperframes check`. Fix clipped text, contrast and freezes. Its loudness P1 is expected
  before finishing (media-tooling masters loudness). Judge its cue and safe-area findings against the brief:
  a kicker that lands before its word can be intended.
- Finish as for HyperFrames: `scripts/finish_delivery.py` from `media-motion-graphics` (loudnorm, limiter,
  `media-verify`), then deliver to `$PROJECT_DIR/renders/<slot>.mp4`.

## Pilot record

Note in the slot's `DECISIONS.md`: that it was built on raea and which release (`~/.raea/share/raea/VERSION`),
draft and master render times, and anything raea couldn't do that sent you back to HyperFrames. Report the same
in the handoff, so the pilot can be judged on real pieces.
