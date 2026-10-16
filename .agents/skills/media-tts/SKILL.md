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

The command uses `eleven_v4` by default. Set
`ELEVENLABS_MODEL_ID` or pass `--model` when a project needs another model.
Run `media-loudnorm` afterward when the narration needs delivery-level
normalization, then mux it with the rendered video using the rough-cut or
Manim rendering workflow.

## Narration for timed compositions

For narration that drives a timed composition (see
`media-motion-graphics/references/generated-film-playbook.md`):

- **Speed:** `eleven_v4` ignores `--speed`. Control pacing with pauses placed by
  the timing step, not the voice.
- **Two script files:** a plain caption-source script with one paragraph per
  scene and numbers in words, and a `.tts.txt` copy for synthesis. The copy adds
  at most one subtle audio tag per paragraph (`[thoughtful]`, `[curious]`,
  `[warm]`).
- **Pronunciation:** spell out what the voice misreads, such as an acronym it reads
  as a word ("A-P-I").
- **Takes:** voice the whole script as one take, and re-voice the whole script
  when a paragraph changes, so delivery stays consistent.
- **Word timings:** transcribe the take with `media-subtitle --backend
  elevenlabs` for word-level timings, then run
  `media-motion-graphics/scripts/narration_timing.py`. Listen wherever it
  reports a real word difference.
- **Voices from another account:** override the key for that one command and
  pass the voice explicitly. For example:
  `ELEVENLABS_API_KEY="$ELEVENLABS_API_KEY_ALT" media-tts ... --voice-id "$ELEVENLABS_VOICE_ID_ES"`.
