#!/usr/bin/env python3
"""Generate an instrumental music bed with ElevenLabs Music (POST /v1/music).

    elevenlabs_music.py OUT.mp3 --seconds 200 --prompt "Low ambient instrumental bed ..."

Generate the bed a little longer than the film (the composition trims it and
fades the tail). Writes OUT.mp3 and OUT.mp3.json (prompt and parameters, for
provenance). Reads ELEVENLABS_API_KEY (or --key-env) from the environment.
A prompt that worked under narration: "Low ambient instrumental
bed for a calm narrated film: warm analog pads, a slow evolving texture
with soft felt piano notes far in the background, a very gentle pulse, around
70 BPM, no drums, no vocals, no lead melody, steady energy that never builds to
a climax, leaves room for a narrator's voice."
"""
import argparse
import json
import os
import urllib.request


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('out')
    ap.add_argument('--seconds', type=float, required=True)
    ap.add_argument('--prompt', required=True)
    ap.add_argument('--model', default='music_v1')
    ap.add_argument('--key-env', default='ELEVENLABS_API_KEY')
    a = ap.parse_args()
    body = {'prompt': a.prompt, 'music_length_ms': int(a.seconds * 1000), 'model_id': a.model, 'force_instrumental': True}
    req = urllib.request.Request('https://api.elevenlabs.io/v1/music', data=json.dumps(body).encode(),
                                 headers={'xi-api-key': os.environ[a.key_env], 'Content-Type': 'application/json', 'Accept': 'audio/mpeg'})
    with urllib.request.urlopen(req, timeout=600) as r:
        open(a.out, 'wb').write(r.read())
    json.dump({**body, 'endpoint': 'POST /v1/music'}, open(a.out + '.json', 'w'), indent=1)
    print('wrote', a.out)


if __name__ == '__main__':
    main()
