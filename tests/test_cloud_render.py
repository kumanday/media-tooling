from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from media_tooling import cloud_render as cr

CONFIG = """
default_profile = "personal"

[profiles.work]
gcloud_configuration = "work-cfg"
account = "me@work.example"
project = "work-proj"

[profiles.personal]
gcloud_configuration = "personal-cfg"
account = "me@example.com"
project = "personal-proj"
region = "europe-west1"

[[rules]]
path = "~/dev/work/**"
profile = "work"
"""

INDEX = """<!doctype html><html><body>
<div id="root" data-composition-id="main" data-width="1920" data-height="1080" data-duration="12.5">
  <video src="assets/media/a.mp4"></video>
  <div data-composition-src="compositions/frames/01.html"></div>
</div></body></html>"""

FRAME = """<template><style>@font-face { src: url("assets/fonts/x.woff2"); }</style>
<video src="capture/shots/c1.mp4"></video><img src="https://example.com/remote.png"></template>"""


def make_project(root: Path) -> Path:
    proj = root / "proj"
    for rel, text in {
        "index.html": INDEX,
        "compositions/frames/01.html": FRAME,
        "assets/media/a.mp4": "a",
        "assets/fonts/x.woff2": "f",
        "capture/shots/c1.mp4": "c",
        "capture/shots/frames/f00001.jpg": "j",
        "renders/master.mp4": "m",
        "qa/notes.txt": "q",
        "capture/shots/c1.take-old.mp4": "old",
        "assets/score/music.mp3": "s",
        "package.json": '{"scripts": {"render": "npx --yes hyperframes@0.8.163 render"}}',
    }.items():
        p = proj / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return proj


class ProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        (self.home / "dev" / "work" / "blog" / "slot").mkdir(parents=True)
        (self.home / "dev" / "other" / "slot").mkdir(parents=True)
        self.cfg_dir = self.root / "cfg"
        self.cfg_dir.mkdir()
        (self.cfg_dir / "profiles.toml").write_text(CONFIG)
        self.env = mock.patch.dict(os.environ, {"HOME": str(self.home), "MEDIA_TOOLING_CONFIG_DIR": str(self.cfg_dir),
                                                "MEDIA_TOOLING_CACHE_DIR": str(self.root / "cache")})
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()

    def test_rule_default_and_cli_precedence(self) -> None:
        cfg = cr.load_config()
        work = self.home / "dev" / "work" / "blog" / "slot"
        other = self.home / "dev" / "other" / "slot"
        self.assertEqual(cr.resolve_profile(work, cfg).name, "work")
        self.assertEqual(cr.resolve_profile(other, cfg).name, "personal")
        self.assertEqual(cr.resolve_profile(other, cfg).reason, "default_profile")
        self.assertEqual(cr.resolve_profile(work, cfg, "personal").name, "personal")

    def test_project_pin_beats_rules(self) -> None:
        cfg = cr.load_config()
        blog = self.home / "dev" / "work" / "blog"
        (blog / "media-tooling.toml").write_text('render_profile = "personal"\n')
        r = cr.resolve_profile(blog / "slot", cfg)
        self.assertEqual(r.name, "personal")
        self.assertIn("media-tooling.toml", r.reason)

    def test_unknown_and_missing(self) -> None:
        cfg = cr.load_config()
        with self.assertRaises(cr.LocalConfigError):
            cr.resolve_profile(None, cfg, "nope")
        del cfg["default_profile"]
        with self.assertRaises(cr.LocalConfigError):
            cr.resolve_profile(self.home / "dev" / "other" / "slot", cfg)

    def test_config_validation(self) -> None:
        bad = self.cfg_dir / "bad.toml"
        bad.write_text(CONFIG + '\n[[rules]]\npath = "/x/**"\nprofile = "ghost"\n')
        with self.assertRaises(cr.LocalConfigError):
            cr.load_config(bad)

    def test_cloud_commands_need_gcp_fields(self) -> None:
        (self.cfg_dir / "profiles.toml").write_text(CONFIG + '\n[profiles.rules_only]\n')
        with self.assertRaises(cr.CloudRenderError):
            cr.resolve_cloud(None, "rules_only")
        self.assertEqual(cr.resolve_cloud(None, "work").profile["project"], "work-proj")

    def test_profile_env_isolates_credentials(self) -> None:
        cfg = cr.load_config()
        prof = cfg["profiles"]["personal"]
        base = {"GOOGLE_OAUTH_ACCESS_TOKEN": "x", "GOOGLE_APPLICATION_CREDENTIALS": "/global.json", "PATH": "/bin"}
        env = cr.profile_env("personal", prof, base)
        self.assertEqual(env["CLOUDSDK_ACTIVE_CONFIG_NAME"], "personal-cfg")
        self.assertEqual(env["CLOUDSDK_CORE_PROJECT"], "personal-proj")
        self.assertNotIn("GOOGLE_OAUTH_ACCESS_TOKEN", env)
        self.assertNotIn("GOOGLE_APPLICATION_CREDENTIALS", env)  # no per-profile file: never fall back to global
        adc = self.cfg_dir / "adc" / "personal.json"
        adc.parent.mkdir()
        adc.write_text("{}")
        self.assertEqual(cr.profile_env("personal", prof, base)["GOOGLE_APPLICATION_CREDENTIALS"], str(adc))


class StagingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.proj = make_project(self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_excludes(self) -> None:
        pats = cr.DEFAULT_EXCLUDES
        self.assertTrue(cr.is_excluded("renders", True, pats))
        self.assertTrue(cr.is_excluded("capture/shots/frames", True, pats))
        self.assertTrue(cr.is_excluded("capture/a/b/frames", True, pats))
        self.assertFalse(cr.is_excluded("compositions/frames", True, pats))
        self.assertTrue(cr.is_excluded("assets/.DS_Store", False, pats))
        self.assertFalse(cr.is_excluded("renders.txt", False, pats))
        self.assertTrue(cr.is_excluded("deep/x.take1.mp4", False, ["*.take1.mp4"]))

    def test_stage_skips_generated_outputs(self) -> None:
        stage = self.root / "stage"
        files, size, skipped = cr.stage_project(self.proj, stage, list(cr.DEFAULT_EXCLUDES))
        self.assertTrue((stage / "capture/shots/c1.mp4").exists())
        self.assertTrue((stage / "compositions/frames/01.html").exists())
        self.assertFalse((stage / "renders").exists())
        self.assertFalse((stage / "qa").exists())
        self.assertFalse((stage / "capture/shots/frames").exists())
        self.assertIn("capture/shots/frames/", skipped)
        self.assertEqual(cr.missing_references(self.proj, stage), ([], []))
        self.assertEqual(cr.drop_unreferenced_media(self.proj, stage)[0], 2)
        self.assertTrue((stage / "assets/media/a.mp4").exists())
        self.assertFalse((stage / "assets/score/music.mp3").exists())

    def test_references_and_missing(self) -> None:
        refs = cr.referenced_assets(self.proj)
        self.assertIn("assets/media/a.mp4", refs)
        self.assertIn("capture/shots/c1.mp4", refs)
        self.assertIn("assets/fonts/x.woff2", refs)
        self.assertFalse(any(r.startswith("http") for r in refs))
        stage = self.root / "stage2"
        cr.stage_project(self.proj, stage, [*cr.DEFAULT_EXCLUDES, "capture/"])
        self.assertEqual(cr.missing_references(self.proj, stage), ([], ["capture/shots/c1.mp4"]))
        (self.proj / "assets/media/a.mp4").unlink()
        self.assertEqual(cr.missing_references(self.proj, stage)[0], ["assets/media/a.mp4"])

    def test_project_facts(self) -> None:
        self.assertEqual(cr.project_dims(self.proj), (1920, 1080, 30))
        self.assertEqual(cr.composition_duration(self.proj), 12.5)
        self.assertEqual(cr.pinned_version(self.proj), "0.8.163")


class DryRunTests(unittest.TestCase):
    def test_render_dry_run_reports_profile_and_upload(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            home = root / "home"
            slot_parent = home / "dev" / "work"
            slot_parent.mkdir(parents=True)
            proj = make_project(slot_parent)
            cfg_dir = root / "cfg"
            cfg_dir.mkdir()
            (cfg_dir / "profiles.toml").write_text(CONFIG)
            env = {"HOME": str(home), "MEDIA_TOOLING_CONFIG_DIR": str(cfg_dir), "MEDIA_TOOLING_CACHE_DIR": str(root / "cache")}
            out, err = io.StringIO(), io.StringIO()
            with mock.patch.dict(os.environ, env), redirect_stdout(out), redirect_stderr(err):
                code = cr.main(["render", str(proj), "--dry-run"])
            self.assertEqual(code, 0, err.getvalue())
            summary = json.loads(out.getvalue())
            self.assertEqual(summary["profile"], "work")
            self.assertEqual(summary["gcp_project"], "work-proj")
            self.assertEqual(summary["frames"], 375)
            self.assertEqual(summary["upload"]["files"], 6)
            self.assertEqual(summary["upload"]["unreferenced_media_left_out"]["files"], 2)
            self.assertIsNone(summary["stack"])

    def test_render_refuses_references_missing_from_the_project(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            proj = make_project(root)
            (proj / "assets/fonts/x.woff2").unlink()
            cfg_dir = root / "cfg"
            cfg_dir.mkdir()
            (cfg_dir / "profiles.toml").write_text(CONFIG)
            env = {"HOME": str(root), "MEDIA_TOOLING_CONFIG_DIR": str(cfg_dir), "MEDIA_TOOLING_CACHE_DIR": str(root / "cache")}
            for extra, expected in (([], 2), (["--allow-missing-refs"], 0)):
                out, err = io.StringIO(), io.StringIO()
                with mock.patch.dict(os.environ, env), redirect_stdout(out), redirect_stderr(err):
                    code = cr.main(["render", str(proj), "--dry-run", *extra])
                self.assertEqual(code, expected, err.getvalue())
                self.assertEqual(json.loads(out.getvalue())["missing_references"]["not_in_project"], ["assets/fonts/x.woff2"])


if __name__ == "__main__":
    unittest.main()
