from __future__ import annotations

import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote, urlparse

from media_tooling.fcpxml_export import (
    frames_to_time,
    load_manifest,
    parse_track_lane,
    write_fcpxml,
)


class TimeAndTrackTests(unittest.TestCase):
    def test_frames_to_time(self) -> None:
        self.assertEqual(frames_to_time(767, 30), "767/30s")

    def test_parse_track_lane(self) -> None:
        self.assertEqual(parse_track_lane("V1"), 0)
        self.assertEqual(parse_track_lane("V6"), 5)
        self.assertEqual(parse_track_lane("A1"), -1)
        self.assertEqual(parse_track_lane("A2"), -2)

    def test_parse_track_lane_rejects_bad_track(self) -> None:
        with self.assertRaises(ValueError):
            parse_track_lane("video 1")


class FCPXMLExportTests(unittest.TestCase):
    def test_exports_resolve_layered_fcpxml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assets = root / "assets"
            assets.mkdir()
            for name in ("background.mov", "logo.mov", "voice.wav", "music.wav"):
                (assets / name).write_bytes(b"placeholder")
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "project": "Demo Project",
                        "event": "Demo Event",
                        "sequence": {
                            "width": 1920,
                            "height": 1080,
                            "fps": 30,
                            "duration_frames": 90,
                        },
                        "layers": [
                            {
                                "name": "Background",
                                "path": "assets/background.mov",
                                "kind": "video",
                                "lane": 0,
                                "duration_frames": 90,
                            },
                            {
                                "name": "Logo",
                                "path": "assets/logo.mov",
                                "kind": "video",
                                "lane": 2,
                                "offset_frames": 30,
                                "duration_frames": 60,
                            },
                            {
                                "name": "Voice",
                                "path": "assets/voice.wav",
                                "kind": "audio",
                                "lane": -1,
                                "role": "dialogue",
                                "duration_frames": 90,
                            },
                            {
                                "name": "Music",
                                "path": "assets/music.wav",
                                "kind": "audio",
                                "lane": -2,
                                "role": "music",
                                "duration_frames": 90,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            out = root / "out.fcpxml"

            write_fcpxml(manifest, out)

            tree = ET.parse(out)
            root_el = tree.getroot()
            self.assertEqual(root_el.attrib["version"], "1.10")
            sequence = root_el.find(".//sequence")
            self.assertIsNotNone(sequence)
            assert sequence is not None
            self.assertEqual(sequence.attrib["duration"], "90/30s")

            refs = [
                Path(unquote(urlparse(rep.attrib["src"]).path))
                for rep in root_el.findall(".//media-rep")
            ]
            self.assertEqual(len(refs), 4)
            self.assertTrue(all(path.exists() for path in refs))

            clips = root_el.findall(".//asset-clip")
            by_name = {clip.attrib["name"]: clip for clip in clips}
            self.assertNotIn("lane", by_name["Background"].attrib)
            self.assertEqual(by_name["Logo"].attrib["lane"], "2")
            self.assertEqual(by_name["Logo"].attrib["offset"], "30/30s")
            self.assertEqual(by_name["Voice"].attrib["audioRole"], "dialogue")
            self.assertEqual(by_name["Music"].attrib["audioRole"], "music")

    def test_loads_credimas_style_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assets = root / "assets"
            assets.mkdir()
            (assets / "background.mov").write_bytes(b"placeholder")
            (assets / "voice.wav").write_bytes(b"placeholder")
            manifest = root / "layer-manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "timeline": {
                            "width": 1920,
                            "height": 1080,
                            "fps": 30,
                            "duration_frames": 767,
                        },
                        "layers": [
                            {"track": "V1", "file": "assets/background.mov"},
                            {
                                "track": "A1",
                                "file": "assets/voice.wav",
                                "role": "dialogue",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            seq, layers = load_manifest(manifest)

            self.assertEqual(seq.duration_frames, 767)
            self.assertEqual(layers[0].kind, "video")
            self.assertEqual(layers[0].lane, 0)
            self.assertEqual(layers[1].kind, "audio")
            self.assertEqual(layers[1].lane, -1)
            self.assertEqual(layers[1].duration_frames, 767)

    def test_missing_media_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "sequence": {
                            "width": 1920,
                            "height": 1080,
                            "fps": 30,
                            "duration_frames": 30,
                        },
                        "layers": [
                            {
                                "path": "missing.mov",
                                "kind": "video",
                                "lane": 0,
                                "duration_frames": 30,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(FileNotFoundError):
                write_fcpxml(manifest, root / "out.fcpxml")


if __name__ == "__main__":
    unittest.main()
