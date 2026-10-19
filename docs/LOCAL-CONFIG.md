# Your private media-tooling folder

media-tooling is a public toolkit. How you use it — which accounts and cloud projects pay for renders, your house
style, where your sources live, your own end-to-end workflows — is yours, and stays out of this repository. It lives
in one local folder that the toolkit reads:

```
~/.config/media-tooling/          (or $MEDIA_TOOLING_CONFIG_DIR)
  profiles.toml                   profiles and the rules that pick one for a project folder
  profiles/<name>/AGENTS.md       private rules for projects of that profile
  skills/<skill>/SKILL.md         private skills
  adc/<name>.json                 per-profile Google credentials (media-cloud-render setup --save-adc)
  cloudrun/<name>/                per-profile cloud render stack (media-cloud-render deploy)
```

Nothing in it is required; without it every command behaves as before. To version or sync it, keep it in a private git
repository and point `MEDIA_TOOLING_CONFIG_DIR` there (keep `adc/` out of git).

## Profiles

```toml
default_profile = "personal"

[profiles.work]
rules = "reference"               # reference (default) | embed — see below
gcloud_configuration = "work-cfg" # cloud rendering, optional (docs/CLOUD-RENDER.md)
account = "me@work.example"
project = "work-gcp-project"

[profiles.personal]

[[rules]]                         # first match wins
path = "~/dev/work/**"
profile = "work"
```

Which profile applies to a project, highest first:

1. `--profile NAME` on the command
2. `profile = "NAME"` (or `render_profile`) in the nearest `media-tooling.toml`, searched from the project folder up
3. the first `[[rules]]` whose path contains the project folder
4. `default_profile`

Optional per profile: `rules_file` (a different path for the private rules), and the cloud rendering fields. At the
top level, `skills_dir` moves the private skills folder.

## Private rules

Write the rules for a kind of work once, in `profiles/<name>/AGENTS.md`: where articles or sources live, which env
file holds the keys, voice and style, review steps. `media-tooling-init <project>` (and `--agents-only`) then adds a
second block to the project's `AGENTS.md`, right after the toolkit's managed block:

- `rules = "reference"` (default): the block tells agents to read your private file by path. The rules' content stays
  out of the project repository; agents need to run on a machine that has the file.
- `rules = "embed"`: the block carries a copy of the rules, for agents that cannot read your config folder (cloud
  agents on a fresh checkout). Use it only for project repositories that are themselves private.

Re-running `media-tooling-init` refreshes the block, and removes it when no profile or rules file applies.

## Private skills

Put your own skills in `skills/<skill>/SKILL.md` (for example a complete "blog article → explainer video" workflow
that strings the toolkit's commands together). `media-tooling-link-skills` links them next to the toolkit's skills
into `~/.agents/skills` and the Claude Code store, so every agent harness finds them. A private skill may not reuse
the name of any skill the toolkit packages, and it never repoints an existing link to another source unless you pass
`--force`; `--no-private` skips private skills altogether.
