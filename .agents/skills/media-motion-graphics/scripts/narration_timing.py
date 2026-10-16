#!/usr/bin/env python3
"""Narration timing for a narrated HyperFrames film.

The script text is the caption source of truth; a word-level transcript of one
single-take narration supplies the clock. The take is cut into one audio file
per sentence. Each cut sits at the midpoint of the silence after a
sentence-ending word, never inside a word, with 30 ms fades. Sentences that run
into the next one without silence stay in one segment. Segments are then placed
on the output timeline with a breath between sentences, a longer gap between
paragraphs (one paragraph per scene), and a lead before each scene's first word.

Writes timing.json (scene windows, output-time word clocks, caption groups,
voice segments) and one WAV per voice segment.

Example, from the composition root:

    python3 narration_timing.py --script ../../narration/script.md \
        --audio ../../narration/narration-1.mp3 \
        --asr ../../../transcripts/narration-1.json \
        --scenes hook,routes,cost,close --lead 0.6 --sentence-gap 0.28 \
        --gaps 0.7,0.7,0.9 --scene-lead 0.45,0.45,0.6 --tail 3.6 \
        --caption-chars 28 --out timing.json --vo-dir assets/audio

Paragraphs in --script are separated by blank lines; there must be exactly one
paragraph per scene. --gaps and --scene-lead take one value per scene boundary
(len(scenes) - 1 values). Use --caption-chars 46 for landscape and 28 for
portrait (one line on a phone). The ASR JSON is the word-level output of
`media-subtitle --backend elevenlabs` (segments[].words[] with start/end).
"""
import argparse
import difflib
import json
import os
import re
import subprocess
import sys
import unicodedata

FUNC = {'a', 'an', 'the', 'of', 'to', 'in', 'on', 'and', 'or', 'its', 'their', 'with', 'from', 'at', 'by', 'for',
        'one', 'every', 'each', 'is', 'are', 'that', 'than', 'y', 'el', 'la', 'los', 'las', 'de', 'del', 'en', 'un',
        'una', 'que', 'con', 'por', 'para', 'sus', 'su'}


def norm(t):
    t = unicodedata.normalize('NFKD', t.lower())
    t = ''.join(c for c in t if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]', '', t)


def floats(s, n, name):
    vals = [float(x) for x in s.split(',')] if s else []
    if len(vals) == 1 and n > 1:
        vals = vals * n
    if len(vals) != n:
        sys.exit(f'--{name} needs {n} values (one per scene boundary), got {len(vals)}')
    return vals


