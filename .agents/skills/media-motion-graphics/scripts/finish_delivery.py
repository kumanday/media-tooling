#!/usr/bin/env python3
"""Finish a rendered HyperFrames master for delivery.

media-loudnorm (two-pass, -14 LUFS) -> alimiter to hold true peak under -1 dBTP
(loudnorm alone overshot in practice) -> measure -> media-verify through a
single-range EDL wrapper (the composition owns its cuts).

    finish_delivery.py MASTER.mp4 PROJECT/renders/name.mp4 --project PROJECT --label name

Writes PROJECT/edit/verify-edl-LABEL.json and PROJECT/edit/verify-LABEL.json
and prints duration, integrated loudness, true peak, LRA and failed checks.
Read failed checks before accepting or rejecting them: `grade_consistency`
samples five frames across the whole film, so a multi-scene composition can
fail it by comparing two unrelated scenes. Inspect the worst pair it names.
"""
import argparse
import json
import os
import subprocess
import sys


def run(*a):
    return subprocess.run(list(a), capture_output=True, text=True, check=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('master')
    ap.add_argument('out')
    ap.add_argument('--project', required=True, help='project root (verification records go in PROJECT/edit/)')
    ap.add_argument('--label', required=True)
    ap.add_argument('--limit', default='0.78', help='alimiter limit (linear); 0.74-0.80 kept true peak near -1.5 dBTP')
    a = ap.parse_args()
    edit = os.path.join(os.path.abspath(a.project), 'edit')
    os.makedirs(edit, exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    tmp = a.out.replace('.mp4', '.loudnorm.tmp.mp4')
    run('media-loudnorm', a.master, '-o', tmp)
    run('ffmpeg', '-nostdin', '-loglevel', 'error', '-y', '-i', tmp, '-c:v', 'copy', '-af', f'alimiter=limit={a.limit}:level=disabled',
        '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', a.out)
    os.remove(tmp)
    m = subprocess.run(['ffmpeg', '-nostdin', '-i', a.out, '-af', 'loudnorm=print_format=json', '-f', 'null', '-'], capture_output=True, text=True).stderr
    j = json.loads(m[m.rindex('{'):m.rindex('}') + 1])
    dur = float(run('ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', a.out).stdout)
    edl_path = os.path.join(edit, f'verify-edl-{a.label}.json')
    json.dump({'version': 1, 'sources': {'v': os.path.relpath(os.path.abspath(a.out), edit)},
               'ranges': [{'source': 'v', 'start': 0.0, 'end': round(dur, 2), 'beat': 'full HyperFrames render',
                           'reason': 'Verification wrapper for a standalone composition; the composition owns all cuts.'}],
               'total_duration_s': round(dur, 2)}, open(edl_path, 'w'), indent=1)
    v = subprocess.run(['media-verify', a.out, '--edl', edl_path, '--output-dir', os.path.join(edit, 'verify', a.label), '--json'],
                       capture_output=True, text=True)
    open(os.path.join(edit, f'verify-{a.label}.json'), 'w').write(v.stdout)
    rep = json.loads(v.stdout) if v.stdout.strip().startswith('{') else {}
    fails = [(f.get('check'), f.get('details', '')[:160]) for f in rep.get('findings', []) if not f.get('passed')]
    print(json.dumps({'out': a.out, 'duration': round(dur, 2), 'lufs': j['input_i'], 'true_peak': j['input_tp'], 'lra': j['input_lra'],
                      'verify_passed': rep.get('passed'), 'failed_checks': fails}, indent=1))
    if float(j['input_tp']) > -1.0:
        print('true peak above -1 dBTP: lower --limit', file=sys.stderr)


if __name__ == '__main__':
    main()
