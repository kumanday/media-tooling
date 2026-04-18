{{MANAGED_BLOCK_START}}
# Media Tooling Project Context

Treat this directory as `$PROJECT_DIR` and keep project artifacts inside it.

Read these central media-tooling skills before routing media-processing work:
{{SKILL_PATHS}}

Use installed toolkit commands from this project directory:
- spoken media: `media-subtitle` or `media-batch-subtitle`
- silent or visual-first video: `media-contact-sheet` or `media-batch-contact-sheet`
- rough-cut assembly: `media-rough-cut`

Operational defaults:
- use sequential processing to reduce resource contention. Have patience for long media jobs
- use `--skip-existing` for resumable batches
- re-run `media-tooling-init` after reinstalling or relocating the toolkit so these skill paths stay current

## Session Memory Protocol

Persist strategy, decisions, and reasoning across sessions in `edit/project.md`.

On startup, read `edit/project.md` and summarize the last session in one sentence to re-establish context.

After each session, append a timestamped entry to `edit/project.md` using this format:

```
## Session YYYY-MM-DD

### Strategy
Current approach and goals for this project.

### Decisions
Key choices made and their rationale.

### Reasoning log
Significant inference chains or trade-off evaluations.

### Outstanding items
Unfinished work, open questions, or next actions.
```
{{MANAGED_BLOCK_END}}
