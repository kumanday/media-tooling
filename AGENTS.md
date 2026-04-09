# Media Tooling Development Context

This `AGENTS.md` is only for developing `media-tooling` itself.

- Read [docs/DEVELOPMENT.md](/Users/magos/dev/trilogy/writing/media-tooling/docs/DEVELOPMENT.md) before making substantial changes.
- Keep user-facing execution guidance out of this file. Project workspaces should get their managed `AGENTS.md` block from [project_AGENTS.md](/Users/magos/dev/trilogy/writing/media-tooling/src/media_tooling/templates/project_AGENTS.md) via `media-tooling-init`.
- When execution posture changes, update the packaged `.agents/skills/`, the project `AGENTS.md` template, and the user docs together.
- Run `bash scripts/check.sh` from the repo root before committing.
