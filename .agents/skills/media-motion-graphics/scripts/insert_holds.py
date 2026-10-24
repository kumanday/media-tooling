#!/usr/bin/env python3
"""Insert silent holds into approved media-tts-frames clips without re-voicing them.

Each hold is FRAME:WORD:SECONDS: WORD is the spoken word (as in audio_meta.json
words[]) after which the hold goes. Case and surrounding punctuation are
ignored; if the word occurs more than once in the frame, append #N (1-based).
The cut lands on the quietest 10 ms between that word's end and the next word's
start (never inside a word), with 30 ms fades on both sides of the silence.

    insert_holds.py --backup qa/voice-backup 2:launch:1.5 4:today#2:2.0

Run it from the composition root (or pass --root) with the Python that has
media-tooling installed (it needs numpy; ffmpeg and ffprobe on PATH).

Updated in place, after copying the originals into --backup (an existing backup
of a file is kept, so the folder always holds the pre-edit take):
<voice-dir>/NN.mp3, audio_meta.json (words, cues, duration_s) and the
media-tts-frames cache (words, char_starts, audio_s). The cache hash is
unchanged because the text is, so a later media-tts-frames run is a cache hit
and writes the same timings back. Then run retime_frames.py on built frames.

The audio helpers here are shared with splice_takes.py.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys

import numpy as np

SR = 44100
FADE = 0.03
WINDOW = 0.01
CACHE_NAME = '.media-tts-frames.json'


def read_pcm(path):
    out = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', path, '-ac', '1', '-ar', str(SR), '-f', 'f32le', '-'],
                         capture_output=True, check=True).stdout
    return np.frombuffer(out, dtype=np.float32)


def quietest(x, lo, hi):
    """Centre (s) of the quietest 10 ms window that starts in [lo, hi - 10 ms]."""
    win = int(WINDOW * SR)
    lo_i = max(0, int(lo * SR))
    hi_i = max(lo_i + 1, int(hi * SR) - win)
    best = min(range(lo_i, hi_i, int(0.002 * SR)), key=lambda s: float(np.sqrt(np.mean(x[s:s + win] ** 2))) if x[s:s + win].size else 0.0)
    return round((best + win / 2) / SR, 3)


def render(parts, out, fade=FADE):
    """Join parts into a mono mp3. A part is (path, start, end|None) or ('silence', seconds).

    Every cut edge gets a fade: in when a segment starts after 0, out when it ends before the file does.
    """
    inputs, graph, labels = [], [], []
    for i, part in enumerate(parts):
        if part[0] == 'silence':
            graph.append(f'aevalsrc=0:d={part[1]}:s={SR}[p{i}]')
        else:
            path, start, end = part
            if path not in inputs:
                inputs.append(path)
            seg = (f'[{inputs.index(path)}:a]aresample={SR},aformat=channel_layouts=mono,atrim=start={start}'
                   + (f':end={end}' if end is not None else '') + ',asetpts=PTS-STARTPTS')
            if start > 0:
                seg += f',afade=t=in:st=0:d={fade}'
            if end is not None:
                seg += f',afade=t=out:st={end - start - fade:.3f}:d={fade}'
            graph.append(seg + f'[p{i}]')
        labels.append(f'[p{i}]')
    graph.append(''.join(labels) + f'concat=n={len(labels)}:v=0:a=1[out]')
    args = ['ffmpeg', '-nostdin', '-v', 'error', '-y']
    for path in inputs:
        args += ['-i', path]
    subprocess.run(args + ['-filter_complex', ';'.join(graph), '-map', '[out]', '-ar', str(SR), '-ac', '1',
                           '-c:a', 'libmp3lame', '-b:a', '192k', out], check=True)


def duration(path):
    out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path],
                         capture_output=True, text=True, check=True).stdout
    return round(float(out), 3)


def norm(word):
    return re.sub(r'^\W+|\W+$', '', word).casefold()


def find_word(words, spec, after=-1):
    """Index of WORD or WORD#N (1-based occurrence) in words[] after index `after`."""
    name, _, nth = spec.partition('#')
    hits = [i for i, w in enumerate(words) if i > after and norm(w['text']) == norm(name)]
    if len(hits) < int(nth or 1):
        raise ValueError(f'word {spec!r} not found in {" ".join(w["text"] for w in words)!r}')
    return hits[int(nth or 1) - 1]


