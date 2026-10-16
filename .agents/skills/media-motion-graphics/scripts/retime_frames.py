#!/usr/bin/env python3
r"""Retime built HyperFrames frames after narration is re-voiced.

Frames authored against one narration take hard-code cue times (GSAP position
arguments, `[selector, time]` pairs, a frame `DUR`). When the narration is
re-voiced, every word moves. This maps each frame's times through a
piecewise-linear warp from the old take's word timings to the new take's, so
reveals stay on their words without rebuilding the frames.

    retime_frames.py --old-audio-meta old/audio_meta.json --new-audio-meta audio_meta.json \
        --frames-dir compositions/frames [--dry-run] [--audit] [--time-keys cue,q] \
        [--helper wipe:1 --helper span:1,3] [--no-helper-default] [--duration-var D]

Both files use the HyperFrames frame-keyed `audio_meta.json` shape (voices[] with
frame, duration_s and frame-relative words). Frame N is the file
`<frames-dir>/NN-*.html`. Words are matched by text; a frame whose words differ
is skipped and reported. Only inline <script> code is rewritten, never string
literals or comments. Rewritten times by default:

- `var|let|const DUR = <t>` (the frame duration: old duration_s -> new duration_s).
  Other `DUR\w*` names (`DURATION`, ...) are mapped the same way when their value
  is the old duration_s (within 0.05 s); otherwise they are reported and left alone;
- the numeric position argument after an object, `{...}, <t>)`, also when the
  base time leads an expression, `{...}, <t> + (k - 1) * 0.15)`;
- `["#id", <t>]` pairs;
- the last numeric argument of a helper call, `name(..., <t>)`. Each frame lists
  the helper names this rule was applied to, so wrong guesses are easy to spot;
- `DUR - <t>` expressions.

Opt-in rules for other idioms:

- `--time-keys cue,q,L,R`: numeric values of these object-literal keys are times,
  as in `{ n: 1, cue: 3.01, q: 4.82 }` (also a base time before `+`/`-`);
- `--helper NAME:IDX[,IDX...]` (repeatable): these 0-based positional arguments of
  `NAME(...)` are times, e.g. `--helper wipe:1` for `wipe("#r1", 13.2, 0.7)`.
  Arguments may contain nested calls. Only the listed arguments of NAME are
  warped; the default last-argument rule is not applied to NAME;
- `--no-helper-default`: disable the last-argument rule for every helper;
- `--duration-var NAME` (repeatable): extra frame-duration variable names, such
  as `D`, mapped like the `DUR\w*` names (value must be the old duration_s);
- `--audit`: after rewriting, list numeric literals that look like absolute
  times (> 1.0 s, within the frame) but were not mapped: GSAP position
  arguments, arrays, object fields, assignments and long or computed tween
  durations. A report only, with the warped value for hand edits.

Tween durations (`duration: 0.5`), staggers and offsets such as `at + 0.05` are
left alone. Every change is printed with its line and rule; inspect the list,
and snapshot the frames before rendering.
"""
import argparse
import bisect
import glob
import json
import os
import re
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

