# raea (pilot motion-graphics backend)

[raea](https://github.com/shinyobjectz/raea) is a GPU render engine for video written as React and TypeScript
compositions. This pilot tries it as an alternative to [HyperFrames](HYPERFRAMES.md) for standalone motion
graphics and narrated explainers. It targets two costs: how many tokens an agent spends writing and revising a
composition, and how long a render takes.

The pilot is opt-in. HyperFrames stays the default, and nothing in the HyperFrames workflow changes. An agent
uses the `media-motion-raea` skill only when asked to work on raea.

## Install

```bash
./scripts/install-raea.sh
raea help
```

The script runs raea's own installer pinned to `0.1.0-canary.2` (the release the pilot was checked against;
`RAEA_VERSION` picks another). The installer verifies the tarball's checksum and installs `raea` under
`~/.raea` with a link in `~/.local/bin`. By default it leaves raea's agent skills out of `~/.claude/skills`: the
pilot skill reads them from `~/.raea/share/raea/skills/`, so other agent sessions keep loading the same skills.
`RAEA_SKILLS=1` installs them globally as upstream does.

raea runs on Apple Silicon macOS and x86_64 Linux. It is a canary release that changes daily, so keep the
pinned version until a newer release has been checked. It is licensed FSL-1.1-ALv2: free to use for making
videos, but not for building a product that competes with raea. Each version becomes Apache-2.0 two years after
release.

## How it fits

| Step | HyperFrames path | raea path |
| --- | --- | --- |
| Narration | `media-tts-frames` → `audio_meta.json` | the same, then `media-raea-timing` → `words.json`, `scenes.json` |
| Authoring | HTML/CSS/GSAP per scene, sub-compositions | one `edit.tsx`; scenes are components and their own `<Composition>` |
| Stills | `hyperframes snapshot --at` | `raea render --lite --at` (whole film or `--composition <scene>`) |
| Check | `hyperframes lint`, `check --snapshots` | `raea check --manifest --words` |
| Render | `hyperframes render`, `media-cloud-render` | `raea render` (local GPU) |
| Finish | `finish_delivery.py`, `media-verify`, `renders/<slot>.mp4` | the same |
| Overlays for EDLs | ProRes 4444 with alpha | not yet (see limits) |

`media-raea-timing` reads either a `media-tts-frames` `audio_meta.json` (scenes end to end in frame order,
`--lead` and `--hold` in seconds) or a `narration_timing.py` `timing.json`. It writes:

- `words.json`: film-clock words, which `raea render --words` and `raea check --words` read;
- `words-<scene>.json`: the same words on each scene's clock, for single-scene compositions;
- `scenes.json`: scene windows in seconds and frames (rounded once, so scenes tile exactly), `{@cue}` times
  relative to each scene, voice placements and any caption groups.

It copies voice files into the project's `media/voice/`, since raea serves nothing outside `media/`. The skill
ships a starter composition (`.agents/skills/media-motion-raea/assets/starter/edit.tsx`) already wired to these
files: per-scene compositions, captions grouped from the words, vendored fonts, and cue helpers.

## Pilot benchmark

The test case was a finished HyperFrames short, ported scene for scene to raea with the same copy, cue
times, video plates and voice clips: 78 s at 1080×1920 and 30 fps, with five scenes, three generated video
plates, 42 caption groups and five narration clips. Both renders ran on the same Apple M3 Max laptop, using
HyperFrames CLI 0.8.142 and raea 0.1.0-canary.2.

| | HyperFrames | raea | raea `--lite` |
| --- | --- | --- | --- |
| Full render, wall clock | 49.7 s | 36.0 s | 22.5 s |
| Full render, CPU (user) | 140 s | 37 s | 23 s |
| Three stills | 4.7 s | 17.8 s | 3.7 s |
| Match to the HyperFrames render | — | mean SSIM 0.981 | frame-identical to raea default |

The SSIM minimum (0.886) falls on the three scene cuts, where frame rounding lands each cut one frame apart.
Elsewhere the two renders differ only in antialiasing. `raea check` passed clipping, contrast and freeze checks
on all 96 texts.

What the agent reads and writes:

| | HyperFrames | raea |
| --- | --- | --- |
| Authored source | 38.6 KB: 5 scene files, shared CSS and JS helpers, a build script, the index | 17.6 KB: one `edit.tsx` |
| Generated source the tools report against | 76.8 KB of compiled compositions | none |
| Skill text loaded for a narrated piece | 71 KB (router plus five domain SKILL.md files, before references) | 45 KB (upstream skill plus four guides) |

The HyperFrames slot had already been optimised with its own build script. A stock HyperFrames slot is
closer to the compiled size.

Not measured yet: the tokens an agent spends creating a piece from a brief on each engine, and the tokens per
director note. Those numbers have to come from real sessions. The skill asks each raea slot to record render
times and fallbacks in `DECISIONS.md`.

## Limits found in the pilot

- **No alpha.** A transparent root renders opaque black, even with `RAEA_READBACK=rgba`. Keep EDL overlays on
  HyperFrames.
- **HyperFrames HTML compatibility doesn't run from the release.** `raea render index.html` is meant to render
  HyperFrames-format pages. In canary.2 the release binary looks for its HTML runtime and a `bun` build script in
  the developer's checkout. Recheck this with each release: it would let existing slots render on raea unchanged.
- **Startup pre-pass.** Without `--lite`, every render first steps through the whole timeline (about 16 s on
  the pilot film, even for one still). `--lite` skips it, and its output was identical on the pilot film.
- **Fonts.** A family that isn't installed falls back to a serif without warning. Google Fonts are not fetched
  for React compositions. Vendor the brand's font files into `media/fonts/` with `@font-face`.
- **CSS differences.** Flex needs `display: flex`, `borderStyle` draws every side, boxes default to
  `content-box`, and `animate` tracks ignore `at`. The skill lists these with fixes.
- **`raea check` on other renders** covers sound, loudness and freezes only. Its text checks need raea's render
  manifest.
- **No cloud render.** `media-cloud-render` is HyperFrames-only. raea renders on the local GPU.
