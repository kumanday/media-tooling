from __future__ import annotations

import email.message
import io
import json
import os
import stat
import subprocess
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any
from unittest import mock

from media_tooling import cloud_render as cr
from media_tooling.local_config import Resolved

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


def resolve(project_dir: Path, cfg: dict[str, Any], cli_profile: str | None = None) -> Resolved:
    r = cr.resolve_profile(project_dir, cfg, cli_profile)
    assert r is not None
    return r


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
        self.assertEqual(resolve(work, cfg).name, "work")
        self.assertEqual(resolve(other, cfg).name, "personal")
        self.assertEqual(resolve(other, cfg).reason, "default_profile")
        self.assertEqual(resolve(work, cfg, "personal").name, "personal")

    def test_project_pin_beats_rules(self) -> None:
        cfg = cr.load_config()
        blog = self.home / "dev" / "work" / "blog"
        (blog / "media-tooling.toml").write_text('render_profile = "personal"\n')
        r = resolve(blog / "slot", cfg)
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


TOKEN = "ya29.test-access-token"
USER_ADC = {"type": "authorized_user", "client_id": "cid.apps.example", "client_secret": "csecret",
            "refresh_token": "1//test-refresh-token"}


class CloudEnvCase(unittest.TestCase):
    """A private config folder with the test profiles (plus one without an account) and a fake HOME."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.cfg_dir = self.root / "cfg"
        self.cfg_dir.mkdir()
        (self.cfg_dir / "profiles.toml").write_text(
            CONFIG + '\n[profiles.noacct]\ngcloud_configuration = "noacct-cfg"\nproject = "noacct-proj"\n')
        self.env = mock.patch.dict(os.environ, {"HOME": str(self.home), "MEDIA_TOOLING_CONFIG_DIR": str(self.cfg_dir),
                                                "MEDIA_TOOLING_CACHE_DIR": str(self.root / "cache")})
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()

    def main(self, *argv: str, tools: tuple[str, ...] = ("terraform", "node")) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("shutil.which", lambda b: f"/opt/bin/{b}" if b in tools else None), \
                redirect_stdout(out), redirect_stderr(err):
            code = cr.main(list(argv))
        return code, out.getvalue(), err.getvalue()


class SetupAccountTests(CloudEnvCase):
    def setUp(self) -> None:
        super().setUp()
        self.gcloud_adc = self.home / ".config" / "gcloud" / "application_default_credentials.json"
        self.gcloud_adc.parent.mkdir(parents=True)
        self.gcloud_adc.write_text(json.dumps(USER_ADC))
        self.posts: list[tuple[str, dict[str, str]]] = []
        configs = json.dumps([{"name": n} for n in ("work-cfg", "personal-cfg", "noacct-cfg")])
        self.quiet_patch = mock.patch.object(cr, "quiet", side_effect=lambda cmd, env: subprocess.CompletedProcess(cmd, 0, configs, ""))
        self.run_patch = mock.patch.object(cr, "run")
        self.quiet_mock, self.run_mock = self.quiet_patch.start(), self.run_patch.start()

    def tearDown(self) -> None:
        self.quiet_patch.stop()
        self.run_patch.stop()
        super().tearDown()

    def google(self, email: str) -> Any:
        """A stand-in for Google's token and tokeninfo endpoints that signs everything in as `email`."""
        def post(url: str, fields: dict[str, str]) -> dict[str, str]:
            self.posts.append((url, dict(fields)))
            if url == cr.TOKEN_URL:
                self.assertEqual(fields["grant_type"], "refresh_token")
                self.assertEqual(fields["refresh_token"], USER_ADC["refresh_token"])
                return {"access_token": TOKEN, "expires_in": "3599"}
            self.assertEqual((url, fields), (cr.TOKENINFO_URL, {"access_token": TOKEN}))
            return {"email": email, "email_verified": "true"}
        return mock.patch.object(cr, "post_form", side_effect=post)

    def adc(self, profile: str) -> Path:
        return self.cfg_dir / "adc" / f"{profile}.json"

    @staticmethod
    def report(out: str) -> dict[str, Any]:
        result: dict[str, Any] = json.loads(out[out.index("{"):])
        return result

    def test_save_adc_matching_account_ignores_case(self) -> None:
        with self.google("Me@Example.COM"):
            code, out, err = self.main("setup", "--profile", "personal", "--save-adc")
        self.assertEqual(code, 0, err)
        saved = json.loads(self.adc("personal").read_text())
        self.assertEqual(saved["refresh_token"], USER_ADC["refresh_token"])
        self.assertEqual(saved["quota_project_id"], "personal-proj")
        self.assertEqual(stat.S_IMODE(self.adc("personal").stat().st_mode), 0o600)
        report = self.report(out)
        self.assertEqual((report["adc_file"], report["adc_account"]), ("ok", "Me@Example.COM"))
        self.assertEqual(report["terraform"], "ok (terraform)")
        self.assertEqual(len(self.posts), 2)   # the report reuses the account checked before saving
        self.assertNotIn(TOKEN, out + err)
        self.assertFalse(any(TOKEN in url for url, _ in self.posts))

    def test_save_adc_wrong_account_writes_nothing(self) -> None:
        with self.google("me@example.com"):
            code, out, err = self.main("setup", "--profile", "work", "--save-adc")
        self.assertEqual(code, 2)
        self.assertFalse((self.cfg_dir / "adc").exists())
        for text in ("me@example.com", "me@work.example", "nothing saved", "gcloud auth application-default login",
                     "media-cloud-render setup --profile work --save-adc"):
            self.assertIn(text, err)
        self.assertNotIn(TOKEN, out + err)
        self.quiet_mock.assert_not_called()   # not even the gcloud configuration is touched
        self.run_mock.assert_not_called()

    def test_save_adc_without_profile_account_warns(self) -> None:
        with self.google("someone@example.com"):
            code, out, err = self.main("setup", "--profile", "noacct", "--save-adc", tools=("tofu", "node"))
        self.assertEqual(code, 0, err)
        self.assertTrue(self.adc("noacct").exists())
        self.assertIn("warning", err)
        self.assertIn("someone@example.com", err)
        report = self.report(out)
        self.assertEqual(report["adc_account"], "someone@example.com")
        self.assertEqual(report["terraform"], "ok (tofu)")

    def test_save_adc_unverifiable_writes_nothing(self) -> None:
        refused = cr.CloudRenderError(f"{cr.TOKEN_URL} answered 400: Token has been expired or revoked.")
        with mock.patch.object(cr, "post_form", side_effect=refused):
            code, _, err = self.main("setup", "--profile", "personal", "--save-adc")
        self.assertEqual(code, 2)
        self.assertFalse((self.cfg_dir / "adc").exists())
        self.assertIn("expired or revoked", err)
        self.assertIn("nothing saved", err)
        self.gcloud_adc.write_text(json.dumps({"type": "service_account", "client_email": "sa@example.com"}))
        code, _, err = self.main("setup", "--profile", "personal", "--save-adc")
        self.assertEqual(code, 2)
        self.assertIn("service_account", err)
        self.assertFalse((self.cfg_dir / "adc").exists())

    def test_plain_setup_reports_existing_file_account(self) -> None:
        self.adc("work").parent.mkdir()
        self.adc("work").write_text(json.dumps(USER_ADC))
        with self.google("me@example.com"):
            code, out, _ = self.main("setup", "--profile", "work")
        report = self.report(out)
        self.assertEqual(code, 1)
        self.assertEqual(report["adc_account"], "me@example.com")
        self.assertTrue(report["adc_file"].startswith("belongs to me@example.com, not me@work.example"))
        with self.google("ME@work.example"):
            code, out, _ = self.main("setup", "--profile", "work")
        self.assertEqual(code, 0)
        self.assertEqual(self.report(out)["adc_file"], "ok")

    def test_missing_terraform_hint_uses_hashicorp_tap(self) -> None:
        code, out, _ = self.main("setup", "--profile", "personal", tools=("node",))
        self.assertEqual(code, 1)
        self.assertIn("brew install hashicorp/tap/terraform", self.report(out)["terraform"])
        self.assertIsNone(self.report(out)["adc_account"])


