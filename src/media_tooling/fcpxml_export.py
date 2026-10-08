"""Export a layered media manifest as FCPXML for DaVinci Resolve."""

from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

VIDEO_EXTENSIONS = {".mov", ".mp4", ".m4v", ".webm", ".png", ".jpg", ".jpeg"}
AUDIO_EXTENSIONS = {".wav", ".aif", ".aiff", ".m4a", ".mp3"}


@dataclass(frozen=True)
class SequenceSpec:
    project: str
    event: str
    width: int
    height: int
    fps: int
    duration_frames: int


@dataclass(frozen=True)
class Layer:
    name: str
    path: Path
    kind: str
    lane: int
    offset_frames: int
    duration_frames: int
    role: str | None = None


def frames_to_time(frames: int, fps: int) -> str:
    if frames < 0:
        raise ValueError(f"frame count must be >= 0, got {frames}")
    return f"{frames}/{fps}s"


def parse_track_lane(track: str) -> int:
    match = re.fullmatch(r"([VA])(\d+)", track.strip().upper())
    if not match:
        raise ValueError(f"track must look like V1 or A1, got {track!r}")
    index = int(match.group(2))
    if index < 1:
        raise ValueError(f"track index must be >= 1, got {track!r}")
    return index - 1 if match.group(1) == "V" else -index


def infer_kind(path: Path, raw: dict[str, Any]) -> str:
    kind = raw.get("kind")
    if isinstance(kind, str):
        kind = kind.lower()
        if kind in {"video", "audio", "av"}:
            return kind
        raise ValueError(f"unsupported layer kind {kind!r}")
    suffix = path.suffix.lower()
    if suffix in AUDIO_EXTENSIONS:
        return "audio"
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    raise ValueError(f"cannot infer layer kind from extension: {path}")


