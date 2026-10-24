#!/usr/bin/env python3
"""Edit an approved media-tts-frames take without re-voicing it.

Two operations on one frame's clip:

    splice_takes.py --backup qa/voice-backup cut 3 Well, today --old-script qa/SCRIPT.before.md
    splice_takes.py --backup qa/voice-backup append 5 qa/scratch-frame-05 [--gap 0.75]

- cut FRAME FROM_WORD UNTIL_WORD removes FROM_WORD up to the gap before
  UNTIL_WORD (UNTIL_WORD is kept), e.g. a false start or a dropped clause.
  Words match ignoring case and surrounding punctuation; use WORD#N for the
  Nth occurrence of FROM_WORD. --old-script is the SCRIPT.md the take was
  voiced from, before the edit.
- append FRAME SCRATCH_ROOT adds a newly voiced sentence after the frame's last
  word, about --gap seconds later. Voice it first with media-tts-frames in a
  scratch composition root whose SCRIPT.md holds only the new sentence for the
  same frame number, with the same voice and settings.

Edit SCRIPT.md first: it must already hold the frame's new text (the old text
minus the cut words, or the old text plus the scratch sentence). Joins land on
the quietest 10 ms inside inter-word gaps (never inside a word), with 30 ms
fades. The clip, audio_meta.json (words, cues, duration_s) and the
media-tts-frames cache (hash, words, char_starts, audio_s) are rebuilt for the
new text with media_tooling.tts_frames' own functions, so a later
media-tts-frames run is a cache hit and writes the same timings back. The
originals are copied into --backup first (an existing backup is kept).

Pass the options the take was voiced with as --tts-args (the cache hash covers
voice, model, language, voice settings and pronunciations), e.g.
--tts-args "--language fr --voice-id $VOICE --tail 0.9". The cut refuses to run
when the cached hash does not match --old-script with those options.

Run it from the composition root (or pass --root) with the Python that has
media-tooling installed; it imports media_tooling and numpy, and needs ffmpeg
and ffprobe on PATH. Then run retime_frames.py on built frames.
"""
import argparse
import difflib
import json
import os
import shlex
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # shared helpers, also when imported by path

from insert_holds import SR, Project, duration, find_word, quietest, read_pcm, render  # noqa: E402

from media_tooling import tts, tts_frames as tf  # noqa: E402


class Voicing:
    """media-tts-frames options for one SCRIPT.md: spoken text per frame and the cache key."""

    def __init__(self, tts_args):
        self.args = tf.parse_args(['SCRIPT.md', *shlex.split(tts_args)])
        self.voice_id = tts.resolve_voice_id(self.args.voice_id)
        self.settings = tf.voice_settings(self.args)
        self.pron = {}
        if self.args.pronunciations:
            with open(self.args.pronunciations, encoding='utf-8') as f:
                self.pron = json.load(f)

    def lines(self, script):
        with open(script, encoding='utf-8') as f:
            return tf.parse_script(f.read())

    def prepared(self, script, frame):
        line = next((ln for ln in self.lines(script) if ln.frame == frame), None)
        if line is None:
            raise ValueError(f'frame {frame} has no spoken line in {script}')
        return tf.prepare(line, self.pron)

    def key(self, spoken):
        return tf.cache_key(spoken, self.voice_id, self.args.model, self.args.language, self.settings)

    def tail(self, script, frame):
        last = self.lines(script)[-1].frame
        return self.args.last_tail if frame == last else self.args.tail


def check_hash(voicing, rec, spoken, what):
    if rec.get('hash') != voicing.key(spoken):
        raise ValueError(f'the cached hash does not match {what} with these options; pass the media-tts-frames '
                         'options the take was voiced with as --tts-args')


def remap_char_starts(old_spoken, old_cs, new_spoken, shift):
    """Carry each kept character's (shifted) start time from the old spoken text onto the new one."""
    if len(old_spoken) != len(old_cs):
        raise ValueError(f'cache has {len(old_cs)} char_starts for {len(old_spoken)} spoken characters')
    cs = [None] * len(new_spoken)
    ops = difflib.SequenceMatcher(a=old_spoken, b=new_spoken, autojunk=False).get_opcodes()
    for op, i1, i2, j1, j2 in ops:
        # a replaced span is aligned on its end: cutting "Well, t" -> "T" gives "T" the time of the kept "t"
        for k in range(min(j2 - j1, i2 - i1) if op in ('equal', 'replace') else 0):
            cs[j2 - 1 - k] = shift(old_cs[i2 - 1 - k])
    for k in range(len(cs)):  # inserted characters (e.g. a re-capitalised first word): borrow the next known time
        if cs[k] is None:
            cs[k] = next((t for t in cs[k + 1:] if t is not None), cs[k - 1] if k else 0.0)
    return cs


def plan_cut(words, x, from_spec, until_word):
    """-> (t_a, t_b, i0, i1): audio t_a..t_b and words[i0:i1] go."""
    i0 = find_word(words, from_spec)
    i1 = find_word(words, until_word, after=i0)
    prev_end = words[i0 - 1]['end'] if i0 else 0.0
    t_a = quietest(x, max(prev_end, words[i0]['start'] - 0.15), words[i0]['start'] - 0.005)
    t_b = quietest(x, max(words[i1 - 1]['end'], words[i1]['start'] - 0.25), words[i1]['start'] - 0.005)
    return t_a, t_b, i0, i1


def cut_shifter(t_a, t_b):
    d = round(t_b - t_a, 3)
    return lambda t: round(t - d, 3) if t >= t_b else (t if t <= t_a else t_a)