class TokenRequestTests(unittest.TestCase):
    def test_post_form_sends_the_token_in_the_body(self) -> None:
        reply = mock.MagicMock()
        reply.__enter__.return_value.read.return_value = b'{"email": "me@example.com"}'
        with mock.patch("urllib.request.urlopen", return_value=reply) as urlopen:
            self.assertEqual(cr.post_form(cr.TOKENINFO_URL, {"access_token": TOKEN}), {"email": "me@example.com"})
        req = urlopen.call_args.args[0]
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.full_url, cr.TOKENINFO_URL)
        self.assertEqual(req.data, f"access_token={TOKEN}".encode())

    def test_post_form_error_names_the_reason_not_the_token(self) -> None:
        body = io.BytesIO(b'{"error": "invalid_token", "error_description": "Invalid Value"}')
        refused = urllib.error.HTTPError(cr.TOKENINFO_URL, 400, "Bad Request", email.message.Message(), body)
        with mock.patch("urllib.request.urlopen", side_effect=refused), self.assertRaises(cr.CloudRenderError) as ctx:
            cr.post_form(cr.TOKENINFO_URL, {"access_token": TOKEN})
        self.assertIn("Invalid Value", str(ctx.exception))
        self.assertNotIn(TOKEN, str(ctx.exception))

    def test_adc_account_mints_then_asks_tokeninfo(self) -> None:
        replies = [{"access_token": TOKEN}, {"email": "me@example.com"}]
        with mock.patch.object(cr, "post_form", side_effect=replies) as post:
            self.assertEqual(cr.adc_account(USER_ADC), "me@example.com")
        self.assertEqual([c.args[0] for c in post.call_args_list], [cr.TOKEN_URL, cr.TOKENINFO_URL])
        with mock.patch.object(cr, "post_form", side_effect=[{"access_token": TOKEN}, {"aud": "x"}]), \
                self.assertRaises(cr.CloudRenderError):
            cr.adc_account(USER_ADC)