def align(words, asr_path):
    """Script words -> (start, end) lists on the clock of one word-level transcript."""
    d = json.load(open(asr_path))
    aw = [x for s in d['segments'] for x in s['words'] if x['word'].strip() and x.get('type', 'word') == 'word']
    sm = difflib.SequenceMatcher(None, [norm(w) for w in words], [norm(x['word']) for x in aw], autojunk=False)
    st = [None] * len(words)
    en = [None] * len(words)
    for a, b, n in sm.get_matching_blocks():
        for k in range(n):
            st[a + k] = aw[b + k]['start']
            en[a + k] = aw[b + k]['end']
    mism = [(op, words[a1:a2], [x['word'].strip() for x in aw[b1:b2]]) for op, a1, a2, b1, b2 in sm.get_opcodes() if op != 'equal']
    i = 0
    while i < len(words):  # interpolate unmatched words (numbers written as digits, split tokens) between neighbours
        if st[i] is None:
            j = i
            while j < len(words) and st[j] is None:
                j += 1
            t0 = en[i - 1] if i > 0 else 0.0
            t1 = st[j] if j < len(words) else aw[-1]['end']
            span = (t1 - t0) / (j - i)
            for k in range(i, j):
                st[k] = round(t0 + span * (k - i) + 0.02, 3)
                en[k] = round(t0 + span * (k - i + 1) - 0.02, 3)
            i = j
        else:
            i += 1
    matched = sum(n for _, _, n in sm.get_matching_blocks())
    return st, en, matched, d['audio_duration'], mism


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--script', required=True, help='caption-source script: one paragraph per scene')
    ap.add_argument('--audio', required=True, help='single-take narration audio')
    ap.add_argument('--asr', required=True, help='word-level transcript JSON of --audio')
    ap.add_argument('--scenes', required=True, help='comma-separated scene IDs, one per paragraph')
    ap.add_argument('--lead', type=float, default=1.0, help='silence before the first word (s)')
    ap.add_argument('--sentence-gap', type=float, default=0.3, help='breath added after each sentence inside a paragraph (s)')
    ap.add_argument('--gaps', default='1.0', help='extra silence after paragraph k, one value per boundary (s)')
    ap.add_argument('--scene-lead', default='0.5', help='scene start before its first word, one value per boundary (s)')
    ap.add_argument('--tail', type=float, default=3.0, help='hold after the last word (s)')
    ap.add_argument('--caption-chars', type=int, default=46, help='target caption chunk length (46 landscape, 28 portrait)')
    ap.add_argument('--out', default='timing.json')
    ap.add_argument('--vo-dir', default='assets/audio', help='where vo-NNN.wav segments are written (path as the composition will reference it)')
    a = ap.parse_args()

    scenes = a.scenes.split(',')
    paras = [p.strip() for p in open(a.script).read().split('\n\n') if p.strip()]
    if len(paras) != len(scenes):
        sys.exit(f'{a.script} has {len(paras)} paragraphs for {len(scenes)} scenes')
    gaps = floats(a.gaps, len(scenes) - 1, 'gaps')
    scene_lead = floats(a.scene_lead, len(scenes) - 1, 'scene-lead')
    sw = [(w, i) for i, p in enumerate(paras) for w in p.split()]
    st, en, matched, main_dur, mism = align([w for w, _ in sw], a.asr)

    # segments: sentences, never crossing a paragraph boundary
    segs, cur = [], []
    for k, (w, p) in enumerate(sw):
        cur.append(k)
        last_in_para = k + 1 == len(sw) or sw[k + 1][1] != p
        if last_in_para or re.search(r'[.?!]$', w):
            segs.append(cur)
            cur = []
    # a sentence that runs straight into the next one (no silence) stays in the same segment
    merged = [segs[0]]
    for ks in segs[1:]:
        same_para = sw[ks[0]][1] == sw[merged[-1][-1]][1]
        if same_para and st[ks[0]] - en[merged[-1][-1]] < 0.06:
            merged[-1] = merged[-1] + ks
        else:
            merged.append(ks)
    segs = merged

    def mid(x, y):
        return round((x + y) / 2, 3)

    cuts = []
    for i, ks in enumerate(segs):
        s0, s1 = ks[0], ks[-1]
        cin = 0.0 if i == 0 else mid(en[segs[i - 1][-1]], st[s0])
        cout = round(main_dur, 3) if i + 1 == len(segs) else mid(en[s1], st[segs[i + 1][0]])
        if i > 0 and st[s0] - en[segs[i - 1][-1]] < 0.06:
            sys.exit(f'no silence before segment {i} ("{sw[s0][0]}"): re-voice or split the paragraph')
        cuts.append((cin, cout))

    offset, t = [], a.lead
    for i, ks in enumerate(segs):
        offset.append(round(t, 3))
        t += cuts[i][1] - cuts[i][0]
        if i + 1 < len(segs):
            p, q = sw[ks[-1]][1], sw[segs[i + 1][0]][1]
            t += gaps[p] if q != p else a.sentence_gap
    total = round(t + a.tail, 2)
    seg_of = {k: i for i, ks in enumerate(segs) for k in ks}

    def shift(k):
        return offset[seg_of[k]] - cuts[seg_of[k]][0]

    os.makedirs(a.vo_dir, exist_ok=True)
    vo = []
    for i, (cin, cout) in enumerate(cuts):
        out = os.path.join(a.vo_dir, f'vo-{i:03d}.wav')
        dur = round(cout - cin, 3)
        subprocess.run(['ffmpeg', '-nostdin', '-loglevel', 'error', '-y', '-ss', str(cin), '-t', str(dur), '-i', a.audio,
                        '-af', f'afade=t=in:d=0.03,afade=t=out:st={dur - 0.03:.3f}:d=0.03', '-ar', '48000', '-ac', '2', out], check=True)
        vo.append({'id': f'vo{i:03d}', 'src': out, 'start': offset[i], 'duration': dur})

    words = [{'w': w, 'p': p, 's': round(st[k] + shift(k), 3), 'e': round(en[k] + shift(k), 3)} for k, (w, p) in enumerate(sw)]
    first = {}
    for k, (_, p) in enumerate(sw):
        first.setdefault(p, k)
    out_scenes = []
    for p, sid in enumerate(scenes):
        s = 0.0 if p == 0 else round(words[first[p]]['s'] - scene_lead[p - 1], 2)
        out_scenes.append({'id': sid, 'start': s})
    for p in range(len(out_scenes)):
        out_scenes[p]['end'] = out_scenes[p + 1]['start'] if p + 1 < len(out_scenes) else total
        out_scenes[p]['duration'] = round(out_scenes[p]['end'] - out_scenes[p]['start'], 2)
    for p in range(1, len(out_scenes)):  # a scene must not start before the previous paragraph's last word ends
        prev_last = max(k for k, (_, q) in enumerate(sw) if q == p - 1)
        if out_scenes[p]['start'] < words[prev_last]['e'] + 0.2:
            sys.exit(f'scene {scenes[p]} starts inside paragraph {p - 1}: raise --gaps or lower --scene-lead at boundary {p}')

    # caption groups: balanced chunks, preferring breaks after punctuation and never after a function word
    C = a.caption_chars
    hard = C + 6
    sents, cur = [], []
    for k, wd in enumerate(words):
        if cur and words[cur[-1]]['p'] != wd['p']:
            sents.append(cur)
            cur = []
        cur.append(k)
        if re.search(r'[.?]$', wd['w']):
            sents.append(cur)
            cur = []
    if cur:
        sents.append(cur)

    def L(ks):
        return len(' '.join(words[x]['w'] for x in ks))

    def cost_break(k):
        w = words[k]['w']
        if re.search(r'[,:;]$', w):
            return -12
        return 40 if re.sub(r'[^a-z]', '', w.lower()) in FUNC else 0

    caps = []
    for ks in sents:
        n = max(1, -(-L(ks) // C))
        best = None
        while best is None:
            def rec(i, parts, acc):
                nonlocal best
                if len(parts) == n - 1:
                    seg = ks[i:]
                    if not seg or L(seg) > hard:
                        return
                    cs = parts + [seg]
                    lens = [L(c) for c in cs]
                    sc = (max(lens) - min(lens)) + acc
                    if best is None or sc < best[0]:
                        best = (sc, cs)
                    return
                for j in range(i + 1, len(ks)):
                    seg = ks[i:j]
                    if L(seg) > hard:
                        break
                    rec(j, parts + [seg], acc + cost_break(ks[j - 1]))
            rec(0, [], 0)
            if best is None:
                n += 1
        for c in best[1]:
            caps.append({'start': words[c[0]]['s'], 'end': words[c[-1]]['e'], 'text': ' '.join(words[x]['w'] for x in c)})
    for x, y in zip(caps, caps[1:]):
        if 0 < y['start'] - x['end'] < 0.35:
            x['end'] = y['start']
        x['end'] = min(x['end'], y['start'])

    ratio = round(matched / len(sw), 3)
    json.dump({'total': total, 'scenes': out_scenes, 'vo': vo, 'words': words, 'captions': caps, 'match_ratio': ratio,
               'asr_mismatches': [{'op': op, 'script': s, 'asr': r} for op, s, r in mism]}, open(a.out, 'w'), indent=1)
    print('total', total, 'match', ratio, 'segments', len(segs), 'captions', len(caps))
    for s in out_scenes:
        print(f"  {s['id']:14s} {s['start']:7.2f} {s['duration']:6.2f}")
    if mism:
        print('script/ASR differences (digits and split tokens are harmless; real word changes need a listen):')
        for op, s, r in mism:
            print(f'  {op}: {" ".join(s)!r} -> {" ".join(r)!r}')


if __name__ == '__main__':
    main()
