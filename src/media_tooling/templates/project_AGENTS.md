{{MANAGED_BLOCK_START}}
# Media Tooling Project Context

This block is managed by `media-tooling-init`.
Treat this directory as `$PROJECT_DIR` and keep project artifacts inside it.

Read these central media-tooling skills before routing media-processing work:
{{SKILL_PATHS}}

Use installed toolkit commands from this project directory:
- spoken media: `media-subtitle` or `media-batch-subtitle`
- silent or visual-first video: `media-contact-sheet` or `media-batch-contact-sheet`
- rough-cut assembly: `media-rough-cut`

Operational defaults:
- prefer sequential processing for long media jobs
- use `--skip-existing` for resumable batches
- keep reusable toolkit code and installs outside this project workspace
- re-run `media-tooling-init` after reinstalling or relocating the toolkit so these skill paths stay current
{{MANAGED_BLOCK_END}}
