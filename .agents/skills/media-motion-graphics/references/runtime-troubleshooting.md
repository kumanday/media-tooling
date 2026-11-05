# Agent runtime and tool lookup

## Locate the installed Python implementation

Start with `command -v media-generated`. For a uv tool install, use its own
interpreter to locate the imported implementation:

```sh
media_tool_python="$(uv tool dir)/media-tooling/bin/python"
"$media_tool_python" -c 'import media_tooling.generated_media as m; print(m.__file__)'
```

Scope `rg` searches to the printed file or its source directory. In an editable
install the Python code lives in the checkout; `site-packages` can contain the
packaged skills without a copied implementation. `generated_media.py` is a file.
A failed import from system `python3` says nothing about the isolated CLI's
environment. For other installation methods, inspect the launcher's shebang and
use that interpreter. Whole-filesystem `find /` and recursive searches from `/`
are unnecessary for this lookup.

Selection input and output paths differ: write a draft under
`rough-cuts/manifests/drafts/` and pass it to `media-generated select`. The CLI
writes `rough-cuts/manifests/selections/<id>.json` and `edit/edl-<id>.json`.
If the draft already occupies its output path, even a new ID produces a revision
collision. Preserve sealed outputs; changed edits need a new ID.

## Pi sessions

Pi 1.1.0 discovers the shared `~/.agents/skills/` store populated by
`media-tooling-link-skills`. Run `/reload` after an edit. Discovery adds names,
descriptions and paths; it does not read the skill's full instructions. Use
`/skill:media-motion-graphics` to load this skill explicitly, then follow its
reference routing. A custom launcher that disables skill discovery must supply
the skill paths explicitly. Inspect the loaded paths for an older duplicate
before reinstalling anything.

Use the tool schema supplied by the running harness. Pi 1.1.0's edit call is:

```json
{"path":"file.md","edits":[{"oldText":"exact match","newText":"replacement"}]}
```

After a validation failure, correct the call and verify the file. A rejected
edit has not changed the artifact.

For multimodal review, respect the selected provider's limit over the entire
outgoing request, including images retained in conversation history. The Nebius
Nemotron 3.5 Super VL route tested here accepts at most eight images per request.
Reading one new image can exceed that limit after earlier reviews. Save findings
as text and preserve images on disk. Use a provider adapter that bounds outgoing
images with explicit omission markers, or resume in a fresh session from saved
artifact paths and a compact handoff. Small review batches alone do not bound
the accumulated history.

Distinguish a provider request error from a failed local tool. Preserve the last
successful artifacts and command results. For a request-processing error, retry
the model continuation or a read-only probe before repeating generation or
rendering. Inspect paid-job receipts and terminal status before resubmission.
An unchanged image-limit rejection needs a smaller payload, not another retry.
