#!/usr/bin/env python3
"""Generate ambient sound and Foley cues with ElevenLabs (POST /v1/sound-generation).

    elevenlabs_sfx.py cues.json OUT_DIR

cues.json maps a cue name to {"seconds": 6, "prompt": "..."}. Existing files are
skipped, so the batch resumes. Prompts and parameters are merged into
OUT_DIR/sfx-prompts.json for provenance. Use these for generated shots: mute the
H3 clip's own audio (it can contain music or garbled speech) and lay a cue that
matches the shot. End each prompt with "No music, no voices, no speech."
Reads ELEVENLABS_API_KEY (or --key-env) from the environment.
"""
import argparse
import json
import os
import urllib.request


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('cues')
    ap.add_argument('out_dir')
    ap.add_argument('--prompt-influence', type=float, default=0.5)
    ap.add_argument('--key-env', default='ELEVENLABS_API_KEY')
    a = ap.parse_args()
    cues = json.load(open(a.cues))
    os.makedirs(a.out_dir, exist_ok=True)
    log_path = os.path.join(a.out_dir, 'sfx-prompts.json')
    log = json.load(open(log_path)) if os.path.exists(log_path) else {}
    for name, c in cues.items():
        path = os.path.join(a.out_dir, name + '.mp3')
        if os.path.exists(path):
            continue
        body = {'text': c['prompt'], 'duration_seconds': c['seconds'], 'prompt_influence': a.prompt_influence}
        req = urllib.request.Request('https://api.elevenlabs.io/v1/sound-generation', data=json.dumps(body).encode(),
                                     headers={'xi-api-key': os.environ[a.key_env], 'Content-Type': 'application/json', 'Accept': 'audio/mpeg'})
        with urllib.request.urlopen(req, timeout=180) as r:
            open(path, 'wb').write(r.read())
        log[name] = {**body, 'endpoint': 'POST /v1/sound-generation'}
        json.dump(log, open(log_path, 'w'), indent=1)
        print('wrote', path)


if __name__ == '__main__':
    main()
