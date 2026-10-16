#!/usr/bin/env python3
"""Retime built HyperFrames frames after narration is re-voiced.

Frames authored against one narration take hard-code cue times (GSAP position
arguments, `[selector, time]` pairs, a frame `DUR`). When the narration is
re-voiced, every word moves. This maps each frame's times through a
piecewise-linear warp from the old take's word timings to the new take's, so
reveals stay on their words without rebuilding the frames.

    retime_frames.py --old-audio-meta old/audio_meta.json --new-audio-meta audio_meta.json \
        --frames-dir compositions/frames [--dry-run]

Both files use the HyperFrames frame-keyed `audio_meta.json` shape (voices[] with
frame, duration_s and frame-relative words). Frame N is the file
`<frames-dir>/NN-*.html`. Words are matched by text; a frame whose words differ
is skipped and reported. Rewritten times, outside string literals only:

- `var|let|const DUR = <t>` (the frame duration: old duration_s -> new duration_s);
- the numeric position argument after an object, `{...}, <t>)`;
- `["#id", <t>]` pairs;
- the last numeric argument of a helper call, `name(..., <t>)`;
- `DUR - <t>` expressions.

Tween durations (`duration: 0.5`), staggers and offsets such as `at + 0.05` are
left alone. Every change is printed; inspect the list, and snapshot the frames
before rendering.
"""
import argparse
import bisect
import glob
import json
import os
import re
import sys
import unicodedata

NUM = r'(\d+(?:\.\d+)?)'
RULES = [
    re.compile(r'\b(?:var|let|const)\s+DUR\s*=\s*' + NUM),
    re.compile(r'\}\s*,\s*' + NUM + r'\s*\)'),
    re.compile(r'\[\s*\x00\d+\x00\s*,\s*' + NUM + r'\s*\]'),  # ["#id", t] (strings are masked first)
    re.compile(r'\b[A-Za-z_]\w*\([^()\n]*?,\s*' + NUM + r'\s*\)'),
    re.compile(r'\bDUR\s*-\s*' + NUM),
]
STRING = re.compile(r'"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'|`(?:[^`\\]|\\.)*`')


def norm(t):
    t = unicodedata.normalize('NFKD', t.lower())
    return re.sub(r'[^a-z0-9]', '', ''.join(c for c in t if not unicodedata.combining(c)))


def warp_points(old, new):
    wo, wn = old.get('words') or [], new.get('words') or []
    if [norm(w['text']) for w in wo] != [norm(w['text']) for w in wn]:
        return None
    pts = [(0.0, 0.0)]
    for a, b in zip(wo, wn):
        pts += [(a['start'], b['start']), (a['end'], b['end'])]
    pts.append((old['duration_s'], new['duration_s']))
    pts = sorted(set(pts))
    clean = [pts[0]]
    for p in pts[1:]:  # keep the map monotone
        if p[0] > clean[-1][0] and p[1] >= clean[-1][1]:
            clean.append(p)
    return clean


def warp(pts, t):
    xs = [p[0] for p in pts]
    if t >= xs[-1]:
        return pts[-1][1] + (t - xs[-1])
    i = bisect.bisect_right(xs, t)
    (x0, y0), (x1, y1) = pts[i - 1], pts[i]
    return y0 + (y1 - y0) * (t - x0) / (x1 - x0)


def retime_script(code, pts, dur_old, dur_new):
    strings = []

    def keep(m):
        strings.append(m.group(0))
        return f'\x00{len(strings) - 1}\x00'
    body = STRING.sub(keep, code)
    hits = {}
    for k, rule in enumerate(RULES):
        for m in rule.finditer(body):
            s, e = m.span(1)
            hits.setdefault(s, (e, k))
    out, last, changes = [], 0, []
    for s in sorted(hits):
        e, k = hits[s]
        old = float(body[s:e])
        new = dur_new if k == 0 else warp(pts, old)
        new_txt = f'{new:.2f}'
        out.append(body[last:s] + new_txt)
        last = e
        if abs(new - old) >= 0.005:
            changes.append((old, round(new, 2)))
    out.append(body[last:])
    res = ''.join(out)
    for i, sv in enumerate(strings):
        res = res.replace(f'\x00{i}\x00', sv, 1)
    return res, changes


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--old-audio-meta', required=True)
    ap.add_argument('--new-audio-meta', required=True)
    ap.add_argument('--frames-dir', required=True)
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    old = {v['frame']: v for v in json.load(open(a.old_audio_meta))['voices']}
    new = {v['frame']: v for v in json.load(open(a.new_audio_meta))['voices']}
    status = 0
    for frame in sorted(new):
        files = sorted(glob.glob(os.path.join(a.frames_dir, f'{frame:02d}-*.html')))
        if frame not in old or not files:
            print(f'frame {frame:02d}: skipped (no old voice or no frame file)')
            continue
        pts = warp_points(old[frame], new[frame])
        if pts is None:
            print(f'frame {frame:02d}: SKIPPED, words differ between takes; retime by hand')
            status = 1
            continue
        html = open(files[0], encoding='utf-8').read()
        parts = re.split(r'(<script(?![^>]*\bsrc=)[^>]*>[\s\S]*?</script>)', html)
        total = []
        for i, part in enumerate(parts):
            if part.startswith('<script'):
                parts[i], ch = retime_script(part, pts, old[frame]['duration_s'], new[frame]['duration_s'])
                total += ch
        print(f'frame {frame:02d}: {os.path.basename(files[0])} · duration {old[frame]["duration_s"]} -> {new[frame]["duration_s"]} · {len(total)} times moved')
        for o, n in total:
            print(f'    {o:6.2f} -> {n:6.2f}')
        if not a.dry_run:
            open(files[0], 'w', encoding='utf-8').write(''.join(parts))
    sys.exit(status)


if __name__ == '__main__':
    main()