def load_manifest(path: Path) -> tuple[SequenceSpec, list[Layer]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    base = path.parent
    timeline = payload.get("sequence", payload.get("timeline"))
    if not isinstance(timeline, dict):
        raise ValueError("manifest must contain 'sequence' or 'timeline'")

    duration_frames = int(timeline["duration_frames"])
    fps = int(timeline["fps"])
    seq = SequenceSpec(
        project=str(payload.get("project", "Layered Resolve Export")),
        event=str(payload.get("event", "Media Tooling Export")),
        width=int(timeline["width"]),
        height=int(timeline["height"]),
        fps=fps,
        duration_frames=duration_frames,
    )

    layers: list[Layer] = []
    raw_layers = payload.get("layers")
    if not isinstance(raw_layers, list) or not raw_layers:
        raise ValueError("manifest 'layers' must be a non-empty list")

    for i, raw in enumerate(raw_layers):
        if not isinstance(raw, dict):
            raise ValueError(f"layer[{i}] must be an object")
        raw_path = raw.get("path", raw.get("file"))
        if not isinstance(raw_path, str):
            raise ValueError(f"layer[{i}] must include 'path' or 'file'")
        media_path = (base / raw_path).resolve()
        kind = infer_kind(media_path, raw)
        lane_value = raw.get("lane")
        if lane_value is None:
            track = raw.get("track")
            if not isinstance(track, str):
                raise ValueError(f"layer[{i}] must include 'lane' or 'track'")
            lane = parse_track_lane(track)
        else:
            lane = int(lane_value)
        layers.append(
            Layer(
                name=str(raw.get("name", media_path.stem)),
                path=media_path,
                kind=kind,
                lane=lane,
                offset_frames=int(raw.get("offset_frames", 0)),
                duration_frames=int(raw.get("duration_frames", duration_frames)),
                role=str(raw["role"]) if "role" in raw else None,
            )
        )

    return seq, layers


def validate_layers(layers: list[Layer]) -> None:
    missing = [str(layer.path) for layer in layers if not layer.path.exists()]
    if missing:
        raise FileNotFoundError("missing media files:\n" + "\n".join(missing))
    if not any(layer.kind in {"video", "av"} for layer in layers):
        raise ValueError("at least one video layer is required")


def asset_flags(kind: str) -> dict[str, str]:
    flags: dict[str, str] = {}
    if kind in {"video", "av"}:
        flags.update({"hasVideo": "1", "videoSources": "1", "format": "fmt1"})
    if kind in {"audio", "av"}:
        flags.update({
            "hasAudio": "1",
            "audioSources": "1",
            "audioChannels": "2",
            "audioRate": "48000",
        })
    return flags


def add_clip(parent: ET.Element, layer: Layer, asset_id: str, fps: int, *, spine: bool) -> None:
    attrs = {
        "name": layer.name,
        "ref": asset_id,
        "offset": frames_to_time(layer.offset_frames, fps),
        "start": "0s",
        "duration": frames_to_time(layer.duration_frames, fps),
    }
    if not spine:
        attrs["lane"] = str(layer.lane)
    if layer.kind in {"audio", "av"} and layer.role:
        attrs["audioRole"] = layer.role
    ET.SubElement(parent, "asset-clip", attrs)


def build_fcpxml(seq: SequenceSpec, layers: list[Layer]) -> ET.ElementTree:
    validate_layers(layers)
    video_layers = [layer for layer in layers if layer.kind in {"video", "av"}]
    spine_layer = min(video_layers, key=lambda layer: (abs(layer.lane), layer.lane))
    connected = [layer for layer in layers if layer is not spine_layer]

    root = ET.Element("fcpxml", {"version": "1.10"})
    resources = ET.SubElement(root, "resources")
    ET.SubElement(
        resources,
        "format",
        {
            "id": "fmt1",
            "name": f"FFVideoFormat{seq.height}p{seq.fps}",
            "frameDuration": f"1/{seq.fps}s",
            "width": str(seq.width),
            "height": str(seq.height),
            "colorSpace": "1-1-1 (Rec. 709)",
        },
    )

    ids: dict[Layer, str] = {}
    for i, layer in enumerate(layers, start=1):
        asset_id = f"a{i}"
        ids[layer] = asset_id
        attrs = {
            "id": asset_id,
            "name": layer.name,
            "uid": asset_id,
            "start": "0s",
            "duration": frames_to_time(layer.duration_frames, seq.fps),
            **asset_flags(layer.kind),
        }
        asset = ET.SubElement(resources, "asset", attrs)
        ET.SubElement(asset, "media-rep", {"kind": "original-media", "src": layer.path.as_uri()})

    library = ET.SubElement(root, "library")
    event = ET.SubElement(library, "event", {"name": seq.event})
    project = ET.SubElement(event, "project", {"name": seq.project})
    sequence = ET.SubElement(
        project,
        "sequence",
        {
            "format": "fmt1",
            "duration": frames_to_time(seq.duration_frames, seq.fps),
            "tcStart": "0s",
            "tcFormat": "NDF",
            "audioLayout": "stereo",
            "audioRate": "48k",
        },
    )
    spine = ET.SubElement(sequence, "spine")
    spine_clip = ET.SubElement(
        spine,
        "asset-clip",
        {
            "name": spine_layer.name,
            "ref": ids[spine_layer],
            "offset": frames_to_time(spine_layer.offset_frames, seq.fps),
            "start": "0s",
            "duration": frames_to_time(spine_layer.duration_frames, seq.fps),
        },
    )
    for layer in sorted(connected, key=lambda item: item.lane):
        add_clip(spine_clip, layer, ids[layer], seq.fps, spine=False)
    return ET.ElementTree(root)


def write_fcpxml(manifest_path: Path, output_path: Path) -> None:
    seq, layers = load_manifest(manifest_path)
    tree = build_fcpxml(seq, layers)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(tree, space="  ")
    tree.write(output_path, encoding="utf-8", xml_declaration=True)
    ET.parse(output_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export a layered media manifest as Resolve-importable FCPXML."
    )
    parser.add_argument("manifest", help="Layer manifest JSON path.")
    parser.add_argument("-o", "--output", help="Output .fcpxml path.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = Path(args.manifest).expanduser().resolve()
    output = (
        Path(args.output).expanduser().resolve()
        if args.output
        else manifest.with_suffix(".fcpxml")
    )
    write_fcpxml(manifest, output)
    print(output)


if __name__ == "__main__":
    main()
