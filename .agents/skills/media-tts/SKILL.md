---
name: media-tts
description: Use when generating narration audio from a script for a media project.
---

# Media TTS

Use `media-tts` when a project needs generated narration audio before rendering
or compositing. Keep the script and generated audio in the project workspace.

## ElevenLabs

Install the optional backend and provide credentials through the environment:

```bash
uv tool install --reinstall "media-tooling[elevenlabs] @ git+https://github.com/kumanday/media-tooling"
export ELEVENLABS_API_KEY="..."
export ELEVENLABS_VOICE_ID_EN="..."
```

Do not write either environment value into scripts, project files, or generated
artifacts. The voice ID is selected from `ELEVENLABS_VOICE_ID_EN`, then
`ELEVENLABS_VOICE_ID`, unless `--voice-id` is passed explicitly.

Generate one narration file from a text, Markdown, or SRT script:

```bash
media-tts "$PROJECT_DIR/script.md" \
  --backend elevenlabs \
  --output "$PROJECT_DIR/assets/audio/narration.mp3"
```

An SRT input is flattened in cue order before synthesis. Use `--overwrite` to
replace an existing file or `--skip-existing` for resumable workflows.

The command uses `eleven_multilingual_v2` by default. Set
`ELEVENLABS_MODEL_ID` or pass `--model` when a project needs another model.
Run `media-loudnorm` afterward when the narration needs delivery-level
normalization, then mux it with the rendered video using the rough-cut or
Manim rendering workflow.
