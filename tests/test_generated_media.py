from __future__ import annotations

import copy
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from unittest.mock import patch

from PIL import Image

from media_tooling import generated_media as gm


def fixture(kind: str) -> dict[str, Any]:
    return gm.read_json(gm.CONTRACT_DIR / "fixtures" / (gm.DOCUMENTS[kind][2] + ".valid.json"))


class ContractTest(unittest.TestCase):
    def test_shared_golden_documents_and_hashes(self) -> None:
        for path in (gm.CONTRACT_DIR / "fixtures").glob("*.json"):
            kind = next(kind for kind, value in gm.DOCUMENTS.items() if path.name.startswith(value[2] + "."))
            with self.subTest(path=path.name):
                if ".invalid." in path.name:
                    with self.assertRaises(gm.IntegrationError):
                        gm.validate_document(kind, gm.read_json(path))
                else:
                    gm.validate_document(kind, gm.read_json(path))
        self.assertEqual(gm.canonical_bytes({"b": -0.0, "a": [1.0, "ñ"]}), '{"a":[1,"ñ"],"b":0}'.encode())
        for value in (float("nan"), float("inf")):
            with self.assertRaises(gm.IntegrationError):
                gm.canonical_bytes(value)
        with self.assertRaises(gm.IntegrationError):
            gm.decode_json(b'{"a":1,"a":2}')

    def test_strict_types_versions_hashes_and_secrets(self) -> None:
        request = fixture("request")
        for key, value in (("contract_version", "2.0"), ("revision", "4"), ("revision", True), ("revision", 4.5)):
            invalid = gm.seal({**request, key: value})
            with self.subTest(key=key, value=value), self.assertRaises(gm.IntegrationError):
                gm.validate_document("request", invalid)
        request["revision"] = 5
        with self.assertRaises(gm.IntegrationError):
            gm.validate_document("request", request)
        for secret in ({"apiKey": "x"}, "a https://example.com/file?signature=x", "Bearer xyz", "https://x/#secret"):
            with self.assertRaises(gm.IntegrationError):
                gm.reject_secrets(secret)

    def test_file_and_http_use_identical_canonical_bytes(self) -> None:
        document = fixture("request")
        received = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                received.append(self.rfile.read(int(self.headers["Content-Length"])))
                response = gm.canonical_bytes(fixture("plan"))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(response)

            def log_message(self, format: str, *args: Any) -> None:
                pass

        with tempfile.TemporaryDirectory() as temp:
            project, handoff = Path(temp) / "project", Path(temp) / "handoff"
            file_response = gm.send_document(project, "request", document, handoff=handoff)
            with HTTPServer(("127.0.0.1", 0), Handler) as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    response = gm.send_document(project, "request", document, server=f"http://127.0.0.1:{server.server_port}")
                finally:
                    server.shutdown()
                    thread.join()
            self.assertEqual(received, [Path(file_response["handoff_path"]).read_bytes()])
            self.assertEqual(gm.canonical_bytes(response), gm.canonical_bytes(fixture("plan")))
            changed = gm.seal({**document, "revision": 100})
            with self.assertRaises(gm.IntegrationError):
                gm.send_document(project, "request", changed, handoff=handoff)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class AssemblyTest(unittest.TestCase):
    source_temp: tempfile.TemporaryDirectory[str]
    asset_root: Path
    source: Path
    media: dict[str, Any]
    @classmethod
    def setUpClass(cls) -> None:
        cls.source_temp = tempfile.TemporaryDirectory()
        cls.asset_root = Path(cls.source_temp.name)
        cls.source = cls.asset_root / "clip.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=320x180:r=24:d=2",
                        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo:d=2", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-shortest", str(cls.source)], check=True, capture_output=True)
        cls.media = gm.probe_media(cls.source)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.source_temp.cleanup()

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        scene = fixture("request")["scenes"][0]
        scene["reference_assets"] = []
        scene["continuity"] = {"mode": "independent", "required_reference_asset_ids": []}
        self.board = {"approved": True, "project_id": "pilot", "revision_id": "board-1",
                      "scenes": [{**copy.deepcopy(scene), "scene_id": f"scene-{i}", "order": i, "requested_duration_s": 2} for i in (3, 1, 2)]}
        self.request = gm.build_request(self.project, self.board, request_id="request-1")
        self.plan = fixture("plan")
        self.plan.update({"plan_id": "plan-1", "request_id": "request-1", "valid_until": "2099-01-01T00:00:00Z"})
        self.plan["scenes"] = [{**copy.deepcopy(self.plan["scenes"][0]), "scene_id": f"scene-{i}", "order": i,
                                "variants": [{**copy.deepcopy(self.plan["scenes"][0]["variants"][0]), "variant_id": f"variant-{i}"}]} for i in (1, 2, 3)]
        for i, plan_scene in enumerate(self.plan["scenes"], 1):
            template = plan_scene["variants"][0]["shots"][0]
            plan_scene["variants"][0]["shots"] = [{**copy.deepcopy(template), "shot_id": f"shot-{i}-{j}", "order": j} for j in range(2 if i == 2 else 1)]
        self.plan["scenes"][0]["variants"][0]["provider"] = "fal"
        self.plan["scenes"][2]["variants"][0]["provider"] = "fallback"
        self.plan = gm.seal(self.plan)
        self.approval = gm.approve_plan(self.project, self.plan, [f"variant-{i}" for i in (1, 2, 3)], approval_id="approval-1", allow_unknown_cost=True)
        self.result = fixture("result")
        self.result.update({"result_id": "result-1", "request_id": "request-1", "plan_id": "plan-1", "approval_id": "approval-1", "reference_assets": [], "scenes": []})
        reference_path = self.asset_root / "reference.png"
        Image.new("RGB", (320, 180), "gray").save(reference_path)
        self.result["reference_assets"] = [{"asset_id": "consumed-boundary", "uri": reference_path.as_uri(), "sha256": gm.file_hash(reference_path),
                                             "mime_type": "image/png", "role": "first_frame", "rights_note": "Synthetic", "source_take_id": "take-2"}]
        for i in (1, 2, 3):
            result_scene = copy.deepcopy(fixture("result")["scenes"][0])
            result_scene.update({"scene_id": f"scene-{i}", "order": i, "actual_shots": [], "attempts": [], "clips": [], "takes": []})
            for j in range(2 if i == 2 else 1):
                shot_id, attempt_id, clip_id = f"shot-{i}-{j}", f"attempt-{i}-{j}", f"clip-{i}-{j}"
                result_scene["actual_shots"].append({"shot_id": shot_id, "order": j, "nominal_duration_s": 2, "continuity_mode": "cut"})
                attempt = copy.deepcopy(fixture("result")["scenes"][0]["attempts"][0])
                attempt.update({"attempt_id": attempt_id, "shot_id": shot_id, "reference_asset_ids": []})
                if i == 1:
                    attempt["provider"] = "fal.ai"
                attempt["billing"] = {"raw_unit_name": "credits", "raw_units": "99", "estimated_usd": 0 if i == 1 else None, "actual_usd": None, "currency": "USD"}
                if i == 3:
                    attempt["reference_asset_ids"] = ["consumed-boundary"]
                    failed = {**copy.deepcopy(attempt), "attempt_id": "failed-3", "status": "failed", "error": {"code": "retry", "message": "Synthetic failure"}}
                    result_scene["attempts"].append(failed)
                    attempt.update({"attempt_number": 2, "fallback_from_attempt_id": "failed-3", "provider": "fallback"})
                result_scene["attempts"].append(attempt)
                asset = {"asset_id": clip_id, "uri": self.source.as_uri(), "sha256": gm.file_hash(self.source), "mime_type": "video/mp4", "role": "generated_clip", "rights_note": "Synthetic test"}
                result_scene["clips"].append({"clip_id": clip_id, "attempt_id": attempt_id, "asset": asset, "media": self.media})
            clip_ids = [clip["clip_id"] for clip in result_scene["clips"]]
            result_scene["takes"] = [{"take_id": f"take-{i}", "clip_ids": list(reversed(clip_ids)), "clip_order": {key: j for j, key in enumerate(clip_ids)},
                                      "preview_asset_id": None, "supersedes_take_ids": [], "depends_on_take_ids": ["take-2"] if i == 3 else [],
                                      "nominal_duration_s": 2 * len(clip_ids), "measured_duration_s": 2 * len(clip_ids)}]
            self.result["scenes"].append(result_scene)
        self.result = gm.seal(self.result)
        gm.import_result(self.project, self.result, asset_root=self.asset_root)
        self.draft: dict[str, Any] = {"edit_revision_id": "edit-1", "project_id": "pilot", "storyboard_revision_id": "board-1",
                      "source_results": [{"result_id": "result-1", "sha256": self.result["document_sha256"]}],
                      "scenes": [{"scene_id": scene["scene_id"], "order": scene["order"], "take_id": scene["takes"][0]["take_id"],
                                  "transition_out": {"type": "cut", "editorial_note": None},
                                  "clip_edits": [{"clip_id": key, "order": order, "trim_in_s": 0.25, "trim_out_s": 1.25, "audio_use": "preserve"}
                                                 for key, order in reversed(list(scene["takes"][0]["clip_order"].items()))]}
                                 for scene in reversed(self.result["scenes"])]}

    def test_compile_order_provenance_trims_and_cost(self) -> None:
        selection = gm.write_selection(self.project, self.draft)
        edl = gm.compile_selection(self.project, selection)
        self.assertEqual([row["beat"] for row in edl["ranges"]], ["scene-1", "scene-2", "scene-2", "scene-3"])
        self.assertEqual([item["clip_id"] for item in edl["generated_media"]["sources"].values()], ["clip-1-0", "clip-2-0", "clip-2-1", "clip-3-0"])
        self.assertEqual(gm.file_hash(gm.project_path(self.project, selection["edl"]["path"])), selection["edl"]["sha256"])
        cost = gm.cost_rollup(self.project, selection)
        self.assertEqual(len(cost["attempts"]), 5)
        self.assertIsNone(cost["all_attempts"]["estimated_usd"]["total"])
        self.assertEqual(cost["all_attempts"]["estimated_usd"]["known_subtotal"], 0)
        self.assertEqual(cost["all_attempts"]["estimated_usd"]["unknown_attempts"], 4)
        self.assertEqual(cost["attempts"][0]["raw_units"], "99")

    def test_fal_plan_alias_matches_recorded_provider(self) -> None:
        self.assertEqual(self.plan["scenes"][0]["variants"][0]["provider"], "fal")
        self.assertEqual(self.result["scenes"][0]["attempts"][0]["provider"], "fal.ai")
        gm.write_selection(self.project, self.draft)

    def test_unsafe_edits_fail_before_ffmpeg_and_hash_tamper(self) -> None:
        for field, value in (("trim_out_s", 10), ("trim_in_s", 1.5)):
            draft = copy.deepcopy(self.draft)
            draft["scenes"][0]["clip_edits"][0][field] = value
            with patch.object(gm, "_audio_source") as audio, self.assertRaises(gm.IntegrationError):
                gm.write_selection(self.project, draft)
            audio.assert_not_called()
        draft = copy.deepcopy(self.draft)
        draft["scenes"][0]["transition_out"]["type"] = "dissolve"
        with patch.object(gm, "probe_media") as probe, self.assertRaises(gm.IntegrationError):
            gm.write_selection(self.project, draft)
        probe.assert_not_called()
        unapproved = copy.deepcopy(self.result)
        unapproved["result_id"] = "unapproved-result"
        unapproved["scenes"][0]["actual_shots"][0]["shot_id"] = "unapproved-shot"
        unapproved["scenes"][0]["attempts"][0]["shot_id"] = "unapproved-shot"
        unapproved = gm.seal(unapproved)
        gm.import_result(self.project, unapproved, asset_root=self.asset_root)
        unapproved_draft = copy.deepcopy(self.draft)
        unapproved_draft["source_results"] = [{"result_id": unapproved["result_id"], "sha256": unapproved["document_sha256"]}]
        with self.assertRaisesRegex(gm.IntegrationError, "approved shot"):
            gm.write_selection(self.project, unapproved_draft)
        index = gm.read_json(self.project / "rough-cuts/manifests/imports/result-1.json")
        gm.project_path(self.project, index["assets"][0]["local_path"]).write_bytes(b"tampered")
        with self.assertRaises(gm.IntegrationError):
            gm.write_selection(self.project, self.draft)

    def test_selected_attempt_must_match_approved_variant(self) -> None:
        plan = copy.deepcopy(self.plan)
        plan["plan_id"] = "plan-variants"
        primary = plan["scenes"][0]["variants"][0]
        for field, value in (("provider", "other-provider"), ("model", "other-model"), ("prompt_snapshot", "other-prompt")):
            variant = copy.deepcopy(primary)
            variant["variant_id"] = f"unapproved-{field}"
            if field == "prompt_snapshot":
                variant["shots"][0][field] = value
            else:
                variant[field] = value
            plan["scenes"][0]["variants"].append(variant)
        plan = gm.seal(plan)
        approval = gm.approve_plan(self.project, plan, ["variant-1", "variant-2", "variant-3"],
                                   approval_id="approval-variants", allow_unknown_cost=True)
        for field, value in (("provider", "other-provider"), ("model", "other-model"), ("prompt_snapshot", "other-prompt")):
            with self.subTest(field=field):
                result = copy.deepcopy(self.result)
                result.update({"result_id": f"result-{field}", "plan_id": plan["plan_id"], "approval_id": approval["approval_id"]})
                result["scenes"][0]["attempts"][0][field] = value
                result = gm.seal(result)
                gm.import_result(self.project, result, asset_root=self.asset_root)
                draft = copy.deepcopy(self.draft)
                draft["source_results"] = [{"result_id": result["result_id"], "sha256": result["document_sha256"]}]
                with patch.object(gm, "_audio_source") as audio, self.assertRaisesRegex(gm.IntegrationError, "approved shot variant"):
                    gm.write_selection(self.project, draft)
                audio.assert_not_called()

    def test_asset_roots_symlinks_hash_and_probe(self) -> None:
        asset = self.result["scenes"][0]["clips"][0]["asset"]
        with self.assertRaises(gm.IntegrationError):
            gm.import_asset(self.project, asset, Path("bad.mp4"), asset_root=self.project)
        with self.assertRaises(gm.IntegrationError):
            gm.import_asset(self.project, {**asset, "sha256": "sha256:" + "0" * 64}, Path("bad.mp4"), asset_root=self.asset_root)
        with self.assertRaises(gm.IntegrationError):
            gm.import_asset(self.project, asset, Path("bad.mp4"), asset_root=self.asset_root, media={**self.media, "width": 1920})
        (self.project / "escape").symlink_to(self.asset_root, target_is_directory=True)
        with self.assertRaises(gm.IntegrationError):
            gm.project_path(self.project, "escape/overwrite.mp4")
        self.assertFalse((self.project / "bad.mp4").exists())

    def test_targeted_request_and_stale_decisions(self) -> None:
        selection = gm.write_selection(self.project, self.draft)
        request = gm.regenerate(self.project, self.board, selection, ["scene-2"], reason="New middle", request_id="request-2", revision=2)
        self.assertEqual([scene["scene_id"] for scene in request["scenes"]], ["scene-2"])
        self.assertEqual(request["regeneration"]["supersedes_take_ids"], ["take-2"])
        foreign_board = {**self.board, "project_id": "another-project"}
        with patch.object(gm, "build_request") as build, self.assertRaisesRegex(gm.IntegrationError, "different project"):
            gm.regenerate(self.project, foreign_board, selection, ["scene-2"], reason="Foreign storyboard")
        build.assert_not_called()
        replacement = copy.deepcopy(self.result)
        replacement["result_id"] = "result-2"
        replacement["scenes"] = [replacement["scenes"][1]]
        take = replacement["scenes"][0]["takes"][0]
        take.update({"take_id": "take-2-new", "supersedes_take_ids": ["take-2"]})
        replacement = gm.seal(replacement)
        gm.import_result(self.project, replacement, asset_root=self.asset_root)
        draft = copy.deepcopy(self.draft)
        draft["edit_revision_id"] = "edit-2"
        draft["source_results"].append({"result_id": "result-2", "sha256": replacement["document_sha256"]})
        draft["scenes"][1]["take_id"] = "take-2-new"
        with self.assertRaisesRegex(gm.IntegrationError, "Stale"):
            gm.write_selection(self.project, draft)
        draft["continuity_decisions"] = [{"scene_id": "scene-3", "dependency_take_id": "take-2", "decision": "accept_stale", "replacement_asset": None}]
        revised = gm.write_selection(self.project, draft)
        self.assertEqual(len(gm.stale_dependencies(revised, [self.result, replacement])), 1)
        self.assertEqual(gm.load_document(self.project, "result", "result-1"), self.result)
        draft["edit_revision_id"] = "edit-boundary"
        draft["continuity_decisions"][0]["decision"] = "regenerate"
        with self.assertRaisesRegex(gm.IntegrationError, "Stale"):
            gm.write_selection(self.project, draft)
        boundary_path = self.asset_root / "boundary.png"
        Image.new("RGB", (320, 180), "gray").save(boundary_path)
        boundary = {"asset_id": "boundary", "uri": boundary_path.as_uri(), "sha256": gm.file_hash(boundary_path),
                    "mime_type": "image/png", "role": "first_frame", "rights_note": "Synthetic", "source_take_id": "take-2-new"}
        imported = gm.import_asset(self.project, boundary, Path("assets/reference/boundary.png"), asset_root=self.asset_root)
        gm.immutable_write(self.project / "rough-cuts/manifests/boundaries/boundary.json", gm.canonical_bytes(imported))
        draft["continuity_decisions"][0].update({"decision": "use_boundary", "replacement_asset": boundary})
        boundary_selection = gm.write_selection(self.project, draft)
        self.assertEqual(boundary_selection["continuity_decisions"][0]["replacement_asset"]["sha256"], gm.file_hash(boundary_path))

    def test_actual_render_verify_and_idempotent_record(self) -> None:
        selection = gm.write_selection(self.project, self.draft)
        record = gm.render_selection(self.project, selection, preview=True, no_loudnorm=True)
        self.assertTrue(record["passed"], gm.read_json(gm.project_path(self.project, record["verification_path"])))
        self.assertEqual(record, gm.render_selection(self.project, selection, preview=True, no_loudnorm=True))
        self.assertTrue(gm.project_path(self.project, record["output_path"]).is_file())

    def test_mute_and_editorial_asset_hashes_preserve_originals(self) -> None:
        draft = copy.deepcopy(self.draft)
        draft["scenes"][0]["clip_edits"][0]["audio_use"] = "mute"
        subtitles = self.project / "subtitles" / "captions.srt"
        subtitles.write_text("1\n00:00:00,000 --> 00:00:01,000\nSynthetic caption\n")
        original_hash = gm.file_hash(self.source)
        selection = gm.write_selection(self.project, draft, edl_options={"subtitles": "subtitles/captions.srt", "grade": "neutral_punch"})
        edl = gm.compile_selection(self.project, selection)
        self.assertEqual(edl["generated_media"]["editorial_assets"][0]["sha256"], gm.file_hash(subtitles))
        self.assertEqual(gm.file_hash(self.source), original_hash)
        muted = next(value for value in edl["generated_media"]["sources"].values() if value["audio_use"] == "mute")
        self.assertIn("derived_asset_sha256", muted)
        subtitles.write_text("changed")
        with self.assertRaisesRegex(gm.IntegrationError, "EDL"):
            gm.render_selection(self.project, selection, no_loudnorm=True)
        gm.project_path(self.project, muted["local_path"]).write_bytes(b"tampered derivative")
        with self.assertRaisesRegex(gm.IntegrationError, "derivative"):
            gm.compile_selection(self.project, selection)


if __name__ == "__main__":
    unittest.main()