NUM = r'(\d+(?:\.\d+)?)'
DUR_TOL = 0.05
RULES = [  # legacy default rules: (label, regex); the time is group 1
    ('position', re.compile(r'\}\s*,\s*' + NUM + r'\s*\)')),
    ('pair', re.compile(r'\[\s*\x00\d+\x00\s*,\s*' + NUM + r'\s*\]')),  # ["#id", t] (strings are masked first)
]
DEFAULT_HELPER = re.compile(r'\b([A-Za-z_]\w*)\([^()\n]*?,\s*' + NUM + r'\s*\)')
DUR_MINUS = re.compile(r'\bDUR\s*-\s*' + NUM)
POSITION_EXPR = re.compile(r'\}\s*,\s*' + NUM + r'(?=\s*[+-])')
STRING = r'"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'|`(?:[^`\\]|\\.)*`'
MASK = re.compile(STRING + r'|//[^\n]*|/\*[\s\S]*?\*/')  # strings -> \x00i\x00, comments -> \x01i\x01
PLACEHOLDER = re.compile(r'([\x00\x01])(\d+)\1')
GAP = r'(?:\s|\x01\d+\x01)*'  # whitespace or masked comments
LEAD = re.compile(GAP + NUM + GAP + r'(?:\Z|[+-])')  # an argument that is <t> or <t> +/- expr
HELPER_SPEC = re.compile(r'([A-Za-z_$][\w$]*):(\d+(?:,\d+)*)')
CALLEE = re.compile(r'(\.?)\s*([A-Za-z_$][\w$]*)\s*\Z')
AUDIT_NUM = re.compile(r'(?<![\w$.\x00\x01])(\d+(?:\.\d+)?)(?![\w.])')
UNARY_MINUS = re.compile(r'(?:^|[:,(\[{=?;&|!]|\breturn)\s*-\s*\Z')
FOLLOW_OP = re.compile(r'\s*[-+*/%]')
GSAP_METHODS = {'to', 'from', 'fromTo', 'set', 'add', 'call', 'addLabel', 'addPause', 'tweenTo', 'tweenFromTo'}
KEYWORDS = {'if', 'for', 'while', 'switch', 'catch', 'function', 'return', 'typeof', 'with', 'in', 'of'}
VISUAL_KEYS = {  # object fields the audit never reports (geometry and style, not times)
    'scale', 'scaleX', 'scaleY', 'scaleZ', 'opacity', 'autoAlpha', 'rotation', 'rotationX', 'rotationY',
    'rotationZ', 'skewX', 'skewY', 'x', 'y', 'z', 'xPercent', 'yPercent', 'width', 'height', 'top', 'left',
    'right', 'bottom', 'r', 'rx', 'ry', 'cx', 'cy', 'x1', 'x2', 'y1', 'y2', 'strokeWidth', 'stroke-width',
    'strokeDashoffset', 'strokeDasharray', 'borderWidth', 'borderRadius', 'fontSize', 'letterSpacing', 'blur'}
DURATION_KEYS = {'duration', 'stagger', 'each', 'delay', 'repeatDelay', 'amount'}


@dataclass
class Options:
    time_keys: frozenset = frozenset()
    helpers: dict = field(default_factory=dict)  # name -> frozenset of 0-based time argument indices
    helper_default: bool = True
    duration_vars: frozenset = frozenset()
    audit: bool = False


@dataclass
class Result:
    text: str
    changes: list = field(default_factory=list)  # (old, new, line, rule)
    default_helpers: Counter = field(default_factory=Counter)
    notes: list = field(default_factory=list)
    leftovers: list = field(default_factory=list)  # (line, value, warped, context, source line)


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


def parse_helper(spec):
    m = HELPER_SPEC.fullmatch(spec.strip())
    if not m:
        raise argparse.ArgumentTypeError(f'expected NAME:IDX[,IDX...], got {spec!r}')
    return m.group(1), frozenset(int(i) for i in m.group(2).split(','))


def split_names(values):
    return frozenset(n.strip() for v in values or [] for n in v.split(',') if n.strip())


def mask(code):
    """Replace string literals and comments by placeholders; return body, tokens and a position map."""
    toks, out, starts, shifts, last, shift = [], [], [], [], 0, 0
    for m in MASK.finditer(code):
        tag = '\x01' if m.group(0)[0] == '/' else '\x00'
        ph = f'{tag}{len(toks)}{tag}'
        toks.append(m.group(0))
        out += [code[last:m.start()], ph]
        shift += len(m.group(0)) - len(ph)
        starts.append(m.end() - shift)  # masked index just after the placeholder
        shifts.append(shift)
        last = m.end()
    out.append(code[last:])
    return ''.join(out), toks, (starts, shifts)


def unmask(text, toks):
    return PLACEHOLDER.sub(lambda m: toks[int(m.group(2))], text)


def call_args(body, open_idx):
    """Spans of the top-level arguments of the call whose '(' is at open_idx (None if unbalanced)."""
    depth, start, spans = 0, open_idx + 1, []
    for i in range(open_idx + 1, len(body)):
        c = body[i]
        if c in '([{':
            depth += 1
        elif c in ')]}':
            if depth == 0:
                if c != ')':
                    return None
                spans.append((start, i))
                return spans
            depth -= 1
        elif c == ',' and depth == 0:
            spans.append((start, i))
            start = i + 1
    return None


def ends_call(body, i):
    """True when the expression from i runs to the closing ')' of its call (it is the last argument)."""
    depth = 0
    for c in body[i:]:
        if c in '([{':
            depth += 1
        elif c in ')]}':
            if depth == 0:
                return c == ')'
            depth -= 1
        elif depth == 0 and c in ',;':
            return False
    return False


def statement_context(body, toks, lo, pos, end):
    """Classify a literal by the text between the previous top-level ',' or ';' and the literal."""
    depth, i = 0, pos - 1
    while i >= lo:
        c = body[i]
        if c in ')]}':
            depth += 1
        elif c in '([{':
            depth -= 1
        elif depth == 0 and c in ',;':
            break
        i -= 1
    seg = re.sub(r'\x01\d+\x01', ' ', body[i + 1:pos])
    m = re.match(r'\s*(?:(?:var|let|const)\s+)?([A-Za-z_$][\w$.]*)\s*[-+*/]?=(?!=)', seg)
    if m:
        return 'assign ' + m.group(1), False
    m = re.match(r'\s*([A-Za-z_$][\w$]*|\x00\d+\x00)\s*:', seg)
    if m:
        key = m.group(1)
        if key.startswith('\x00'):
            key = toks[int(key[1:-1])][1:-1]
        return 'field ' + key, bool(seg[m.end():].strip()) or bool(FOLLOW_OP.match(body, end))
    return 'expr', False


def literal_context(body, toks, s, e, stack):
    pos = s
    for o in reversed(stack):
        c = body[o]
        if c == '[':
            return 'array', False
        if c == '(':
            m = CALLEE.search(body[max(0, o - 80):o])
            if m and m.group(2) not in KEYWORDS:
                args = call_args(body, o) or []
                idx = next((k for k, (a, b) in enumerate(args) if a <= s <= b), 0)
                if m.group(1) and m.group(2) in GSAP_METHODS and idx > 0 and idx == len(args) - 1:
                    return 'position', False
                return f'{m.group(2)}() arg {idx}', False
            pos = o  # a grouping paren: classify the enclosing expression
            continue
        return statement_context(body, toks, o + 1, pos, e)  # object literal or block
    return statement_context(body, toks, 0, pos, e)


def audit_literals(body, toks, claimed, dur_old):
    """Numeric literals that look like absolute times but were not mapped: [(start, value, context)]."""
    lits = [(m.start(1), m.end(1), m.group(1)) for m in AUDIT_NUM.finditer(body) if m.start(1) not in claimed]
    stacks, stack, k = [], [], 0
    for i, c in enumerate(body):
        while k < len(lits) and lits[k][0] == i:
            stacks.append(list(stack))
            k += 1
        if c in '([{':
            stack.append(i)
        elif c in ')]}' and stack:
            stack.pop()
    found = []
    for (s, e, txt), st in zip(lits, stacks):
        v = float(txt)
        if not 1.0 < v <= dur_old + 1.0 or UNARY_MINUS.search(body[max(0, s - 40):s]):
            continue
        ctx, is_expr = literal_context(body, toks, s, e, st)
        key = ctx[6:] if ctx.startswith('field ') else None
        if key in VISUAL_KEYS:
            continue
        if key in DURATION_KEYS:
            if not (v >= 2.0 or is_expr):
                continue
            ctx = f'field {key} ({"computed" if is_expr else "long"})'
        if '.' not in txt and ctx != 'position':
            continue
        found.append((s, v, ctx))
    return found


def retime_code(code, pts, dur_old, dur_new, opts=None):
    """Retime one <script> block. Returns a Result with the new text, changes, notes and audit."""
    opts = opts or Options()
    body, toks, (starts, shifts) = mask(code)
    nl = [i for i, c in enumerate(code) if c == '\n']

    def line(p):  # 1-based line in `code` of masked position p
        i = bisect.bisect_right(starts, p) - 1
        return bisect.bisect_left(nl, p + (shifts[i] if i >= 0 else 0)) + 1

    res = Result(code)
    cands = []  # (start, end, kind, rule) in precedence order
    dur_names = [r'DUR\w*'] + [re.escape(n) for n in sorted(opts.duration_vars)]
    for m in re.finditer(r'\b(?:var|let|const)\s+(' + '|'.join(dur_names) + r')(?![\w$])\s*=\s*' + NUM, body):
        name, v = m.group(1), float(m.group(2))
        if name == 'DUR' or abs(v - dur_old) <= DUR_TOL:
            cands.append((m.start(2), m.end(2), 'dur', name))
        else:
            res.notes.append(f'L{line(m.start(2))} {name} = {m.group(2)} left unchanged (old duration is {dur_old})')
    for rule_name, rule in RULES:
        cands += [(m.start(1), m.end(1), 'time', rule_name) for m in rule.finditer(body)]
    skip = set()  # numeric non-time arguments of declared helpers (not audited)
    if opts.helpers:
        names = '|'.join(re.escape(n) for n in sorted(opts.helpers))
        for m in re.finditer(r'(?<![\w$])(' + names + r')\s*\(', body):
            for idx, (a, b) in enumerate(call_args(body, m.end() - 1) or []):
                lm = LEAD.match(body, a, b)
                if lm and idx in opts.helpers[m.group(1)]:
                    cands.append((lm.start(1), lm.end(1), 'time', f'{m.group(1)}() arg {idx}'))
                elif lm:
                    skip.add(lm.start(1))
    if opts.time_keys:
        keys = '|'.join(re.escape(k) for k in sorted(opts.time_keys))
        tk = re.compile(r'[{,]' + GAP + r'(?:(' + keys + r')(?![\w$])|\x00(\d+)\x00)\s*:\s*' + NUM
                        + r'(?=' + GAP + r'[,}+-])')
        for m in tk.finditer(body):
            key = m.group(1) or toks[int(m.group(2))][1:-1]
            if key in opts.time_keys:
                cands.append((m.start(3), m.end(3), 'time', 'key ' + key))
    cands += [(m.start(1), m.end(1), 'time', 'position base') for m in POSITION_EXPR.finditer(body)
              if ends_call(body, m.end(1))]
    cands += [(m.start(1), m.end(1), 'time', 'DUR -') for m in DUR_MINUS.finditer(body)]
    if opts.helper_default:
        cands += [(m.start(2), m.end(2), 'default', m.group(1)) for m in DEFAULT_HELPER.finditer(body)
                  if m.group(1) not in opts.helpers]
    hits = {}
    for c in cands:
        hits.setdefault(c[0], c)
    out, last = [], 0
    for s in sorted(hits):
        _, e, kind, rule_name = hits[s]
        old = float(body[s:e])
        new = dur_new if kind == 'dur' else warp(pts, old)
        out.append(body[last:s] + f'{new:.2f}')
        last = e
        if kind == 'default':
            res.default_helpers[rule_name] += 1
            rule_name = f'{rule_name}() last arg (default)'
        if abs(new - old) >= 0.005:
            res.changes.append((old, round(new, 2), line(s), rule_name))
    out.append(body[last:])
    res.text = unmask(''.join(out), toks)
    if opts.audit:
        src_lines = code.split('\n')
        for s, v, ctx in audit_literals(body, toks, set(hits) | skip, dur_old):
            ln = line(s)
            src = src_lines[ln - 1].strip()
            res.leftovers.append((ln, v, round(warp(pts, v), 2), ctx, src[:72] + ('...' if len(src) > 72 else '')))
    return res


def retime_script(code, pts, dur_old, dur_new, opts=None):
    """Backward-compatible wrapper: (new code, [(old, new), ...])."""
    r = retime_code(code, pts, dur_old, dur_new, opts)
    return r.text, [(o, n) for o, n, _, _ in r.changes]


def read_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--old-audio-meta', required=True)
    ap.add_argument('--new-audio-meta', required=True)
    ap.add_argument('--frames-dir', required=True)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--time-keys', action='append', metavar='KEY[,KEY...]',
                    help='object-literal keys whose numeric values are times (opt-in)')
    ap.add_argument('--helper', action='append', type=parse_helper, default=[], metavar='NAME:IDX[,IDX...]',
                    help='0-based argument indices of NAME(...) that are times; repeatable')
    ap.add_argument('--no-helper-default', action='store_true',
                    help='do not warp the last numeric argument of other helper calls')
    ap.add_argument('--duration-var', action='append', metavar='NAME',
                    help='extra frame-duration variable names besides DUR*')
    ap.add_argument('--audit', action='store_true', help='list time-like literals that were not mapped')
    a = ap.parse_args(argv)
    helpers = {}
    for name, idx in a.helper:
        helpers[name] = helpers.get(name, frozenset()) | idx
    opts = Options(split_names(a.time_keys), helpers, not a.no_helper_default, split_names(a.duration_var), a.audit)
    old = {v['frame']: v for v in read_json(a.old_audio_meta)['voices']}
    new = {v['frame']: v for v in read_json(a.new_audio_meta)['voices']}
    status, defaults = 0, Counter()
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
        with open(files[0], encoding='utf-8') as f:
            html = f.read()
        parts = re.split(r'(<script(?![^>]*\bsrc=)[^>]*>[\s\S]*?</script>)', html)
        total, used, notes, left, offset = [], Counter(), [], [], 0
        for i, part in enumerate(parts):
            if part.startswith('<script'):
                r = retime_code(part, pts, old[frame]['duration_s'], new[frame]['duration_s'], opts)
                parts[i] = r.text
                total += [(o, n, ln + offset, rule) for o, n, ln, rule in r.changes]
                notes += r.notes
                left += [(ln + offset, *rest) for ln, *rest in r.leftovers]
                used += r.default_helpers
            offset += part.count('\n')
        defaults += used
        print(f'frame {frame:02d}: {os.path.basename(files[0])} · duration {old[frame]["duration_s"]} -> {new[frame]["duration_s"]} · {len(total)} times moved')
        for o, n, ln, rule in total:
            print(f'    {o:6.2f} -> {n:6.2f}  L{ln} {rule}')
        for note in notes:
            print(f'    note: {note}')
        if used:
            print('    default last-argument rule applied to: '
                  + ', '.join(f'{k} x{c}' for k, c in sorted(used.items()))
                  + ' (pass --helper NAME:IDX where the time is another argument)')
        if a.audit:
            print(f'    audit: {len(left)} time-like literals not mapped' + (':' if left else ''))
            for ln, v, w, ctx, src in left:
                print(f'      L{ln:<5} {v:6.2f} (warped {w:6.2f})  {ctx:<28} {src}')
        if not a.dry_run:
            with open(files[0], 'w', encoding='utf-8') as f:
                f.write(''.join(parts))
    if defaults:
        print('default last-argument rule used for: ' + ', '.join(f'{k} x{c}' for k, c in sorted(defaults.items())))
    sys.exit(status)


if __name__ == '__main__':
    main()
