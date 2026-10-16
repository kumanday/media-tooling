"""Optional score and sound effects for a finished video (ElevenLabs video-to-music).

Use only when the user wants background music and/or sound effects. Two steps:

``generate VIDEO --out-dir DIR``
    Sends the picture-locked video to ``POST /v1/music/video-to-music``. The
    model scores the video's own cuts and motion, so generate from the final edit.
    With ``--separate-tracks`` (the default) the response is a ZIP holding
    ``music.mp3`` and ``sfx.mp3`` (with ``--sfx``), each matched to the video's
    length, so music and effects get separate levels. Writes ``request.json``
    for provenance.

``mix VIDEO --music DIR/music.mp3 [--sfx DIR/sfx.mp3] -o OUT.mp4``
    Lays the stems under the video's existing audio (the narration). Music is
    lowered and ducked under the voice with a sidechain compressor, SFX sit at
    their own level, and the result is loudness-normalized with a true-peak
    limit. Video is stream-copied.

Reads ELEVENLABS_API_KEY from the environment.
"""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

from media_tooling import tts

VIDEO_TO_MUSIC_URL = "https://api.elevenlabs.io/v1/music/video-to-music"
MAX_BYTES = 200 * 1024 * 1024


def generate(video: Path, out_dir: Path, *, description: str | None, tags: list[str], model: str, sfx: bool,
             separate_tracks: bool, use_audio_as_reference: bool) -> list[Path]:
    if video.stat().st_size > MAX_BYTES:
        raise ValueError("video-to-music accepts at most 200 MB of video; export a lighter proxy of the final edit")
    api_key = tts.resolve_api_key()
    requests = tts._requests_module
    assert requests is not None  # guarded by resolve_api_key
    form: list[tuple[str, str]] = [("model_id", model), ("add_sfx", str(sfx).lower()),
                                   ("separate_tracks", str(separate_tracks).lower()),
                                   ("use_audio_as_reference", str(use_audio_as_reference).lower())]
    if description:
        form.append(("description", description))
    form += [("tags", t) for t in tags]
    with video.open("rb") as fh:
        try:
            response = requests.post(VIDEO_TO_MUSIC_URL, headers={"xi-api-key": api_key}, data=form,
                                     files=[("videos", (video.name, fh, "video/mp4"))], timeout=1200)
        except requests.exceptions.RequestException:
            raise RuntimeError("Could not reach ElevenLabs. Check your connection and retry.") from None
    if not response.ok:
        raise RuntimeError(f"video-to-music failed: HTTP {response.status_code} {response.text[:300]}")
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    content = bytes(response.content)
    if content[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            for name in zf.namelist():
                if name.endswith("/"):
                    continue
                target = out_dir / Path(name).name
                target.write_bytes(zf.read(name))
                written.append(target)
    else:
        target = out_dir / "music.mp3"
        target.write_bytes(content)
        written.append(target)
    record: dict[str, Any] = {"endpoint": "POST /v1/music/video-to-music", "video": str(video), "model_id": model,
                              "description": description, "tags": tags, "add_sfx": sfx, "separate_tracks": separate_tracks,
                              "use_audio_as_reference": use_audio_as_reference, "outputs": [p.name for p in written]}
    (out_dir / "request.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
    return written


def mix_filter(*, has_sfx: bool, music_db: float, sfx_db: float, duck: bool, lufs: float, true_peak: float) -> str:
    music = f"[1:a]volume={music_db}dB[m0]"
    if duck:  # the narration keys the compressor; the music dips while the voice speaks
        parts = ["[0:a]asplit=2[voice][key]", music,
                 "[m0][key]sidechaincompress=threshold=0.03:ratio=6:attack=25:release=350[music]"]
    else:
        parts = ["[0:a]anull[voice]", music.replace("[m0]", "[music]")]
    inputs = "[voice][music]"
    if has_sfx:
        parts.append(f"[2:a]volume={sfx_db}dB[fx]")
        inputs += "[fx]"
    n = 3 if has_sfx else 2
    parts.append(f"{inputs}amix=inputs={n}:duration=first:normalize=0,loudnorm=I={lufs}:TP={true_peak - 0.5}:LRA=11,"
                 f"alimiter=limit={10 ** (true_peak / 20):.3f}:level=disabled[out]")
    return ";".join(parts)


def mix(video: Path, music: Path, sfx: Path | None, out: Path, *, music_db: float, sfx_db: float, duck: bool,
        lufs: float, true_peak: float) -> None:
    cmd = ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(video), "-i", str(music)]
    if sfx:
        cmd += ["-i", str(sfx)]
    cmd += ["-filter_complex", mix_filter(has_sfx=sfx is not None, music_db=music_db, sfx_db=sfx_db, duck=duck,
                                          lufs=lufs, true_peak=true_peak),
            "-map", "0:v", "-map", "[out]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-movflags", "+faststart", str(out)]
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(cmd, check=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Optional score and SFX for a finished video (ElevenLabs video-to-music).")
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate", help="score a picture-locked video; writes music.mp3 (and sfx.mp3)")
    g.add_argument("video")
    g.add_argument("--out-dir", required=True)
    g.add_argument("--description", default=None, help="what the music should be (max 4100 characters)")
    g.add_argument("--tag", action="append", default=[], help="style tag, repeatable (max 10)")
    g.add_argument("--model", default="music_v2_5", help="music_v1, music_v2 or music_v2_5 (default)")
    g.add_argument("--sfx", action="store_true", help="also generate sound effects from the video")
    g.add_argument("--mixed", action="store_true", help="one mixed file instead of separate music and SFX tracks")
    g.add_argument("--use-audio-as-reference", action="store_true",
                   help="let the video's own audio guide genre, BPM and mood (off for narrated videos)")
    m = sub.add_parser("mix", help="lay music (and SFX) under the video's narration")
    m.add_argument("video")
    m.add_argument("--music", required=True)
    m.add_argument("--sfx", default=None)
    m.add_argument("-o", "--output", required=True)
    m.add_argument("--music-db", type=float, default=-10.0, help="music gain before ducking (dB); -10 left the music about 21 dB under speech")
    m.add_argument("--sfx-db", type=float, default=-4.0, help="SFX gain (dB)")
    m.add_argument("--no-duck", action="store_true", help="do not duck the music under the voice")
    m.add_argument("--lufs", type=float, default=-14.0, help="integrated loudness target")
    m.add_argument("--true-peak", type=float, default=-1.0, help="true-peak ceiling (dBTP)")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    a = parse_args(argv)
    try:
        if a.cmd == "generate":
            if len(a.tag) > 10:
                raise ValueError("at most 10 tags")
            files = generate(Path(a.video), Path(a.out_dir), description=a.description, tags=a.tag, model=a.model, sfx=a.sfx,
                             separate_tracks=not a.mixed, use_audio_as_reference=a.use_audio_as_reference)
            print("wrote " + ", ".join(str(f) for f in files))
        else:
            out = Path(a.output)
            if out.resolve() == Path(a.video).resolve():
                raise ValueError("output must differ from the input video")
            mix(Path(a.video), Path(a.music), Path(a.sfx) if a.sfx else None, out, music_db=a.music_db, sfx_db=a.sfx_db,
                duck=not a.no_duck, lufs=a.lufs, true_peak=a.true_peak)
            print(f"wrote {out}")
    except (OSError, RuntimeError, ValueError, zipfile.BadZipFile, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
