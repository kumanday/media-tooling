# Generated media with TTV

Media Tooling owns the editorial storyboard, take selection and final EDL. TTV owns provider planning and generation. `media-generated` exchanges immutable contract 1.0 JSON documents through files or HTTP. Install with `uv sync --group dev`; FFmpeg and ffprobe must be on PATH.

Start in a project created by `media-tooling-init`. An approved storyboard JSON has `project_id`, `revision_id`, `approved: true` and `scenes`. Each scene uses the `GenerationRequest.scenes` shape in the [pinned schema](../src/media_tooling/contracts/v1_0/GenerationRequest.schema.json). Keep scene IDs stable across revisions and give each scene an explicit, unique `order`. A request for a subset preserves these values.

```sh
media-generated --project /path/to/project request storyboard.json \
  --id request-1 --revision 1
media-generated --project /path/to/project send request \
  /path/to/project/rough-cuts/manifests/requests/request-1.json \
  --server https://ttv.example.com
```

Planning returns a stored plan. Review its prompts, shot count, duration, provider variants, continuity and costs before approving execution:

```sh
media-generated --project /path/to/project approve plan.json \
  --id approval-1 --key approval-1 --variant PRIMARY_VARIANT_ID \
  --variant APPROVED_FALLBACK_VARIANT_ID --budget-usd 20
media-generated --project /path/to/project send approval \
  /path/to/project/rough-cuts/manifests/approvals/approval-1.json \
  --server https://ttv.example.com
```

Every scene needs an approved variant. Include a fallback only when its shot plan has been reviewed. Unknown estimates require `--allow-unknown-cost`; zero remains a known amount. Retry submissions by resending the stored approval, preserving its ID, key and canonical bytes. TTV owns paid-work deduplication and budget enforcement. Use `approve --mode keyframes` for keyframe review, import its result, then create a video approval with `--keyframes KEYFRAME_RESULT_ID`. Prompt changes require a new request and plan.

HTTP commands accept `--token-env VARIABLE_NAME`; the token remains in process memory. Remote endpoints require HTTPS; localhost HTTP supports development. Redirects require an explicit new endpoint.

```sh
media-generated get job --id JOB_ID --server https://ttv.example.com
media-generated --project /path/to/project get result --id JOB_ID \
  --server https://ttv.example.com --output rough-cuts/manifests/result-download.json
media-generated get cancel --id JOB_ID --server https://ttv.example.com
```

For file handoff, replace `--server` on `send` with `--handoff /path/to/exchange`. It writes identical canonical request or approval bytes. Run TTV's file adapter against these documents, then import the plan or terminal result. The repositories share schemas and documents as data.

```sh
media-generated --project /path/to/project import plan plan.json
media-generated --project /path/to/project import result result.json \
  --asset-root /path/to/ttv/output
```

Local file URIs must resolve beneath the explicit asset root. For durable `gs://` or `s3://` URIs, pass `--deliveries deliveries.json`, a transient mapping from each durable URI to a local path or download URL. HTTPS downloads also require `--allow-origin https://storage.example.com`. Signed URLs belong only in this mapping. The importer stores canonical source URIs, local paths, content hashes and measured properties. It verifies clips, keyframes and references before committing the result import. Source files remain untouched.

Create a selection draft naming the reviewed takes. Include every clip exactly once, with explicit edit order and source in/out points. `trim_out_s` is the exclusive source out-point. The take's `clip_order` supplies its generated sequence; edit order expresses the reviewed editorial sequence.

```json
{
  "edit_revision_id": "edit-1",
  "project_id": "my-film",
  "storyboard_revision_id": "storyboard-1",
  "source_results": [{"result_id": "RESULT_ID", "sha256": "sha256:RESULT_HASH"}],
  "scenes": [{
    "scene_id": "scene-1", "order": 1, "take_id": "TAKE_ID",
    "transition_out": {"type": "cut", "editorial_note": null},
    "clip_edits": [{
      "clip_id": "CLIP_ID", "order": 0,
      "trim_in_s": 0, "trim_out_s": 3, "audio_use": "preserve"
    }]
  }],
  "continuity_decisions": []
}
```

```sh
media-generated --project /path/to/project select selection-draft.json
media-generated --project /path/to/project render \
  /path/to/project/rough-cuts/manifests/selections/edit-1.json --preview
```

`select` writes the immutable selection and ordinary EDL. It verifies request, plan, approval, result, storyboard and asset hashes; checks take membership, order, duration bounds and continuity; then expands clips into EDL sources and ranges. `render` repeats these checks before calling the existing renderer and `media-verify`. Render records include hashes, source and attempt provenance, reference assets, options and FFmpeg version. A failed verification remains a recorded result and returns a nonzero status.

Pass `select --edl-options options.json` for existing EDL `grade`, `subtitles` and `overlays` settings. Their paths resolve inside the project. Changing settings creates a new selection and EDL revision. Generated clips can also be ordinary sources in other EDL projects.

