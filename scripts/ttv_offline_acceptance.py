"""Consume the TTV fake-provider pilot as files, then render both editorial revisions."""
from __future__ import annotations

import argparse
import copy
from pathlib import Path
from typing import Any

from media_tooling import generated_media as gm


def choose_scene(scene: dict[str, Any]) -> dict[str, Any]:
    take = scene["takes"][0]
    clips = {clip["clip_id"]: clip for clip in scene["clips"]}
    return {"scene_id": scene["scene_id"], "order": scene["order"], "take_id": take["take_id"],
            "transition_out": {"type": "cut", "editorial_note": None},
            "clip_edits": [{"clip_id": clip_id, "order": order, "trim_in_s": 0,
                            "trim_out_s": clips[clip_id]["media"]["measured_duration_s"], "audio_use": "preserve"}
                           for clip_id, order in take["clip_order"].items()]}


def run(handoff: Path, asset_root: Path, project: Path) -> dict[str, Any]:
    if project.exists():
        raise ValueError("Acceptance project must be a new directory")
    project.mkdir(parents=True)
    board = gm.read_json(handoff / "storyboard.json")
    gm.immutable_write(gm.project_path(project, Path("storyboards") / (board["revision_id"] + ".json")), gm.canonical_bytes(board))
    results = []
    for prefix in ("", "regeneration-"):
        for kind in ("request", "plan", "approval"):
            gm.store_document(project, kind, gm.read_json(handoff / (prefix + kind + ".json")))
        result = gm.read_json(handoff / (prefix + "result.json"))
        gm.import_result(project, result, asset_root=asset_root)
        results.append(result)
    original, replacement = results
    scenes = sorted(original["scenes"], key=lambda scene: scene["order"])
    assert [len(scene["takes"][0]["clip_ids"]) for scene in scenes] == [1, 3, 1]
    attempts = [attempt for scene in scenes for attempt in scene["attempts"]]
    assert any(attempt["status"] == "failed" for attempt in attempts)
    assert any(attempt["fallback_from_attempt_id"] for attempt in attempts)
    assert len(replacement["scenes"]) == 1 and replacement["scenes"][0]["scene_id"] == scenes[1]["scene_id"]
    assert scenes[1]["takes"][0]["take_id"] in replacement["scenes"][0]["takes"][0]["supersedes_take_ids"]
    original_draft = {"edit_revision_id": "pilot-edit-1", "project_id": board["project_id"],
                      "storyboard_revision_id": board["revision_id"],
                      "source_results": [{"result_id": original["result_id"], "sha256": original["document_sha256"]}],
                      "scenes": [choose_scene(scene) for scene in reversed(scenes)]}
    selection = gm.write_selection(project, original_draft)
    original_record = gm.render_selection(project, selection, preview=True, no_loudnorm=True)
    assert original_record["passed"]
    revised_draft = copy.deepcopy(original_draft)
    revised_draft["edit_revision_id"] = "pilot-edit-2"
    revised_draft["source_results"].append({"result_id": replacement["result_id"], "sha256": replacement["document_sha256"]})
    revised_draft["scenes"] = [choose_scene(replacement["scenes"][0]) if scene["scene_id"] == scenes[1]["scene_id"] else scene for scene in revised_draft["scenes"]]
    revised_draft["continuity_decisions"] = []
    stale = gm.stale_dependencies(revised_draft, results)
    assert stale, "TTV pilot must emit a genuine dependency on the replaced middle take"
    try:
        gm.write_selection(project, revised_draft)
    except gm.IntegrationError as exc:
        assert "Stale" in str(exc)
    else:
        raise AssertionError("Unresolved continuity should block compilation")
    revised_draft["continuity_decisions"] = [{"scene_id": item["scene_id"], "dependency_take_id": item["dependency_take_id"],
                                            "decision": "accept_stale", "replacement_asset": None} for item in stale]
    revised = gm.write_selection(project, revised_draft)
    revised_record = gm.render_selection(project, revised, preview=True, no_loudnorm=True)
    assert revised_record["passed"]
    before = original_record["provenance"]["sources"]
    after = revised_record["provenance"]["sources"]
    for scene_id in (scenes[0]["scene_id"], scenes[2]["scene_id"]):
        old = [(item["take_id"], item["asset_sha256"]) for item in before.values() if item["scene_id"] == scene_id]
        new = [(item["take_id"], item["asset_sha256"]) for item in after.values() if item["scene_id"] == scene_id]
        assert old == new
    assert gm.load_document(project, "result", original["result_id"]) == original
    summary = {"passed": True, "original_render": original_record, "revised_render": revised_record,
               "stale_dependencies": stale, "costs": gm.cost_rollup(project, revised)}
    gm.immutable_write(project / "acceptance.json", gm.canonical_bytes(summary))
    return {"passed": True, "project": str(project), "original_output": original_record["output_path"],
            "revised_output": revised_record["output_path"], "stale_dependencies": len(stale)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handoff", type=Path, required=True)
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    args = parser.parse_args()
    print(gm.canonical_bytes(run(args.handoff.resolve(), args.asset_root.resolve(), args.project.resolve())).decode())