class Project:
    """audio_meta.json and the media-tts-frames cache of one composition root."""

    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.meta_path = os.path.join(self.root, 'audio_meta.json')
        with open(self.meta_path, encoding='utf-8') as f:
            self.meta = json.load(f)
        if not self.meta.get('voices'):
            raise ValueError(f'{self.meta_path} has no voices')
        voice_dir = os.path.dirname(os.path.join(self.root, self.meta['voices'][0]['path']))
        self.cache_path = os.path.join(voice_dir, CACHE_NAME)
        with open(self.cache_path, encoding='utf-8') as f:
            self.cache = json.load(f)

    def voice(self, frame):
        voice = next((v for v in self.meta['voices'] if v['frame'] == frame), None)
        if voice is None or str(frame) not in self.cache:
            raise ValueError(f'frame {frame} is not in {self.meta_path} and the media-tts-frames cache')
        return voice, self.cache[str(frame)], os.path.join(self.root, voice['path'])

    def backup(self, backup_dir, *paths):
        os.makedirs(backup_dir, exist_ok=True)
        for path in (self.meta_path, self.cache_path, *paths):
            dst = os.path.join(backup_dir, os.path.basename(path))
            if not os.path.exists(dst):
                shutil.copy2(path, dst)

    def save(self):
        for path, data in ((self.meta_path, self.meta), (self.cache_path, self.cache)):
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=1, ensure_ascii=False)


def parse_hold(spec):
    frame, word, seconds = spec.rsplit(':', 2)
    return int(frame), word, float(seconds)


def plan_holds(words, holds, x):
    """holds: [(WORD[#N], seconds)] -> sorted [(cut_s, seconds, word_index)]."""
    cuts = []
    for spec, seconds in holds:
        i = find_word(words, spec)
        nxt = words[i + 1]['start'] if i + 1 < len(words) else words[i]['end'] + 0.3
        cuts.append((quietest(x, words[i]['end'] - 0.05, nxt + 0.03), seconds, i))
    return sorted(cuts)


def shifter(cuts):
    return lambda t: round(t + sum(sec for at, sec, _ in cuts if t >= at), 3)


def apply_holds(voice, rec, cuts):
    """Shift the voice entry's and cache record's timings past each cut; returns the seconds added."""
    shift = shifter(cuts)
    for w in voice['words']:
        w['start'], w['end'] = shift(w['start']), shift(w['end'])
    for c in voice.get('cues', []):
        c['t'] = shift(c['t'])
    added = round(sum(sec for _, sec, _ in cuts), 3)
    voice['duration_s'] = round(voice['duration_s'] + added, 2)
    rec['words'] = voice['words']
    rec['char_starts'] = [shift(t) for t in rec.get('char_starts', [])]
    rec['audio_s'] = round(rec['audio_s'] + added, 3)
    rec.setdefault('edits', []).append({'op': 'holds', 'holds': [
        {'after_word': voice['words'][i]['text'], 'at': at, 's': sec} for at, sec, i in cuts]})
    return added


def hold_parts(clip, cuts):
    parts, prev = [], 0.0
    for at, sec, _ in cuts:
        parts += [(clip, prev, at), ('silence', sec)]
        prev = at
    return parts + [(clip, prev, None)]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('holds', nargs='+', metavar='FRAME:WORD[#N]:SECONDS')
    ap.add_argument('--root', default='.', help='composition root (holds audio_meta.json)')
    ap.add_argument('--backup', required=True, help='folder for the pre-edit audio_meta.json, cache and clips')
    a = ap.parse_args(argv)
    try:
        project = Project(a.root)
        by_frame = {}
        for spec in a.holds:
            frame, word, seconds = parse_hold(spec)
            by_frame.setdefault(frame, []).append((word, seconds))
        edits = []
        for frame, holds in sorted(by_frame.items()):
            voice, rec, clip = project.voice(frame)
            cuts = plan_holds(voice['words'], holds, read_pcm(clip))
            edits.append((frame, voice, rec, clip, cuts))
        project.backup(a.backup, *(clip for _, _, _, clip, _ in edits))
        for frame, voice, rec, clip, cuts in edits:
            tmp = clip + '.tmp.mp3'
            render(hold_parts(clip, cuts), tmp)
            os.replace(tmp, clip)
            apply_holds(voice, rec, cuts)
            print(json.dumps({'frame': frame, 'holds': [[voice['words'][i]['text'], at, sec] for at, sec, i in cuts],
                              'duration_s': voice['duration_s']}, ensure_ascii=False))
        project.save()
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