class TerraformTests(CloudEnvCase):
    def test_terraform_preferred_then_tofu(self) -> None:
        for tools, expected in ((("terraform", "tofu"), "terraform"), (("tofu",), "tofu"), ((), None)):
            with mock.patch("shutil.which", lambda b, t=tools: f"/opt/bin/{b}" if b in t else None):
                self.assertEqual(cr.terraform_bin(), expected)

    def test_deploy_without_either_gives_the_install_hint(self) -> None:
        code, _, err = self.main("deploy", "--profile", "work", "--yes", tools=())
        self.assertEqual(code, 2)
        self.assertIn("brew tap hashicorp/tap && brew install hashicorp/tap/terraform", err)
        self.assertIn("brew install opentofu", err)

    def test_deploy_creates_the_workflows_agent_before_terraform(self) -> None:
        (self.cfg_dir / "adc").mkdir()
        (self.cfg_dir / "adc" / "work.json").write_text("{}")
        runtime = self.root / "rt"
        (runtime / "node_modules" / "@hyperframes" / "gcp-cloud-run" / "terraform").mkdir(parents=True)
        calls: list[list[str]] = []

        def quiet(cmd: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        def run(cmd: list[str], env: dict[str, str], cwd: Path | None = None, capture: bool = False,
                check: bool = True) -> str:
            calls.append(cmd)
            return "out"

        with mock.patch.object(cr, "quiet", side_effect=quiet), mock.patch.object(cr, "run", side_effect=run), \
                mock.patch.object(cr, "ensure_runtime", return_value=runtime):
            code, _, err = self.main("deploy", "--profile", "work", "--image", "reg/img:1", "--yes")
        self.assertEqual(code, 0, err)
        heads = [" ".join(c[:4]) for c in calls]
        agent = heads.index("gcloud beta services identity")
        self.assertLess(heads.index("gcloud services enable run.googleapis.com"), agent)
        self.assertLess(agent, heads.index("terraform apply -input=false -auto-approve"))
        self.assertEqual(calls[agent][-2:], ["--project", "work-proj"])
        self.assertNotIn("gcloud builds submit", " | ".join(heads))   # --image skips the build

    def test_destroy_runs_tofu_when_terraform_is_missing(self) -> None:
        stack_dir = self.cfg_dir / "cloudrun" / "work"
        stack_dir.mkdir(parents=True)
        (stack_dir / "stack.json").write_text(json.dumps({"project": "work-proj", "region": "us-central1",
                                                          "bucketName": "b", "image": "img", "tfstate_bucket": "tfb"}))
        with mock.patch.object(cr, "run") as run:
            code, _, err = self.main("destroy", "--profile", "work", "--yes", tools=("tofu",))
        self.assertEqual(code, 0, err)
        self.assertEqual([c.args[0][:2] for c in run.call_args_list], [["tofu", "init"], ["tofu", "destroy"]])
        self.assertFalse((stack_dir / "stack.json").exists())


DOCKERFILE = """\
FROM node:22 AS base
# COPY commented/out.txt nowhere
COPY package.json bun.lock ./
COPY packages/core/package.json \\
     packages/core/package.json
COPY --chown=node:node scripts/build.mjs scripts/build.mjs
FROM base AS runtime
COPY --from=base /app/dist /app/dist
copy packages/core/ packages/core/
ADD ["assets/logo.svg", "/app/logo.svg"]
COPY <<EOF /app/inline.txt
EOF
RUN bun run build
"""


class RenderImageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.src = Path(self.tmp.name)
        dockerfile = self.src / cr.DOCKERFILE
        dockerfile.parent.mkdir(parents=True)
        dockerfile.write_text(DOCKERFILE)
        for f in ("package.json", "bun.lock", "packages/core/package.json", "packages/core/src/index.ts",
                  "scripts/build.mjs", "assets/logo.svg"):
            (self.src / f).parent.mkdir(parents=True, exist_ok=True)
            (self.src / f).write_text("x")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_dockerfile_sources_reads_the_build_context_only(self) -> None:
        self.assertEqual(cr.dockerfile_sources(self.src / cr.DOCKERFILE),
                         ["package.json", "bun.lock", "packages/core/package.json", "scripts/build.mjs",
                          "packages/core/", "assets/logo.svg"])

    def test_build_ignore_reincludes_parents_before_paths(self) -> None:
        lines = cr.build_ignore(["package.json", "packages/core/package.json", "packages/core/"])
        self.assertEqual(lines[0], "**")
        self.assertLess(lines.index("!packages/"), lines.index("!packages/core/"))
        self.assertLess(lines.index("!packages/core/"), lines.index("!packages/core/package.json"))
        self.assertIn("!packages/core/**", lines)
        self.assertEqual(len(lines), len(set(lines)))
        self.assertEqual(lines[-len(cr.BUILD_SKIP):], list(cr.BUILD_SKIP))   # skips win over re-includes
        self.assertEqual(cr.build_ignore(["./", "package.json"]), list(cr.BUILD_SKIP))

    def test_build_image_turns_on_buildkit_and_uploads_the_filtered_context(self) -> None:
        with mock.patch.object(cr, "run") as run:
            cr.build_image(self.src, "reg/img:1", "proj", "us-central1", {"X": "1"})
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[:4], ["gcloud", "builds", "submit", str(self.src)])
        ignore = Path(cmd[cmd.index("--ignore-file") + 1])
        self.assertIn("!scripts/build.mjs", ignore.read_text().splitlines())
        config = Path(cmd[cmd.index("--config") + 1]).read_text()
        self.assertIn('env: ["DOCKER_BUILDKIT=1"]', config)
        self.assertIn(f'"--build-arg","TARGETARCH={cr.IMAGE_ARCH}"', config)
        self.assertIn('images: ["reg/img:1"]', config)

    def test_build_image_stops_before_upload_when_a_copied_file_is_missing(self) -> None:
        (self.src / "scripts" / "build.mjs").unlink()
        with mock.patch.object(cr, "run") as run, self.assertRaises(cr.CloudRenderError) as ctx:
            cr.build_image(self.src, "reg/img:1", "proj", "us-central1", {})
        self.assertIn("scripts/build.mjs", str(ctx.exception))
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
