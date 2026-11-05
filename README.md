# Media Tooling

Media Tooling lets a coding agent (Claude Code, Codex, Antigravity and others) work on your video and audio
projects. It turns raw recordings into transcripts, subtitles, contact sheets, shot lists and storyboards, then
assembles, grades, checks and delivers the edit. You ask for the outcome; the agent uses the toolkit's skills
and `media-*` commands, and everything it makes stays in your project folder.

It fits podcasts, interviews, tutorials, courses, product videos, explainers, shorts and YouTube uploads.

## Media processing flow

![Media processing flow: source media is processed into transcripts, contact sheets and indexed stills, planned with the agent, assembled into a rough cut or an edited render, self-checked, and delivered. Narration, motion graphics, generated footage and music are created when needed and cut into the edit.](docs/images/media-processing-flow.png)

## Quick start

```bash
brew install uv ffmpeg
uv tool install "media-tooling[elevenlabs] @ git+https://github.com/kumanday/media-tooling"
media-tooling-link-skills                 # lets your agents find the skills

export PROJECT_DIR="$HOME/projects/my-project-media"
media-tooling-init "$PROJECT_DIR"         # project folders plus an AGENTS.md for the agent
cd "$PROJECT_DIR"
```

Then open your agent in `$PROJECT_DIR` and ask for what you want:

```text
Create a 5-minute highlight reel with representative samples of the different speakers and the topics discussed.
```

```text
Turn this session into a short recap that explains the main workflows, tools, and takeaways.
```

```text
Review this processed media project and propose a first-pass rough cut with the strongest clips and any obvious weak spots.
```

The full install, update and troubleshooting steps are in [docs/INSTALL.md](docs/INSTALL.md). It's written so
an agent can follow it: give your agent its URL. More prompts are in [docs/WORKFLOWS.md](docs/WORKFLOWS.md).

## Toolkit commands

| Stage | Command | What it does |
| --- | --- | --- |
| Setup | `media-tooling-init` | Creates a project workspace and its managed `AGENTS.md` block |
| | `media-tooling-link-skills` | Links the skills where coding agents look for them |
| Transcripts and subtitles | `media-subtitle` | Transcript, `.srt` and JSON for one audio or video file |
| | `media-batch-subtitle` | The same for a manifest of files |
| | `media-pack-transcript` | Compact phrase-level transcript for the agent to reason over |
| | `media-translate-subtitles` | Translates subtitles in windows, then re-times the cues |
| | `media-burn-subtitles` | Burns subtitles into a video |
| | `media-batch-burn-subtitles` | The same for a manifest of videos |
| Visual review | `media-contact-sheet` | One image of frames sampled across a video |
| | `media-batch-contact-sheet` | The same for a manifest of videos |
| | `media-timeline-view` | Filmstrip and waveform image at an editing decision point |
| Assembly and finishing | `media-rough-cut` | Quick first-pass cut from cards, image holds and clips |
| | `media-edl-render` | Edited render from an EDL: grading, fades, overlays, subtitles, loudness |
| | `media-grade` | Automatic or preset color grading |
| | `media-loudnorm` | Two-pass loudness normalization (−14 LUFS) |
| | `media-verify` | Self-check of a render against its EDL |
| | `media-fcpxml-export` | FCPXML timeline for DaVinci Resolve |
| Narration and sound | `media-tts` | Narration from a script (ElevenLabs) |
| | `media-tts-frames` | Per-scene narration clips with word timings |
| | `media-teleprompter` | Teleprompter page timed to a reference take |
| | `media-video-music` | Optional music and sound effects mixed under the voice |
| Motion and generated media | `media-generated` | Reviewed requests, imports and take selection for generated footage |
| | `media-cloud-render` | Renders a HyperFrames project on Google Cloud Run |
| | `media-raea-timing` | Narration timing for raea compositions (pilot) |

Flags, backends and behavior for each command: [docs/COMMANDS.md](docs/COMMANDS.md). Optional engines installed
separately: [HyperFrames](docs/HYPERFRAMES.md) and [raea](docs/RAEA.md) (pilot) for motion graphics.

## Agent skills system

![Agent skills system: you ask your coding agent for an outcome; the agent reads the project AGENTS.md written by media-tooling-init and finds the skills linked by media-tooling-link-skills; media-render-pipeline delegates to the ingest, assembly and motion-graphics skills, and narration skills are used directly; each skill runs media-* commands inside the project.](docs/images/agent-skills.png)

`media-render-pipeline` handles "make me a finished video" from end to end. A single job, such as transcribing a
folder or voicing a script, goes straight to the skill that covers it. What each skill does and how the routing
works: [docs/SKILLS.md](docs/SKILLS.md).

## Documentation

| Read | For |
| --- | --- |
| [INSTALL.md](docs/INSTALL.md) | Installing, updating and verifying the toolkit |
| [SETUP.md](docs/SETUP.md) | Project workspaces, optional installs and shell helpers |
| [WORKFLOWS.md](docs/WORKFLOWS.md) | Prompt patterns and runnable command examples |
| [COMMANDS.md](docs/COMMANDS.md) | Every command in detail |
| [SKILLS.md](docs/SKILLS.md) | How prompts route through the agent skills |
| [hard-rules.md](docs/hard-rules.md) | The production rules the renderers enforce |
| [HYPERFRAMES.md](docs/HYPERFRAMES.md) | HTML-rendered motion graphics and overlays |
| [RAEA.md](docs/RAEA.md) | Pilot: raea as a faster motion-graphics backend |
| [generated-media.md](docs/generated-media.md) | Generated footage through TTV providers |
| [CLOUD-RENDER.md](docs/CLOUD-RENDER.md) | HyperFrames renders on Google Cloud Run |
| [LOCAL-CONFIG.md](docs/LOCAL-CONFIG.md) | Private rules, skills and render profiles |
| [EXPORTING.md](docs/EXPORTING.md) | Layered exports for DaVinci Resolve |
| [DEVELOPMENT.md](docs/DEVELOPMENT.md) | Working on the toolkit itself |

## For agents

Inside a project workspace, follow the project's `AGENTS.md` and the skills it lists. Read the docs above when a
task needs detail. [COMMANDS.md](docs/COMMANDS.md) has each command's behavior, [SKILLS.md](docs/SKILLS.md) the
routing, and [WORKFLOWS.md](docs/WORKFLOWS.md) worked examples. To change the toolkit itself, start with the
repo-root [AGENTS.md](AGENTS.md).

Keep reusable code and installs outside the project workspace, and project outputs inside it.
