#!/usr/bin/env python3
"""Rebuild the STORYBOARD.md frame blocks from SOURCE.md and audio_meta.json.

After re-voicing or editing a take, the storyboard's durations, voiceover text
and cue times drift. This rewrites every `## Frame N — Title` block from the
scene source and the current media-tts-frames timings, keeping the storyboard's
frontmatter (with `duration:` set to the new total) and everything before the
first frame block, such as "Video direction".

    storyboard_from_source.py [--status 3=animated ...] [--src 3=compositions/frames/03-demo.html ...]

SOURCE.md holds one block per scene:

    ## Scene 01 — Title
    - transition_in: cut
    - type: hook
    - focal: ...
    - roles: ...
    ### Visual
    Free text; @cue names get the cue time appended, as "@reveal [t=4.20s]".
    ### Narration
    {@reveal}Spoken text with cue marks and [Display|spoken] overrides.

Each frame block gets duration, status, src, voiceover (cue marks removed,
display forms kept), the scene fields, a frame-relative cue timeline from
audio_meta.json cues and the visual direction. src and status come from the
existing storyboard unless --src / --status (repeatable, N=value) override
them; status defaults to outline.
"""
import argparse
import json
import re
import sys

SCENE = re.compile(r'^## Scene (\d+) [—-] (.+?)\n(.*?)(?=^## Scene |\Z)', re.S | re.M)
FRAME_FIELD = r'^## Frame (\d+) [—-] .*?\n(?:(?!^## ).*\n)*?^- {}: (\S+)'
FIELDS = ('transition_in', 'type', 'focal', 'roles')


def section(body, name):
    m = re.search(rf'^### {name}\s*\n(.*?)(?=^##|\Z)', body, re.S | re.M)
    return ' '.join(m.group(1).split()) if m else ''


def field(body, key):
    m = re.search(rf'^- {key}: (.*)$', body, re.M)
    return m.group(1).strip() if m else ''


def frame_fields(storyboard, key):
    return {int(n): v for n, v in re.findall(FRAME_FIELD.format(key), storyboard, re.M)}


def overrides(pairs):
    return {int(k): v for k, v in (p.split('=', 1) for p in pairs)}


def spoken_text(narration):
    """Cue marks removed and [Display|spoken] shown as Display, as captions show it."""
    return re.sub(r'\[([^|\]]+)\|[^\]]+\]', r'\1', re.sub(r'\{@[\w-]+\}', '', narration)).strip()


def frame_block(n, title, body, voice, src, status):
    cues = voice.get('cues', [])
    at = {c['name']: c['t'] for c in cues}
    visual = re.sub(r'@([\w-]+)', lambda m: f'@{m.group(1)} [t={at[m.group(1)]:.2f}s]' if m.group(1) in at else m.group(0),
                    section(body, 'Visual'))
    lines = [f'## Frame {n} — {title}', '', f'- scene: {title}', f"- duration: {voice['duration_s']}s",
             f'- status: {status}', f'- src: {src}', f'- voiceover: "{spoken_text(section(body, "Narration"))}"']
    lines += [f'- {k}: {field(body, k)}' for k in FIELDS]
    lines += ['', "Cue timeline (seconds from this frame's start; reveal each element exactly at its cue, never earlier):",
              '- t=0.00s · frame start']
    for c in cues:
        following = c.get('following') or ''
        if isinstance(following, list):
            following = ' '.join(following)
        lines.append(f"- t={c['t']:.2f}s · @{c['name']} · narration: \"{following}…\"")
    if voice.get('words'):
        end = max(w['end'] for w in voice['words'])
        lines.append(f"- t={end:.2f}s · narration ends; hold the resolved state until frame end t={voice['duration_s']:.2f}s")
    return '\n'.join(lines + ['', visual, ''])


def rebuild(source, storyboard, meta, src=None, status=None):
    voices = {v['frame']: v for v in meta['voices']}
    srcs = {**frame_fields(storyboard, 'src'), **(src or {})}
    stat = {**frame_fields(storyboard, 'status'), **(status or {})}
    first = re.search(r'^## Frame \d+ ', storyboard, re.M)
    head = storyboard[:first.start()] if first else storyboard
    scenes = [(int(n), title.strip(), body) for n, title, body in SCENE.findall(source)]
    if not scenes:
        raise ValueError('no "## Scene N — Title" blocks in the source')
    missing = [n for n, _, _ in scenes if n not in voices]
    if missing:
        raise ValueError(f'scenes {missing} have no voice in audio_meta.json')
    nosrc = [n for n, _, _ in scenes if n not in srcs]
    if nosrc:
        raise ValueError(f'frames {nosrc} have no src in the storyboard; pass --src N=path')
    total = sum(voices[n]['duration_s'] for n, _, _ in scenes)
    head = re.sub(r'^duration: .*$', f'duration: {total:.2f}s', head, count=1, flags=re.M)
    blocks = [frame_block(n, title, body, voices[n], srcs[n], stat.get(n, 'outline')) for n, title, body in scenes]
    return '\n'.join([head.rstrip() + '\n', *blocks]), len(blocks), total


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--source', default='SOURCE.md')
    ap.add_argument('--audio-meta', default='audio_meta.json')
    ap.add_argument('--storyboard', default='STORYBOARD.md', help='read for frontmatter, src and status; rewritten')
    ap.add_argument('--src', action='append', default=[], metavar='N=PATH')
    ap.add_argument('--status', action='append', default=[], metavar='N=STATUS')
    a = ap.parse_args(argv)
    try:
        with open(a.source, encoding='utf-8') as f:
            source = f.read()
        with open(a.storyboard, encoding='utf-8') as f:
            storyboard = f.read()
        with open(a.audio_meta, encoding='utf-8') as f:
            meta = json.load(f)
        text, frames, total = rebuild(source, storyboard, meta, overrides(a.src), overrides(a.status))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 1
    with open(a.storyboard, 'w', encoding='utf-8') as f:
        f.write(text)
    print(f'{frames} frames · {total:.2f}s')
    return 0


if __name__ == '__main__':
    sys.exit(main())