Contract 1.0 supports `cut` and `none` transitions and `preserve` or `mute` audio. Muting creates a derived copy. Clips without audio receive silence when other clips preserve audio. The existing concat renderer requires matching aspect ratios and frame rates; incompatible selections fail before rendering. Its 30 ms cut padding remains active. Provenance records requested and padded bounds, clamped to source duration. For completely silent audio, pass `render --no-loudnorm` to use the existing normalization bypass; this choice is recorded.

Regenerate only selected scenes that need replacement:

```sh
media-generated --project /path/to/project regenerate storyboard.json selection.json \
  --scene scene-2 --reason 'Revised product screen' --id request-2 --revision 2
```

Send and approve the request, then import its result. A new selection combines the replacement with unchanged takes from older results. Include every referenced result ID and hash. Historical documents remain immutable.

`media-generated inspect selection-draft.json` reports stale continuity dependencies. Each stale dependency needs an explicit `continuity_decisions` record: `scene_id`, `dependency_take_id`, `decision` and nullable `replacement_asset`. `accept_stale` records editorial acceptance. `use_boundary` requires an image AssetRef imported with `import boundary` whose hash matches the first frame consumed by the dependent take; its optional `source_take_id` must name a selected take. A different boundary requires regenerating the dependent scene. `regenerate` keeps compilation blocked until a replacement is selected. Decisions document compatibility judgments without altering historical generation.

`media-generated cost --selection selection.json` reports all attempts, selected successful outputs and unselected attempts. USD subtotals carry unknown-attempt counts; incomplete totals remain null. Raw provider units stay separate per attempt.

## Verification

The five schemas, raw-byte hash manifest and shared fixtures are vendored under `src/media_tooling/contracts/v1_0`. Runtime validation pins the version and manifest hash, rejects unknown fields and verifies canonical document hashes. Updating the contract requires replacing the bundle and deliberately updating the pin. `media-generated validate KIND FILE` validates a handoff independently.

Run `bash scripts/check.sh` for unittest, ruff and mypy. New tests exercise real FFmpeg import/render when installed, contract parity, safe paths, tampering, bounds, order, billing and regeneration. Consume TTV's emitted offline pilot without importing its runtime:

```sh
uv run python scripts/ttv_offline_acceptance.py \
  --handoff /path/to/ttv-pilot/handoff \
  --asset-root /path/to/ttv-pilot \
  --project /path/to/fresh-media-pilot
```

### Live validation status (2026-09-22)

The primary provider profile is MiniMax H3 Max through TTV's production `FalGenerator`, using `minimax/h3-max/image-to-video`: a supplied first frame, 5 seconds, `768P`, seed 42, safety checking enabled, prompt expansion disabled, one attempt and no fallback. The live submission returned HTTP 403 because the Fal account balance was exhausted. It produced no provider request ID or clip. Media Tooling validated and imported the immutable failed request/plan/approval/result chain; H3 Max rendering remains unverified until a funded account produces a clip.

Two separate acceptance checks passed:

- A local Hypercorn API, Redis and RQ SpawnWorker executed the shipped `media-generated` HTTP client with deterministic providers. Three scenes produced 1, 3 and 1 clips, including a recorded failure and approved fallback. Duplicate approvals before and after completion returned the same job. Both the original edit and a middle-scene replacement rendered and passed verification. Unchanged outer takes retained their IDs and hashes; the stale downstream dependency blocked compilation until explicitly accepted.
- A secondary real Google `veo-3.1-generate-preview` submission produced one 4-second, 1280×720, 24 fps clip. Its complete producer chain imported without provider-specific consumer changes. The existing EDL renderer produced a 1920×1080, 24 fps preview with 4 seconds of video; `media-verify` passed with no blocking findings. The silent audio track required the documented `--no-loudnorm` option.

The consumer gate passed 696 unittest tests, ruff and mypy. A fresh 22-case cross-repository contract corpus agreed on all outcomes (7 accepted, 15 rejected), and all vendored schema and fixture JSON bytes matched the producer bundle. These checks cover local services and provider calls; they do not establish production deployment.

To verify a successful provider result, retain the approved storyboard and request/plan/approval documents in the project, then use the same provider-independent commands:

```sh
media-generated --project /path/to/project get result --id JOB_ID \
  --server https://ttv.example.com --token-env TTV_TOKEN \
  --output rough-cuts/manifests/result-download.json
media-generated --project /path/to/project import result \
  /path/to/project/rough-cuts/manifests/result-download.json \
  --asset-root /path/to/ttv/output
media-generated --project /path/to/project select /path/to/selection-draft.json
media-generated --project /path/to/project render \
  /path/to/project/rough-cuts/manifests/selections/edit-1.json --preview --no-loudnorm
media-verify /path/to/project/edit/edit-1-preview.mp4 \
  --edl /path/to/project/edit/edl-edit-1.json --no-timelines --max-passes 1 --json
```

Use `--no-loudnorm` for silent media; omit it when normalization is desired. The blocked H3 result has no selectable take and cannot substantiate a render check.
