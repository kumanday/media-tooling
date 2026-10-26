---
name: media-teleprompter
description: Use when someone will read a script to camera and wants a teleprompter timed to a reference take (a TTS practice narration, a rough cut, or an earlier recording). Builds a karaoke teleprompter web page with media-teleprompter, where the text scrolls right to left in a thin band at the top of the screen and each word reaches a reading line as it is spoken.
---

# Media teleprompter

`media-teleprompter` turns word timings into a web page that a presenter reads
while recording. The page shows one line of the script in a band at the top of
the screen. The words scroll right to left; each word reaches a thin reading line
at the moment it is spoken in the reference take and fills in while it is spoken.
Pauses in the take slow the scroll, so the presenter keeps the take's pacing and
any graphics, cuts or captions timed to that take still land.

The page is self-contained (`index.html`, plus `voice.mp3` when a reference audio
track is given) and works offline from `file://`.

## Inputs

1. **Word timings**, one of:
   - a `media-subtitle` JSON transcript of the reference take;
   - a narration `timing.json` (`words[]` with `w`, `s`, `e`, `p`), such as the
     motion-graphics playbook's `narration_timing.py` writes;
   - a `media-tts-frames` `audio_meta.json`, read as frames played back to back
     in frame order.
2. **The script** (`--script`, recommended): Markdown or plain text.
   - Headings at the deepest level used start beats; text under higher-level
     headings (a title, an introduction) is not shown.
   - With no headings, each paragraph is a beat.
   - `**Bold**` words are cue words and are underlined on the page.
   - Blockquotes (delivery notes), code blocks, tables and HTML comments are not
     shown.

   The script is aligned to the timed words, so names the transcript spells
   differently still get their own timing. Without a script, the page shows the
   transcript's words and starts a beat after each pause of `--beat-gap` seconds.
3. **The reference audio** (`--audio`, optional): an audio or video file on the
   same clock as the word timings. For a `timing.json`, that is the composition's
   audio (the rough cut), not the raw narration file.

## Standard flow

From a script and a practice voice:

```bash
media-tts script.tts.txt -o take.mp3
media-subtitle take.mp3 --backend elevenlabs --language en --json-out take.json
media-teleprompter take.json --script SCRIPT.md --audio take.mp3 --out teleprompter --title "Product pitch"
```

From a rough cut built on a narration `timing.json`:

```bash
media-teleprompter timing.json --script SCRIPT.md --audio renders/rough-cut.mp4 --out teleprompter
```

The command prints the word, beat and cue counts and the script/timing match. A
match below 0.9 means the script and the take differ. Make the script say what
the take says, or re-transcribe, before handing the page over.

Re-run the command after any re-voice, retime or script edit. The page does not
update itself.

## Numbers

Spelled-out numbers are shown as digits so they read at a glance ("six hundred
seats" becomes "600 seats", "a five-thousand-person pilot" becomes "a
5,000-person pilot").

- `--language en` (default) and `--language es` have number parsers. Other
  languages show numbers as written.
- `--keep-words "half a million"` keeps a phrase in words (repeatable). "half a
  million" and "medio millón" already stay in words.
- `--thousands` sets the separator (`,` for English, `.` for Spanish, `''` for
  none). Years read as quantities ("two thousand twenty-six" becomes "2,026"); keep
  them in words with `--keep-words` if that matters.
- `--no-numerals` shows every number as written.

## Recording with it

- Open `teleprompter/index.html` in a browser and press `F` for full screen.
  Press `H` for the keys.
- Put the reading line next to the camera. The line starts at the horizontal
  centre; `[` and `]` move it, the arrow keys move the band, `+` and `-` change
  the text size. A phone in portrait in front of a laptop leaves the top of the
  screen visible, which is where the band sits by default.
- The reference voice starts muted, because the camera's microphone would record
  it. `M` turns it on for rehearsal; use headphones if recording at the same time.
- `Space` starts after a 3-2-1 countdown. `1` to `9` start at a beat, for
  retakes. `,` and `.` change the speed in 5% steps when the presenter's natural
  pace differs from the take.
- Settings are kept per page title in the browser's local storage.

## Checks before handing it over

- Open the page, press `Space`, and check that the first words fill in as the
  take says them (with `M` on).
- Check a converted number and a cue word in the band.
- State the match ratio and any words the command reported as converted, so the
  presenter knows what to expect.
