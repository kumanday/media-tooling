"""Versioned TTV handoff, verified project imports, and ordinary EDL compilation.

TTV owns generation. This adapter owns immutable editorial revisions. No provider
SDK or TTV runtime is needed; the pinned JSON schemas are the protocol boundary.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any, BinaryIO
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

from jsonschema import Draft202012Validator, FormatChecker
from PIL import Image

from media_tooling.edl_render import (
    EDL_VERSION,
    apply_padding,
    render_edl,
    validate_edl,
)
from media_tooling.project_init import ensure_project_directories
from media_tooling.verify import run_verification

CONTRACT_VERSION = "1.0"
CONTRACT_DIR = Path(__file__).parent / "contracts" / "v1_0"
SCHEMA_MANIFEST_SHA256 = "sha256:477478a4dbbfce5f653c60f11689543ccddb50cf3e7d6492065376c38ea98284"
DOCUMENTS = {
    "request": ("request_id", "requests", "GenerationRequest"),
    "plan": ("plan_id", "plans", "GenerationPlan"),
    "approval": ("approval_id", "approvals", "PlanApproval"),
    "result": ("result_id", "results", "GenerationResult"),
    "selection": ("edit_revision_id", "selections", "EditorialSelection"),
}
MAX_DOCUMENT_BYTES = 16 * 1024 * 1024
MAX_ASSET_BYTES = 20 * 1024**3


class IntegrationError(ValueError):
    """Invalid, incompatible, or unsafe integration input."""


def canonical_bytes(value: Any) -> bytes:
    def normalize(item: Any) -> Any:
        if isinstance(item, float):
            if not math.isfinite(item):
                raise IntegrationError("Non-finite JSON number")
            return int(item) if item.is_integer() else item
        if isinstance(item, dict):
            return {key: normalize(child) for key, child in item.items()}
        if isinstance(item, list):
            return [normalize(child) for child in item]
        return item

    return json.dumps(normalize(value), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def document_hash(document: dict[str, Any]) -> str:
    return sha256(canonical_bytes({k: v for k, v in document.items() if k != "document_sha256"}))


def seal(document: dict[str, Any]) -> dict[str, Any]:
    document = copy.deepcopy(document)
    document["document_sha256"] = document_hash(document)
    return document


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    if path.stat().st_size > MAX_DOCUMENT_BYTES:
        raise IntegrationError("Document exceeds 16 MiB")
    return decode_json(path.read_bytes())


def decode_json(data: bytes) -> dict[str, Any]:
    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise IntegrationError("Duplicate JSON key")
            result[key] = value
        return result

    if len(data) > MAX_DOCUMENT_BYTES:
        raise IntegrationError("Document exceeds 16 MiB")
    value = json.loads(data, object_pairs_hook=unique_pairs)
    if not isinstance(value, dict):
        raise IntegrationError("Expected a JSON object")
    canonical_bytes(value)
    return value


def reject_secrets(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if re.sub(r"[^a-z]", "", key.lower()) in {
                "authorization", "headers", "httpheaders", "apikey", "token",
                "accesstoken", "refreshtoken", "password", "secret", "credentials",
                "signedurl", "downloadurl", "privatekey", "secretkey",
            }:
                raise IntegrationError("Credentials and delivery URLs are forbidden in durable documents")
            reject_secrets(child)
    elif isinstance(value, list):
        for child in value:
            reject_secrets(child)
    elif isinstance(value, str):
        for candidate in re.findall(r"(?:https?|gs|s3|file)://[^\s\"<>]+", value, flags=re.I):
            uri = urlsplit(candidate)
            if uri.username or uri.password or uri.query or uri.fragment:
                raise IntegrationError("Durable URIs cannot contain credentials, queries, or fragments")
        if re.search(r"\bBearer\s+\S+", value, flags=re.I):
            raise IntegrationError("Authorization values are forbidden in durable documents")


def _unique(items: list[dict[str, Any]], key: str) -> dict[Any, dict[str, Any]]:
    result = {item[key]: item for item in items}
    if len(result) != len(items):
        raise IntegrationError(f"Duplicate {key}")
    return result


def validate_document(kind: str, document: dict[str, Any]) -> None:
    if document.get("contract_version") != CONTRACT_VERSION:
        raise IntegrationError(f"Incompatible contract version; supported version is {CONTRACT_VERSION}")
    reject_secrets(document)
    if file_hash(CONTRACT_DIR / "schema-hashes.json") != SCHEMA_MANIFEST_SHA256:
        raise IntegrationError("Pinned schema manifest hash mismatch")
    manifest = read_json(CONTRACT_DIR / "schema-hashes.json")
    schema_name = DOCUMENTS[kind][2] + ".schema.json"
    schema_path = CONTRACT_DIR / schema_name
    if file_hash(schema_path) != manifest[DOCUMENTS[kind][2]]:
        raise IntegrationError("Pinned contract schema hash mismatch")
    schema = read_json(schema_path)
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(document))
    if errors:
        # Do not echo schema validator messages: they can contain rejected secrets.
        raise IntegrationError("Invalid " + kind + " field: " + ".".join(map(str, errors[0].absolute_path)))
    if document_hash(document) != document["document_sha256"]:
        raise IntegrationError("Document SHA-256 mismatch")
    try:
        for key in ("created_at", "valid_until"):
            if key in document:
                datetime.fromisoformat(document[key].replace("Z", "+00:00"))
    except ValueError:
        raise IntegrationError("Invalid UTC timestamp") from None
    scenes = document.get("scenes", [])
    _unique(scenes, "scene_id")
    if scenes and "order" in scenes[0]:
        _unique(scenes, "order")
    if kind == "result":
        for scene in scenes:
            shots = _unique(scene["actual_shots"], "shot_id")
            _unique(scene["actual_shots"], "order")
            attempts = _unique(scene["attempts"], "attempt_id")
            clips = _unique(scene["clips"], "clip_id")
            _unique(scene["takes"], "take_id")
            seen: set[str] = set()
            for attempt in scene["attempts"]:
                if attempt["shot_id"] not in shots:
                    raise IntegrationError("Attempt refers to missing shot")
                fallback = attempt.get("fallback_from_attempt_id")
                if fallback is not None and fallback not in seen:
                    raise IntegrationError("Fallback refers to missing or later attempt")
                seen.add(attempt["attempt_id"])
            for clip in clips.values():
                if clip["attempt_id"] not in attempts or attempts[clip["attempt_id"]]["status"] != "succeeded":
                    raise IntegrationError("Clip must refer to a successful attempt")
            for take in scene["takes"]:
                if not take["clip_ids"] or len(set(take["clip_ids"])) != len(take["clip_ids"]):
                    raise IntegrationError("Take requires distinct ordered clips")
                if any(clip_id not in clips for clip_id in take["clip_ids"]):
                    raise IntegrationError("Take refers to missing clip")
                if set(take["clip_order"]) != set(take["clip_ids"]) or len(set(take["clip_order"].values())) != len(take["clip_ids"]):
                    raise IntegrationError("Take requires explicit unique clip order")
    if kind == "selection":
        for scene in scenes:
            for edit in scene["clip_edits"]:
                if edit["trim_out_s"] <= edit["trim_in_s"]:
                    raise IntegrationError("Clip trim_out_s must exceed trim_in_s")


def _component(identifier: str) -> str:
    # IDs remain opaque; only their local storage names need filesystem restrictions.
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,120}", identifier) and ".." not in identifier:
        return identifier
    return "id-" + hashlib.sha256(identifier.encode()).hexdigest()


def project_path(project: Path, relative: str | Path) -> Path:
    root = project.resolve()
    path = root / relative
    if not path.resolve().is_relative_to(root):
        raise IntegrationError("Path escapes project directory")
    if path.is_symlink():
        raise IntegrationError("Artifact path cannot be a symlink")
    return path


def immutable_write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temp = Path(stream.name)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        try:
            os.link(temp, path)
        except FileExistsError:
            if path.is_symlink() or path.read_bytes() != data:
                raise IntegrationError("Immutable artifact already exists with different content") from None
    finally:
        temp.unlink()
    return path


def document_path(project: Path, kind: str, identifier: str) -> Path:
    return project_path(project, Path("rough-cuts/manifests") / DOCUMENTS[kind][1] / (_component(identifier) + ".json"))


def store_document(project: Path, kind: str, document: dict[str, Any]) -> Path:
    validate_document(kind, document)
    identifier = document[DOCUMENTS[kind][0]]
    return immutable_write(document_path(project, kind, identifier), canonical_bytes(document))


def load_document(project: Path, kind: str, identifier: str) -> dict[str, Any]:
    document = read_json(document_path(project, kind, identifier))
    validate_document(kind, document)
    if document[DOCUMENTS[kind][0]] != identifier:
        raise IntegrationError("Document identity mismatch")
    return document


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_request(
    project: Path, storyboard: dict[str, Any], *, scene_ids: list[str] | None = None,
    request_id: str | None = None, revision: int = 1, supersedes_request_id: str | None = None,
    regeneration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if storyboard.get("approved") is not True:
        raise IntegrationError("Storyboard revision must be approved before request authoring")
    reject_secrets(storyboard)
    all_scenes = _unique(storyboard["scenes"], "scene_id")
    _unique(storyboard["scenes"], "order")
    targets = list(all_scenes) if scene_ids is None else scene_ids
    if not targets or len(set(targets)) != len(targets) or set(targets) - all_scenes.keys():
        raise IntegrationError("Scene subset contains missing or duplicate scene IDs")
    scenes = sorted((copy.deepcopy(all_scenes[key]) for key in targets), key=lambda scene: scene["order"])
    document = {
        "contract_version": CONTRACT_VERSION, "request_id": request_id or str(uuid4()),
        "project_id": storyboard["project_id"], "revision": revision,
        "supersedes_request_id": supersedes_request_id, "created_at": now(),
        "storyboard": {"revision_id": storyboard["revision_id"], "sha256": sha256(canonical_bytes(storyboard))},
        "scenes": scenes, "regeneration": regeneration,
    }
    document["idempotency_key"] = sha256(canonical_bytes(document))
    document = seal(document)
    validate_document("request", document)
    ensure_project_directories(project_dir=project, create_directories=True)
    immutable_write(project_path(project, Path("storyboards") / (_component(storyboard["revision_id"]) + ".json")), canonical_bytes(storyboard))
    store_document(project, "request", document)
    return document


def approve_plan(
    project: Path, plan: dict[str, Any], variant_ids: list[str], *, execution_mode: str = "video",
    approval_id: str | None = None, idempotency_key: str | None = None,
    keyframe_result_id: str | None = None,
    allow_unknown_cost: bool = False, max_estimated_cost_usd: float | None = None,
) -> dict[str, Any]:
    validate_document("plan", plan)
    if plan["status"] != "ready" or datetime.fromisoformat(plan["valid_until"].replace("Z", "+00:00")) <= datetime.now(timezone.utc):
        raise IntegrationError("Plan is blocked or expired")
    all_variants = {variant["variant_id"] for scene in plan["scenes"] for variant in scene["variants"]}
    if len(set(variant_ids)) != len(variant_ids) or set(variant_ids) - all_variants:
        raise IntegrationError("Unknown or duplicate approved variant")
    if any(not set(variant_ids).intersection(v["variant_id"] for v in scene["variants"]) for scene in plan["scenes"]):
        raise IntegrationError("Every planned scene requires an approved variant")
    approved = [variant for scene in plan["scenes"] for variant in scene["variants"] if variant["variant_id"] in variant_ids]
    if any(variant["estimated_cost"]["amount"] is None for variant in approved) and not allow_unknown_cost:
        raise IntegrationError("Plan has unknown costs; approval requires --allow-unknown-cost")
    if keyframe_result_id is not None:
        keyframes = load_document(project, "result", keyframe_result_id)
        if keyframes["result_kind"] != "keyframes" or keyframes["plan_id"] != plan["plan_id"] or keyframes["terminal_status"] != "succeeded":
            raise IntegrationError("Approved keyframes must be a successful result from this plan")
    document = seal({
        "contract_version": CONTRACT_VERSION, "approval_id": approval_id or str(uuid4()),
        "request_id": plan["request_id"], "plan_id": plan["plan_id"],
        "plan_sha256": plan["document_sha256"], "created_at": now(),
        "execution_mode": execution_mode, "approved_variant_ids": variant_ids,
        "approved_keyframe_result_id": keyframe_result_id,
        "idempotency_key": idempotency_key or str(uuid4()),
        "allow_unknown_cost": allow_unknown_cost, "max_estimated_cost_usd": max_estimated_cost_usd,
    })
    store_document(project, "plan", plan)
    store_document(project, "approval", document)
    return document


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        raise IntegrationError("HTTP redirects require an explicit new endpoint")


def http_document(
    base_url: str, path: str, *, document: dict[str, Any] | None = None,
    token: str | None = None, method: str | None = None,
) -> dict[str, Any]:
    uri = urlsplit(base_url)
    if uri.scheme not in {"http", "https"} or not uri.hostname or uri.username or uri.password or uri.query or uri.fragment:
        raise IntegrationError("Invalid service endpoint")
    if uri.scheme == "http" and uri.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise IntegrationError("Remote services require HTTPS")
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = Request(base_url.rstrip("/") + path, data=None if document is None else canonical_bytes(document), headers=headers, method=method)
    try:
        with build_opener(_NoRedirect()).open(request, timeout=60) as response:
            return decode_json(response.read(MAX_DOCUMENT_BYTES + 1))
    except HTTPError as exc:
        raise IntegrationError(f"TTV returned HTTP {exc.code}") from None
    except URLError:
        raise IntegrationError("TTV connection failed") from None


def probe_media(path: Path) -> dict[str, Any]:
    result = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)], check=True, capture_output=True)
    payload = decode_json(result.stdout)
    video = next((stream for stream in payload["streams"] if stream["codec_type"] == "video"), None)
    if not video:
        raise IntegrationError("Imported clip has no video stream")
    duration = float(payload.get("format", {}).get("duration", video.get("duration", 0)))
    fps = float(Fraction(video.get("avg_frame_rate") or video["r_frame_rate"]))
    if not math.isfinite(duration) or duration <= 0 or not math.isfinite(fps) or fps <= 0:
        raise IntegrationError("Imported clip has invalid duration or frame rate")
    return {"measured_duration_s": duration, "width": int(video["width"]), "height": int(video["height"]),
            "fps": fps, "has_audio": any(stream["codec_type"] == "audio" for stream in payload["streams"])}


def _compare_media(expected: dict[str, Any], measured: dict[str, Any]) -> None:
    for key in ("width", "height", "has_audio"):
        if expected.get(key) is not None and expected[key] != measured[key]:
            raise IntegrationError("Clip media property mismatch: " + key)
    for key, tolerance in (("measured_duration_s", 0.05), ("fps", 0.01)):
        if expected.get(key) is not None and abs(expected[key] - measured[key]) > tolerance:
            raise IntegrationError("Clip media property mismatch: " + key)


def _copy_limited(stream: BinaryIO, destination: Path) -> None:
    total = 0
    with destination.open("wb") as output:
        while chunk := stream.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_ASSET_BYTES:
                raise IntegrationError("Asset exceeds 20 GiB")
            output.write(chunk)


def import_asset(
    project: Path, asset: dict[str, Any], relative: Path, *, asset_root: Path | None = None,
    deliveries: dict[str, str] | None = None, allowed_origins: list[str] | None = None,
    media: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reject_secrets(asset)
    asset_schema = read_json(CONTRACT_DIR / "GenerationResult.schema.json")
    schema = {"$defs": asset_schema["$defs"], "$ref": "#/$defs/AssetRef"}
    if not Draft202012Validator(schema).is_valid(asset):
        raise IntegrationError("Invalid AssetRef")
    if media is not None and not asset["mime_type"].startswith("video/"):
        raise IntegrationError("Generated clip MIME type must be video")
    destination = project_path(project, relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    delivery = (deliveries or {}).get(asset["uri"], asset["uri"])
    uri = urlsplit(delivery)
    with tempfile.TemporaryDirectory(dir=destination.parent) as stage:
        staged = Path(stage) / "asset"
        if uri.scheme in {"", "file"}:
            if uri.netloc or uri.query or uri.fragment:
                raise IntegrationError("Invalid local delivery URI")
            source = Path(unquote(uri.path)).resolve()
            # File roots are caller-controlled, never inferred from an imported result.
            if asset_root is None or not source.is_relative_to(asset_root.resolve()) or not source.is_file():
                raise IntegrationError("Local asset is outside the explicit asset root")
            with source.open("rb") as stream:
                _copy_limited(stream, staged)
        elif uri.scheme in {"https", "http"}:
            origin = f"{uri.scheme}://{uri.netloc}"
            if origin not in (allowed_origins or []) or uri.username or uri.password or uri.fragment:
                raise IntegrationError("Asset delivery origin is not explicitly allowed")
            if uri.scheme == "http" and uri.hostname not in {"localhost", "127.0.0.1", "::1"}:
                raise IntegrationError("Remote assets require HTTPS")
            try:
                with build_opener(_NoRedirect()).open(delivery, timeout=60) as response:
                    _copy_limited(response, staged)
            except (HTTPError, URLError):
                raise IntegrationError("Asset download failed") from None
        else:
            raise IntegrationError("Supply an explicit delivery mapping for this durable object URI")
        if file_hash(staged) != asset["sha256"]:
            raise IntegrationError("Asset SHA-256 mismatch")
        measured = probe_media(staged) if asset["mime_type"].startswith("video/") else None
        if measured is not None:
            _compare_media(media or asset.get("media") or {}, measured)
        if asset["mime_type"].startswith("image/"):
            with Image.open(staged) as image:
                if Image.MIME.get(image.format or "") != asset["mime_type"]:
                    raise IntegrationError("Image MIME type does not match its content")
                if asset.get("media"):
                    for key, actual in (("width", image.width), ("height", image.height)):
                        if asset["media"].get(key) is not None and asset["media"][key] != actual:
                            raise IntegrationError("Reference image dimensions mismatch")
                image.verify()
        try:
            os.link(staged, destination)
        except FileExistsError:
            if destination.is_symlink() or file_hash(destination) != asset["sha256"]:
                raise IntegrationError("Imported asset path already has different content") from None
    return {"asset_id": asset["asset_id"], "source_uri": asset["uri"], "sha256": asset["sha256"],
            "local_path": str(destination.relative_to(project.resolve())), "media": measured}


def import_result(
    project: Path, result: dict[str, Any], *, asset_root: Path | None = None,
    deliveries: dict[str, str] | None = None, allowed_origins: list[str] | None = None,
) -> dict[str, Any]:
    validate_document("result", result)
    records = []
    for scene in result["scenes"]:
        for clip in scene["clips"]:
            take_ids = [take["take_id"] for take in scene["takes"] if clip["clip_id"] in take["clip_ids"]]
            take_dir = take_ids[0] if take_ids else result["result_id"]
            relative = Path("rough-cuts/generated-clips") / _component(scene["scene_id"]) / _component(take_dir) / (_component(clip["clip_id"]) + ".mp4")
            record = import_asset(project, clip["asset"], relative, asset_root=asset_root, deliveries=deliveries, allowed_origins=allowed_origins, media=clip["media"])
            records.append({**record, "scene_id": scene["scene_id"], "clip_id": clip["clip_id"], "attempt_id": clip["attempt_id"]})
        for keyframe in scene["keyframes"]:
            asset = keyframe["asset"]
            relative = Path("rough-cuts/generated-clips") / _component(scene["scene_id"]) / _component(result["result_id"]) / (_component(asset["asset_id"]) + ".png")
            record = import_asset(project, asset, relative, asset_root=asset_root, deliveries=deliveries, allowed_origins=allowed_origins)
            with Image.open(project_path(project, record["local_path"])) as image:
                for key, actual in (("width", image.width), ("height", image.height)):
                    if keyframe["media"].get(key) is not None and keyframe["media"][key] != actual:
                        raise IntegrationError("Keyframe dimensions mismatch")
            records.append({**record, "scene_id": scene["scene_id"], "shot_id": keyframe["shot_id"], "position": keyframe["position"]})
    for asset in result["preview_assets"]:
        relative = Path("rough-cuts/generated-clips/previews") / _component(result["result_id"]) / (_component(asset["asset_id"]) + ".mp4")
        records.append(import_asset(project, asset, relative, asset_root=asset_root, deliveries=deliveries, allowed_origins=allowed_origins, media=asset.get("media")))
    for asset in result["reference_assets"]:
        relative = Path("assets/reference/generated") / _component(result["result_id"]) / _component(asset["asset_id"])
        records.append(import_asset(project, asset, relative, asset_root=asset_root, deliveries=deliveries, allowed_origins=allowed_origins))
    index = {"result_id": result["result_id"], "result_sha256": result["document_sha256"], "assets": records}
    immutable_write(project_path(project, Path("rough-cuts/manifests/imports") / (_component(result["result_id"]) + ".json")), canonical_bytes(index))
    store_document(project, "result", result)
    return index


def _selection_inputs(project: Path, selection: dict[str, Any]) -> dict[str, dict[str, Any]]:
    results = {}
    for reference in selection["source_results"]:
        result = load_document(project, "result", reference["result_id"])
        if result["result_id"] in results or result["document_sha256"] != reference["sha256"]:
            raise IntegrationError("Duplicate result or result hash mismatch in selection")
        if result["result_kind"] != "video":
            raise IntegrationError("A keyframe result cannot supply a video take")
        request = load_document(project, "request", result["request_id"])
        plan = load_document(project, "plan", result["plan_id"])
        approval = load_document(project, "approval", result["approval_id"])
        if approval["execution_mode"] != result["result_kind"]:
            raise IntegrationError("Result kind does not match approval execution mode")
        if request["project_id"] != selection["project_id"]:
            raise IntegrationError("Result belongs to a different project")
        if (plan["request_id"] != request["request_id"] or approval["request_id"] != request["request_id"]
                or approval["plan_id"] != plan["plan_id"] or approval["plan_sha256"] != plan["document_sha256"]):
            raise IntegrationError("Result provenance chain does not match request, plan, and approval")
        source_board = read_json(project_path(project, Path("storyboards") / (_component(request["storyboard"]["revision_id"]) + ".json")))
        if sha256(canonical_bytes(source_board)) != request["storyboard"]["sha256"]:
            raise IntegrationError("Request storyboard hash mismatch")
        index = read_json(project_path(project, Path("rough-cuts/manifests/imports") / (_component(result["result_id"]) + ".json")))
        if index["result_id"] != result["result_id"] or index["result_sha256"] != result["document_sha256"]:
            raise IntegrationError("Asset import record refers to a different result")
        results[result["result_id"]] = {"result": result, "request": request, "plan": plan, "approval": approval, "index": index}
    return results


def stale_dependencies(selection: dict[str, Any], results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    takes = {take["take_id"]: take for result in results for scene in result["scenes"] for take in scene["takes"]}
    selected = {scene["take_id"] for scene in selection["scenes"]}
    decisions = {(item["scene_id"], item["dependency_take_id"]): item for item in selection["continuity_decisions"]}
    if len(decisions) != len(selection["continuity_decisions"]):
        raise IntegrationError("Duplicate continuity decision")
    stale = []
    for scene in selection["scenes"]:
        if scene["take_id"] not in takes:
            raise IntegrationError("Selected take is missing")
        for dependency in takes[scene["take_id"]]["depends_on_take_ids"]:
            if dependency not in selected:
                decision = decisions.get((scene["scene_id"], dependency))
                stale.append({"scene_id": scene["scene_id"], "take_id": scene["take_id"],
                              "dependency_take_id": dependency, "decision": decision})
    return stale


def compile_selection(project: Path, selection: dict[str, Any], *, prepare_audio: bool = True) -> dict[str, Any]:
    """Verify the complete selection before producing any FFmpeg derivatives."""
    validate_document("selection", selection)
    inputs = _selection_inputs(project, selection)
    board = read_json(project_path(project, Path("storyboards") / (_component(selection["storyboard_revision_id"]) + ".json")))
    if board.get("approved") is not True or board["project_id"] != selection["project_id"]:
        raise IntegrationError("Selection requires this project's approved storyboard")
    storyboard_scenes = _unique(board["scenes"], "scene_id")
    takes: dict[str, tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = {}
    for entry in inputs.values():
        for result_scene in entry["result"]["scenes"]:
            for take in result_scene["takes"]:
                if take["take_id"] in takes:
                    raise IntegrationError("Ambiguous take ID across results")
                takes[take["take_id"]] = entry, result_scene, take
    selected_clips: list[dict[str, Any]] = []
    for scene in sorted(selection["scenes"], key=lambda value: value["order"]):
        board_scene = storyboard_scenes.get(scene["scene_id"])
        if not board_scene or scene["order"] != board_scene["order"]:
            raise IntegrationError("Selected scene order must match its approved storyboard")
        if scene["transition_out"]["type"] not in {"cut", "none"}:
            raise IntegrationError("Transition is unsupported by EDL version 1")
        if scene["take_id"] not in takes:
            raise IntegrationError("Selected take is missing from referenced results")
        entry, result_scene, take = takes[scene["take_id"]]
        if result_scene["scene_id"] != scene["scene_id"]:
            raise IntegrationError("Selected take belongs to a different scene")
        edits = _unique(scene["clip_edits"], "clip_id")
        _unique(scene["clip_edits"], "order")
        if set(edits) != set(take["clip_ids"]):
            raise IntegrationError("Selection must edit every clip in the selected take exactly once")
        clips = {clip["clip_id"]: clip for clip in result_scene["clips"]}
        imports = _unique([asset for asset in entry["index"]["assets"] if "clip_id" in asset], "clip_id")
        asset_imports = {asset["asset_id"]: asset for asset in entry["index"]["assets"]}
        reference_assets = {asset["asset_id"]: asset for asset in entry["result"]["reference_assets"]}
        for source_scene in entry["result"]["scenes"]:
            reference_assets.update({frame["asset"]["asset_id"]: frame["asset"] for frame in source_scene["keyframes"]})
            reference_assets.update({clip["asset"]["asset_id"]: clip["asset"] for clip in source_scene["clips"]})
        attempts = {attempt["attempt_id"]: attempt for attempt in result_scene["attempts"]}
        provider_aliases = {"fal": "fal.ai"}
        approved_shots = [(plan_scene["scene_id"], plan_scene["order"], variant, shot)
                          for plan_scene in entry["plan"]["scenes"] for variant in plan_scene["variants"]
                          if variant["variant_id"] in entry["approval"]["approved_variant_ids"]
                          for shot in variant["shots"]]
        approved_positions = {(scene_id, shot["shot_id"]): (scene_order, shot["order"])
                              for scene_id, scene_order, _, shot in approved_shots}
        frames = [(source_scene["scene_id"], frame) for source_scene in entry["result"]["scenes"]
                  for frame in source_scene["keyframes"]]
        predecessor_ids = {identifier for identifier in take["depends_on_take_ids"]
                           if identifier in takes and takes[identifier][1]["order"] < result_scene["order"]}
        predecessor_scenes = {takes[identifier][1]["scene_id"] for identifier in predecessor_ids}
        first_frame_hashes = {(asset.get("source_take_id"), asset["sha256"])
                              for asset in entry["result"]["reference_assets"] if asset["role"] == "first_frame"}
        continuity_refs = {asset["asset_id"] for asset in entry["result"]["reference_assets"]
                           if asset.get("source_take_id") in predecessor_ids and
                           (asset["role"] == "first_frame" or
                            (asset["role"] == "provider_reference" and
                             (asset["source_take_id"], asset["sha256"]) in first_frame_hashes))}
        for edit in sorted(edits.values(), key=lambda value: value["order"]):
            clip = clips[edit["clip_id"]]
            attempt = attempts[clip["attempt_id"]]
            approved_refs = [set(shot["reference_asset_ids"]) for scene_id, _, variant, shot in approved_shots
                             if scene_id == scene["scene_id"] and shot["shot_id"] == attempt["shot_id"]
                             and provider_aliases.get(variant["provider"], variant["provider"]) ==
                             provider_aliases.get(attempt["provider"], attempt["provider"])
                             and variant["model"] == attempt["model"] and shot["prompt_snapshot"] == attempt["prompt_snapshot"]]
            if not approved_refs:
                raise IntegrationError("Selected clip does not match an approved shot variant")
            shot_position = approved_positions[(scene["scene_id"], attempt["shot_id"])]
            approved_keyframes = {frame["asset"]["asset_id"] for source_scene_id, frame in frames
                                  if frame["asset"]["role"] == "keyframe"
                                  and (source_scene_id == scene["scene_id"] or source_scene_id in predecessor_scenes)
                                  and (frame_position := approved_positions.get((source_scene_id, frame["shot_id"]))) is not None
                                  and frame_position <= shot_position}
            prepared = attempt["generation_parameters"].get("prepared_reference_sources", "{}")
            try:
                prepared_sources = json.loads(prepared)
            except (TypeError, ValueError):
                raise IntegrationError("Invalid prepared reference provenance") from None
            if (not isinstance(prepared_sources, dict) or
                    any(not isinstance(key, str) or not isinstance(value, str) for key, value in prepared_sources.items()) or
                    set(prepared_sources) - set(attempt["reference_asset_ids"])):
                raise IntegrationError("Invalid prepared reference provenance")
            authorized = False
            for refs in approved_refs:
                allowed = refs | approved_keyframes | continuity_refs
                allowed |= {identifier for identifier, source in prepared_sources.items()
                            if source in allowed and source in reference_assets
                            and reference_assets.get(identifier, {}).get("role") == "provider_reference"}
                if set(attempt["reference_asset_ids"]) <= allowed:
                    authorized = True
                    break
            if not authorized:
                raise IntegrationError("Selected clip used unapproved reference assets")
            imported = imports.get(clip["clip_id"])
            if not imported or imported["sha256"] != clip["asset"]["sha256"] or imported["source_uri"] != clip["asset"]["uri"]:
                raise IntegrationError("Missing or mismatched clip import")
            local = project_path(project, imported["local_path"])
            if file_hash(local) != clip["asset"]["sha256"]:
                raise IntegrationError("Imported clip SHA-256 mismatch")
            measured = probe_media(local)
            _compare_media(clip["media"], measured)
            start, end = edit["trim_in_s"], edit["trim_out_s"]
            if not 0 <= start < end <= measured["measured_duration_s"]:
                raise IntegrationError("Editorial trims exceed measured clip duration")
            nominal = clip["media"].get("measured_duration_s")
            if nominal is not None and end > nominal:
                raise IntegrationError("Editorial trim exceeds declared measured duration")
            provenance = {"scene_id": scene["scene_id"], "take_id": take["take_id"], "clip_id": clip["clip_id"],
                          "attempt_id": clip["attempt_id"], "asset_id": clip["asset"]["asset_id"],
                          "asset_sha256": clip["asset"]["sha256"], "source_uri": clip["asset"]["uri"],
                          "attempt": attempts[clip["attempt_id"]], "audio_use": edit["audio_use"]}
            provenance["reference_assets"] = []
            for identifier in provenance["attempt"]["reference_asset_ids"]:
                reference_asset = reference_assets.get(identifier)
                reference_import = asset_imports.get(identifier)
                if not reference_asset or not reference_import:
                    raise IntegrationError("Provider attempt references a missing imported asset")
                if file_hash(project_path(project, reference_import["local_path"])) != reference_asset["sha256"]:
                    raise IntegrationError("Provider reference asset hash mismatch")
                provenance["reference_assets"].append({**reference_asset, "local_path": reference_import["local_path"]})
            for kind in ("request", "plan", "approval", "result"):
                provenance[kind + "_id"] = entry[kind][DOCUMENTS[kind][0]]
                provenance[kind + "_sha256"] = entry[kind]["document_sha256"]
            selected_clips.append({"path": local, "edit": edit, "media": measured, "provenance": provenance})
    stale = stale_dependencies(selection, [entry["result"] for entry in inputs.values()])
    for item in stale:
        decision = item["decision"]
        if decision is None or decision["decision"] == "regenerate":
            raise IntegrationError("Stale continuity dependency needs an explicit accept or boundary decision")
        if decision["decision"] == "use_boundary":
            asset = decision["replacement_asset"]
            if asset is None:
                raise IntegrationError("Boundary decision requires an imported replacement asset")
            if not asset["mime_type"].startswith("image/"):
                raise IntegrationError("A replacement boundary must be an image")
            if asset.get("source_take_id") and asset["source_take_id"] not in {scene["take_id"] for scene in selection["scenes"]}:
                raise IntegrationError("Replacement boundary refers to an unselected take")
            entry, dependent_scene, dependent_take = takes[item["take_id"]]
            first_clip_id = min(dependent_take["clip_order"], key=dependent_take["clip_order"].get)
            first_clip = next(clip for clip in dependent_scene["clips"] if clip["clip_id"] == first_clip_id)
            first_attempt = next(attempt for attempt in dependent_scene["attempts"] if attempt["attempt_id"] == first_clip["attempt_id"])
            consumed = {frame["asset"]["sha256"] for frame in dependent_scene["keyframes"]
                        if frame["position"] == "first" and frame["asset"]["asset_id"] in first_attempt["reference_asset_ids"]}
            consumed.update(reference["sha256"] for reference in entry["result"]["reference_assets"]
                            if reference["role"] == "first_frame" and reference["asset_id"] in first_attempt["reference_asset_ids"])
            if asset["sha256"] not in consumed:
                raise IntegrationError("Compatible boundary must match the dependent take's consumed first frame; otherwise regenerate it")
            boundary = project_path(project, Path("rough-cuts/manifests/boundaries") / (_component(asset["asset_id"]) + ".json"))
            record = read_json(boundary)
            if record["source_uri"] != asset["uri"] or file_hash(project_path(project, record["local_path"])) != asset["sha256"]:
                raise IntegrationError("Replacement boundary hash mismatch")
    # The existing concat renderer requires equal geometry, fps and audio topology.
    formats = {(clip["media"]["width"] / clip["media"]["height"], round(clip["media"]["fps"], 3)) for clip in selected_clips}
    if len(formats) != 1:
        raise IntegrationError("Selected clips require matching aspect ratios and frame rates for EDL concat")
    needs_audio = any(clip["media"]["has_audio"] and clip["edit"]["audio_use"] == "preserve" for clip in selected_clips)
    sources: dict[str, str] = {}
    ranges = []
    provenance_sources = {}
    total_duration = 0.0
    for position, clip in enumerate(selected_clips):
        name = "generated_" + str(position)
        local = clip["path"]
        media, edit, provenance = clip["media"], clip["edit"], clip["provenance"]
        if edit["audio_use"] == "mute" or (needs_audio and not media["has_audio"]):
            local = _audio_source(project, local, provenance["asset_sha256"], media, needs_audio, prepare_audio)
            provenance["derived_asset_sha256"] = file_hash(local) if local.exists() else None
        sources[name] = str(local)
        start, end = edit["trim_in_s"], edit["trim_out_s"]
        ranges.append({"source": name, "start": start, "end": end, "beat": provenance["scene_id"]})
        padded_start, padded_end = apply_padding(start, end, source_duration=media["measured_duration_s"])
        total_duration += padded_end - padded_start
        provenance_sources[name] = {**provenance, "local_path": str(local.relative_to(project.resolve())),
                                    "trim_in_s": start, "trim_out_s": end,
                                    "padded_in_s": padded_start, "padded_out_s": padded_end}
    edl: dict[str, Any] = {"version": EDL_VERSION, "sources": sources, "ranges": ranges, "total_duration_s": total_duration,
           "generated_media": {"edit_revision_id": selection["edit_revision_id"],
                               "storyboard_sha256": sha256(canonical_bytes(board)),
                               "sources": provenance_sources, "stale_dependencies": stale}}
    if selection.get("edl"):
        stored = read_json(project_path(project, selection["edl"]["path"]))
        if sha256(canonical_bytes(stored)) != selection["edl"]["sha256"]:
            raise IntegrationError("Stored EDL hash mismatch")
        for key in ("grade", "overlays", "subtitles"):
            if key in stored:
                edl[key] = stored[key]
        edl["generated_media"]["editorial_assets"] = _editorial_assets(project, edl)
    validate_edl(edl)
    return edl


def _editorial_assets(project: Path, edl: dict[str, Any]) -> list[dict[str, str]]:
    paths = [overlay["source"] for overlay in edl.get("overlays", []) if isinstance(overlay.get("source"), str)]
    subtitles = edl.get("subtitles")
    if isinstance(subtitles, str):
        paths.append(subtitles)
    elif isinstance(subtitles, dict) and subtitles.get("path"):
        paths.append(subtitles["path"])
    return [{"path": str(project_path(project, path)), "sha256": file_hash(project_path(project, path))} for path in sorted(set(paths))]


def _audio_source(project: Path, source: Path, digest: str, media: dict[str, Any], needs_audio: bool, prepare: bool) -> Path:
    suffix = "silent" if needs_audio else "mute"
    destination = project_path(project, Path("rough-cuts/generated-clips/derived") / (digest.removeprefix("sha256:") + "-" + suffix + ".mp4"))
    record_path = destination.with_suffix(".json")
    if destination.exists():
        if not record_path.exists():
            raise IntegrationError("Audio derivative has no provenance record")
        record = read_json(record_path)
        if record["source_sha256"] != digest or record["output_sha256"] != file_hash(destination):
            raise IntegrationError("Audio derivative hash mismatch")
        return destination
    if not prepare:
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temp:
        output = Path(temp) / "derived.mp4"
        command = ["ffmpeg", "-v", "error", "-nostdin", "-i", str(source)]
        if needs_audio:
            command += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-t", str(media["measured_duration_s"])]
        else:
            command += ["-map", "0:v:0", "-c:v", "copy", "-an"]
        subprocess.run([*command, "-movflags", "+faststart", str(output)], check=True, capture_output=True)
        try:
            os.link(output, destination)
        except FileExistsError:
            if file_hash(destination) != file_hash(output):
                raise IntegrationError("Conflicting audio derivative") from None
    immutable_write(record_path, canonical_bytes({"source_sha256": digest, "output_sha256": file_hash(destination), "audio": suffix}))
    return destination


def write_selection(project: Path, draft: dict[str, Any], *, edl_options: dict[str, Any] | None = None) -> dict[str, Any]:
    """Commit an editorial revision and the exact EDL together after validation."""
    selection = seal({"contract_version": CONTRACT_VERSION, "selection_version": 1,
                      "created_at": now(), "continuity_decisions": [], "edl": None, **draft})
    edl = compile_selection(project, selection)
    if edl_options:
        if set(edl_options) - {"grade", "overlays", "subtitles"}:
            raise IntegrationError("EDL options support grade, overlays and subtitles")
        options = copy.deepcopy(edl_options)
        for overlay in options.get("overlays", []):
            if isinstance(overlay.get("source"), str):
                overlay["source"] = str(project_path(project, overlay["source"]))
        subtitles = options.get("subtitles")
        if isinstance(subtitles, str):
            options["subtitles"] = str(project_path(project, subtitles))
        elif isinstance(subtitles, dict) and subtitles.get("path"):
            subtitles["path"] = str(project_path(project, subtitles["path"]))
        edl.update(options)
        validate_edl(edl)
    edl["generated_media"]["editorial_assets"] = _editorial_assets(project, edl)
    relative = Path("edit") / ("edl-" + _component(selection["edit_revision_id"]) + ".json")
    selection["edl"] = {"path": str(relative), "sha256": sha256(canonical_bytes(edl))}
    selection = seal(selection)
    validate_document("selection", selection)
    # Check identity conflicts before creating either revision file.
    selection_path = document_path(project, "selection", selection["edit_revision_id"])
    if selection_path.exists() and selection_path.read_bytes() != canonical_bytes(selection):
        raise IntegrationError("Selection revision already exists; use a new edit_revision_id")
    immutable_write(project_path(project, relative), canonical_bytes(edl))
    store_document(project, "selection", selection)
    return selection


def render_selection(project: Path, selection: dict[str, Any], *, preview: bool = False, no_loudnorm: bool = False) -> dict[str, Any]:
    edl = compile_selection(project, selection)
    reference = selection["edl"]
    if reference is None or sha256(canonical_bytes(edl)) != reference["sha256"]:
        raise IntegrationError("Compiled EDL no longer matches the immutable selection")
    edl_path = project_path(project, reference["path"])
    if file_hash(edl_path) != reference["sha256"]:
        raise IntegrationError("EDL file hash mismatch")
    revision = _component(selection["edit_revision_id"])
    output = project_path(project, Path("edit") / (revision + ("-preview" if preview else "-final") + ".mp4"))
    record_path = project_path(project, Path("edit") / ("render-" + output.stem + ".json"))
    if record_path.exists():
        record = read_json(record_path)
        if (record["selection_sha256"] != selection["document_sha256"] or file_hash(output) != record["output_sha256"]
                or record["no_loudnorm"] != no_loudnorm or document_hash(record) != record["document_sha256"]
                or file_hash(project_path(project, record["verification_path"])) != record["verification_sha256"]):
            raise IntegrationError("Existing render record or output changed")
        return record
    if output.exists():
        raise IntegrationError("Unrecorded output already exists; choose a new revision")
    # Renderer scratch files are isolated per render; its implementation stays unchanged.
    with tempfile.TemporaryDirectory(dir=project_path(project, "edit")) as scratch:
        render_edl_path = Path(scratch) / edl_path.name
        render_edl_path.write_bytes(canonical_bytes(edl))
        temp_output = Path(scratch) / output.name
        if render_edl(render_edl_path, temp_output, preview=preview, no_loudnorm=no_loudnorm) != 0:
            raise IntegrationError("Existing EDL renderer failed")
        report = run_verification(temp_output, edl, output_dir=project_path(project, Path("edit/verify") / output.stem), max_passes=1)
        report.video, report.edl = str(output), str(edl_path)
        verification = report.to_dict()
        verification_path = project_path(project, Path("edit") / ("verification-" + output.stem + ".json"))
        immutable_write(verification_path, canonical_bytes(verification))
        os.link(temp_output, output)
    record = seal({"edit_revision_id": selection["edit_revision_id"], "created_at": now(),
                   "selection_sha256": selection["document_sha256"], "edl": reference,
                   "output_path": str(output.relative_to(project.resolve())), "output_sha256": file_hash(output),
                   "verification_path": str(verification_path.relative_to(project.resolve())),
                   "verification_sha256": file_hash(verification_path), "passed": report.passed,
                   "preview": preview, "no_loudnorm": no_loudnorm, "provenance": edl["generated_media"],
                   "ffmpeg_version": subprocess.run(["ffmpeg", "-version"], check=True, capture_output=True, text=True).stdout.splitlines()[0]})
    immutable_write(record_path, canonical_bytes(record))
    return record


def cost_rollup(project: Path, selection: dict[str, Any] | None = None) -> dict[str, Any]:
    selected: set[tuple[str, str]] = set()
    if selection is not None:
        validate_document("selection", selection)
        inputs = _selection_inputs(project, selection)
        for scene in selection["scenes"]:
            matches = [(result_id, take["take_id"]) for result_id, entry in inputs.items()
                       for result_scene in entry["result"]["scenes"] if result_scene["scene_id"] == scene["scene_id"]
                       for take in result_scene["takes"] if take["take_id"] == scene["take_id"]]
            if len(matches) != 1:
                raise IntegrationError("Selected take is missing or ambiguous in referenced results")
            selected.add(matches[0])
    observations: dict[str, dict[str, Any]] = {}
    for path in sorted(project_path(project, "rough-cuts/manifests/results").glob("*.json")):
        result = read_json(path)
        validate_document("result", result)
        for scene in result["scenes"]:
            selected_clips = {clip_id for take in scene["takes"] if (result["result_id"], take["take_id"]) in selected for clip_id in take["clip_ids"]}
            selected_attempts = {clip["attempt_id"] for clip in scene["clips"] if clip["clip_id"] in selected_clips}
            for attempt in scene["attempts"]:
                row = {"attempt_id": attempt["attempt_id"], "result_id": result["result_id"],
                       "scene_id": scene["scene_id"], "provider": attempt["provider"], "model": attempt["model"],
                       "selected_output": attempt["attempt_id"] in selected_attempts, **attempt["billing"]}
                if attempt["attempt_id"] in observations and observations[attempt["attempt_id"]] != row:
                    raise IntegrationError("Conflicting billing observations for one attempt")
                observations[attempt["attempt_id"]] = row

    def totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
        sums = {}
        for key in ("estimated_usd", "actual_usd"):
            known = sum((Decimal(str(row[key])) for row in rows if row[key] is not None), Decimal(0))
            unknown = sum(row[key] is None for row in rows)
            sums[key] = {"total": None if unknown else float(known), "known_subtotal": float(known), "unknown_attempts": unknown, "currency": "USD"}
        return sums

    rows = list(observations.values())
    return {"attempts": rows, "all_attempts": totals(rows),
            "selected_outputs": totals([row for row in rows if row["selected_output"]]),
            "unselected_attempts": totals([row for row in rows if not row["selected_output"]])}


def regenerate(
    project: Path, storyboard: dict[str, Any], selection: dict[str, Any], scene_ids: list[str],
    *, reason: str, request_id: str | None = None, revision: int = 1,
) -> dict[str, Any]:
    validate_document("selection", selection)
    if storyboard.get("project_id") != selection["project_id"]:
        raise IntegrationError("Regeneration storyboard belongs to a different project")
    inputs = _selection_inputs(project, selection)
    selected = {scene["scene_id"]: scene["take_id"] for scene in selection["scenes"]}
    if not scene_ids or set(scene_ids) - selected.keys():
        raise IntegrationError("Regeneration targets must be selected scenes")
    replaced = [selected[scene_id] for scene_id in scene_ids]
    base_results = [entry["result"]["result_id"] for entry in inputs.values()
                    if any(take["take_id"] in replaced for scene in entry["result"]["scenes"] for take in scene["takes"])]
    prior_requests = {inputs[result_id]["request"]["request_id"] for result_id in base_results}
    return build_request(project, storyboard, scene_ids=scene_ids, request_id=request_id, revision=revision,
                         supersedes_request_id=next(iter(prior_requests)) if len(prior_requests) == 1 else None,
                         regeneration={"base_result_ids": base_results, "supersedes_take_ids": replaced, "reason": reason})


def send_document(
    project: Path, kind: str, document: dict[str, Any], *, server: str | None = None,
    handoff: Path | None = None, token: str | None = None,
) -> dict[str, Any]:
    if kind not in {"request", "approval"}:
        raise IntegrationError("Send accepts request or approval documents")
    store_document(project, kind, document)
    if (server is None) == (handoff is None):
        raise IntegrationError("Choose exactly one HTTP server or file handoff directory")
    if handoff is not None:
        relative = Path(DOCUMENTS[kind][1]) / (_component(document[DOCUMENTS[kind][0]]) + ".json")
        destination = project_path(handoff, relative)
        immutable_write(destination, canonical_bytes(document))
        return {"handoff_path": str(destination), "document_sha256": document["document_sha256"]}
    response = http_document(server or "", "/v2/plans" if kind == "request" else "/v2/jobs", document=document, token=token)
    if kind == "request":
        if response.get("request_id") != document["request_id"]:
            raise IntegrationError("Server returned a plan for a different request")
        store_document(project, "plan", response)
    else:
        reject_secrets(response)
        if response.get("approval_id") != document["approval_id"]:
            raise IntegrationError("Server returned a job for a different approval")
    return response


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="command", required=True)
    request = sub.add_parser("request", help="Write an immutable request from an approved storyboard")
    request.add_argument("storyboard", type=Path)
    request.add_argument("--scene", action="append")
    request.add_argument("--id")
    request.add_argument("--revision", type=int, default=1)
    request.add_argument("--supersedes")
    approve = sub.add_parser("approve", help="Record approval of an exact reviewed plan")
    approve.add_argument("plan", type=Path)
    approve.add_argument("--variant", action="append", required=True)
    approve.add_argument("--mode", choices=("video", "keyframes"), default="video")
    approve.add_argument("--id")
    approve.add_argument("--key")
    approve.add_argument("--keyframes")
    approve.add_argument("--allow-unknown-cost", action="store_true")
    approve.add_argument("--budget-usd", type=float)
    send = sub.add_parser("send", help="Submit exact request/approval bytes over HTTP or files")
    send.add_argument("kind", choices=("request", "approval"))
    send.add_argument("document", type=Path)
    transport = send.add_mutually_exclusive_group(required=True)
    transport.add_argument("--server")
    transport.add_argument("--handoff", type=Path)
    send.add_argument("--token-env")
    get = sub.add_parser("get", help="Read capabilities, plan, job, or terminal result over HTTP")
    get.add_argument("kind", choices=("capabilities", "plan", "job", "result", "cancel"))
    get.add_argument("--id")
    get.add_argument("--server", required=True)
    get.add_argument("--token-env")
    get.add_argument("--output", type=Path)
    validate = sub.add_parser("validate", help="Validate the pinned contract and canonical hash")
    validate.add_argument("kind", choices=DOCUMENTS)
    validate.add_argument("document", type=Path)
    ingest = sub.add_parser("import", help="Verify and import a document and its media assets")
    ingest.add_argument("kind", choices=(*DOCUMENTS, "boundary"))
    ingest.add_argument("document", type=Path)
    ingest.add_argument("--asset-root", type=Path)
    ingest.add_argument("--deliveries", type=Path, help="Transient mapping of durable URI to local path or signed delivery URL")
    ingest.add_argument("--allow-origin", action="append")
    select = sub.add_parser("select", help="Validate a selection draft, compile EDL, and freeze both")
    select.add_argument("draft", type=Path)
    select.add_argument("--edl-options", type=Path, help="Existing EDL grade, overlays and subtitle settings")
    render = sub.add_parser("render", help="Revalidate, render through existing EDL pipeline, and verify")
    render.add_argument("selection", type=Path)
    render.add_argument("--preview", action="store_true")
    render.add_argument("--no-loudnorm", action="store_true", help="Use the existing renderer's normalization bypass for silent media")
    inspect = sub.add_parser("inspect", help="Show stale dependencies in a selection draft")
    inspect.add_argument("selection", type=Path)
    cost = sub.add_parser("cost", help="Roll up all attempts, selected outputs, and raw units")
    cost.add_argument("--selection", type=Path)
    regen = sub.add_parser("regenerate", help="Request replacements for only the named selected scenes")
    regen.add_argument("storyboard", type=Path)
    regen.add_argument("selection", type=Path)
    regen.add_argument("--scene", action="append", required=True)
    regen.add_argument("--reason", required=True)
    regen.add_argument("--id")
    regen.add_argument("--revision", type=int, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    project = args.project.resolve()
    try:
        result: dict[str, Any]
        if args.command == "request":
            result = build_request(project, read_json(args.storyboard), scene_ids=args.scene, request_id=args.id, revision=args.revision, supersedes_request_id=args.supersedes)
        elif args.command == "approve":
            result = approve_plan(project, read_json(args.plan), args.variant, execution_mode=args.mode, approval_id=args.id,
                                  idempotency_key=args.key, keyframe_result_id=args.keyframes,
                                  allow_unknown_cost=args.allow_unknown_cost, max_estimated_cost_usd=args.budget_usd)
        elif args.command == "send":
            result = send_document(project, args.kind, read_json(args.document), server=args.server, handoff=args.handoff,
                                   token=os.environ.get(args.token_env) if args.token_env else None)
        elif args.command == "get":
            if args.kind != "capabilities" and not args.id:
                raise IntegrationError("This operation requires --id")
            identifier = quote(args.id or "", safe="")
            path = {"capabilities": "/v2/capabilities", "plan": "/v2/plans/" + identifier,
                    "job": "/v2/jobs/" + identifier, "result": "/v2/jobs/" + identifier + "/result",
                    "cancel": "/v2/jobs/" + identifier + "/cancel"}[args.kind]
            result = http_document(args.server, path, token=os.environ.get(args.token_env) if args.token_env else None,
                                   method="POST" if args.kind == "cancel" else "GET")
            if args.kind in {"plan", "result"}:
                validate_document(args.kind, result)
                id_field = "plan_id" if args.kind == "plan" else "job_id"
                if result[id_field] != args.id:
                    raise IntegrationError("Server returned a different artifact identity")
            reject_secrets(result)
            if args.output:
                immutable_write(project_path(project, args.output), canonical_bytes(result))
            if args.kind == "plan":
                store_document(project, "plan", result)
        elif args.command == "validate":
            validate_document(args.kind, read_json(args.document))
            result = {"valid": True, "contract_version": CONTRACT_VERSION}
        elif args.command == "import":
            document = read_json(args.document)
            deliveries = read_json(args.deliveries) if args.deliveries else None
            if args.kind == "result":
                result = import_result(project, document, asset_root=args.asset_root, deliveries=deliveries, allowed_origins=args.allow_origin)
            elif args.kind == "boundary":
                relative = Path("assets/reference/boundaries") / _component(document["asset_id"])
                result = import_asset(project, document, relative, asset_root=args.asset_root, deliveries=deliveries, allowed_origins=args.allow_origin)
                immutable_write(project_path(project, Path("rough-cuts/manifests/boundaries") / (_component(document["asset_id"]) + ".json")), canonical_bytes(result))
            else:
                result = {"path": str(store_document(project, args.kind, document))}
        elif args.command == "select":
            result = write_selection(project, read_json(args.draft), edl_options=read_json(args.edl_options) if args.edl_options else None)
        elif args.command == "render":
            result = render_selection(project, read_json(args.selection), preview=args.preview, no_loudnorm=args.no_loudnorm)
        elif args.command == "inspect":
            selection = read_json(args.selection)
            results = [load_document(project, "result", ref["result_id"]) for ref in selection["source_results"]]
            result = {"stale_dependencies": stale_dependencies(selection, results)}
        elif args.command == "regenerate":
            result = regenerate(project, read_json(args.storyboard), read_json(args.selection), args.scene, reason=args.reason, request_id=args.id, revision=args.revision)
        else:
            result = cost_rollup(project, read_json(args.selection) if args.selection else None)
        print(canonical_bytes(result).decode())
        return 1 if args.command == "render" and not result["passed"] else 0
    except (IntegrationError, OSError, json.JSONDecodeError, KeyError, TypeError, subprocess.CalledProcessError) as exc:
        # Untrusted provider output or transport details may contain secrets.
        message = str(exc) if isinstance(exc, IntegrationError) else type(exc).__name__
        print("media-generated: " + message, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