def cut(a, project, voicing, voice, rec, clip, new):
    old = voicing.prepared(a.old_script, a.frame)
    check_hash(voicing, rec, old.spoken, a.old_script)
    words = rec['words']
    t_a, t_b, i0, i1 = plan_cut(words, read_pcm(clip), a.from_word, a.until_word)
    shift = cut_shifter(t_a, t_b)
    cs = remap_char_starts(old.spoken, rec['char_starts'], new.spoken, shift)
    kept = [{**w, 'start': shift(w['start']), 'end': shift(w['end'])} for i, w in enumerate(words) if not i0 <= i < i1]
    report = {'op': 'cut', 'cut': [t_a, t_b], 'removed': [w['text'] for w in words[i0:i1]], 'seconds': round(t_b - t_a, 3)}
    return [(clip, 0, t_a), (clip, t_b, None)], cs, kept, report


def append(a, project, voicing, voice, rec, clip, new):
    scratch = Project(a.scratch)
    s_voice, s_rec, s_clip = scratch.voice(a.frame)
    s_new = voicing.prepared(os.path.join(scratch.root, 'SCRIPT.md'), a.frame)
    if not new.spoken.endswith(' ' + s_new.spoken):
        raise ValueError(f'SCRIPT.md frame {a.frame} must end with the scratch sentence {s_new.spoken!r}')
    check_hash(voicing, rec, new.spoken[:-len(s_new.spoken) - 1], 'SCRIPT.md without the scratch sentence')
    words = rec['words']
    x = read_pcm(clip)
    last_end = words[-1]['end']
    t_a = quietest(x, last_end + 0.03, min(len(x) / SR, last_end + 0.35))
    lead = s_rec['words'][0]['start']  # the new clip's own leading silence is kept
    silence = round(max(0.05, a.gap - (t_a - last_end) - lead), 3)
    off = round(t_a + silence, 3)
    cs = rec['char_starts'] + [round(off + s_rec['char_starts'][0], 3)] + [round(off + t, 3) for t in s_rec['char_starts']]
    kept = [dict(w) for w in words] + [{**w, 'start': round(w['start'] + off, 3), 'end': round(w['end'] + off, 3)}
                                       for w in s_rec['words']]
    report = {'op': 'append', 'join': t_a, 'silence': silence, 'new_clip_at': off, 'new_words': len(s_rec['words'])}
    return [(clip, 0, t_a), ('silence', silence), (s_clip, 0, None)], cs, kept, report


def relabel(new, cs, kept, frame):
    """Display text and ids from the new spoken text (keeps display overrides and capitalisation)."""
    if len(cs) != len(new.spoken):
        raise ValueError(f'{len(cs)} char_starts for {len(new.spoken)} spoken characters')
    toks = tf.words_from_alignment(new, {'character_start_times_seconds': cs, 'character_end_times_seconds': cs}, frame)
    if len(toks) != len(kept):
        raise ValueError(f'the new text has {len(toks)} words but the edited take has {len(kept)}')
    for k, (w, t) in enumerate(zip(kept, toks)):
        w['text'], w['id'] = t['text'], f'w{frame:02d}-{k:03d}'
    return kept


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--root', default='.', help='composition root (holds audio_meta.json)')
    ap.add_argument('--script', default=None, help='edited SCRIPT.md (default ROOT/SCRIPT.md)')
    ap.add_argument('--backup', required=True, help='folder for the pre-edit audio_meta.json, cache and clip')
    ap.add_argument('--tts-args', default='', help='the media-tts-frames options the take was voiced with, one string')
    sub = ap.add_subparsers(dest='op', required=True)
    c = sub.add_parser('cut', help='remove FROM_WORD up to the gap before UNTIL_WORD')
    c.add_argument('frame', type=int)
    c.add_argument('from_word')
    c.add_argument('until_word')
    c.add_argument('--old-script', required=True, help='SCRIPT.md the take was voiced from, before the edit')
    p = sub.add_parser('append', help="append the clip media-tts-frames voiced for FRAME in SCRATCH_ROOT")
    p.add_argument('frame', type=int)
    p.add_argument('scratch')
    p.add_argument('--gap', type=float, default=0.75, help='silence between the last word and the new one (s)')
    a = ap.parse_args(argv)
    try:
        project = Project(a.root)
        script = a.script or os.path.join(project.root, 'SCRIPT.md')
        voicing = Voicing(a.tts_args)
        voice, rec, clip = project.voice(a.frame)
        new = voicing.prepared(script, a.frame)
        parts, cs, kept, report = (cut if a.op == 'cut' else append)(a, project, voicing, voice, rec, clip, new)
        kept = relabel(new, cs, kept, a.frame)
        project.backup(a.backup, clip)
        tmp = clip + '.tmp.mp3'
        render(parts, tmp)
        os.replace(tmp, clip)
        audio_s = duration(clip)
        rec.update({'hash': voicing.key(new.spoken), 'words': kept, 'char_starts': cs, 'audio_s': audio_s})
        rec.setdefault('edits', []).append(report)
        voice['words'] = kept
        voice['cues'] = tf.cues_from_starts(new, cs)
        voice['duration_s'] = round(audio_s + voicing.tail(script, a.frame), 2)  # media-tts-frames' rule
        if not voice['cues']:
            del voice['cues']
        project.save()
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.CalledProcessError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 1
    print(json.dumps({'frame': a.frame, **report, 'audio_s': audio_s, 'duration_s': voice['duration_s'],
                      'cues': {c['name']: c['t'] for c in voice.get('cues', [])}}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
