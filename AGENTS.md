# AGENTS.md

This file provides persistent context for AI agents working on this repository.

## Project Overview

<!-- Describe your project here. What does it do? What problem does it solve? -->

## Technology Stack

<!-- List your technologies: languages, frameworks, databases, etc. -->

- Language: <!-- e.g., Python 3.11, TypeScript 5.0 -->
- Framework: <!-- e.g., FastAPI, React, Next.js -->
- Database: <!-- e.g., PostgreSQL, SQLite -->
- Testing: <!-- e.g., pytest, vitest -->

## Coding Standards

### General

- Keep functions small and focused
- Write self-documenting code with clear names
- Add comments only for "why", not "what"
- Follow existing patterns in the codebase

### Formatting

<!-- Add your formatting commands -->

- Format command: `<!-- e.g., make format, npm run format -->`
- Lint command: `<!-- e.g., make lint, npm run lint -->`
- Type check: `<!-- e.g., make typecheck, npm run typecheck -->`

### Testing

<!-- Add your testing requirements -->

- Test command: `<!-- e.g., make test, npm test -->`
- Coverage requirement: <!-- e.g., 80%, 100% for critical paths -->
- Test location: `<!-- e.g., tests/, __tests__/ -->`

## Project Structure

```
<!-- Customize this structure for your project -->
.
├── src/                    # Source code
├── tests/                  # Test files
├── docs/                   # Documentation
├── configs/                # Configuration files
├── scripts/                # Utility scripts
├── AGENTS.md               # This file
├── WORKFLOW.md             # OpenSymphony configuration
└── README.md               # Project readme
```

## Key Directories

<!-- Document important directories -->

- `src/` - <!-- Main source code -->
- `tests/` - <!-- Test files -->
- `docs/` - <!-- Documentation -->

## Dependencies

### Runtime

<!-- List key runtime dependencies -->

### Development

<!-- List key dev dependencies -->

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `EXAMPLE_VAR` | <!-- Description --> | Yes/No |

## Local Development Setup

<!-- Steps to set up local development -->

```bash
# Example setup steps
# 1. Install dependencies
# 2. Configure environment
# 3. Run tests
```

## PR Requirements

Before submitting a PR:

1. All tests pass
2. Code is formatted
3. Lint checks pass
4. New code has tests
5. Documentation updated if needed

## Architecture Decisions

<!-- Document key architecture decisions -->

### Decision 1

- **Context**: <!-- Why this decision was needed -->
- **Decision**: <!-- What was decided -->
- **Consequences**: <!-- Impact and trade-offs -->

## Known Issues / Gotchas

<!-- Document any quirks or known issues -->

## References

<!-- Links to relevant external documentation -->

- [Framework Docs](https://example.com)
- [API Reference](https://example.com/api)

## Preserved Existing AGENTS.md

The following content was preserved from the repository's previous `AGENTS.md` during `opensymphony init`.

# Media Tooling Development Context

This `AGENTS.md` is only for developing `media-tooling` itself.

- Read [docs/DEVELOPMENT.md](/Users/magos/dev/trilogy/writing/media-tooling/docs/DEVELOPMENT.md) before making substantial changes.
- Keep user-facing execution guidance out of this file. Project workspaces should get their managed `AGENTS.md` block from [project_AGENTS.md](/Users/magos/dev/trilogy/writing/media-tooling/src/media_tooling/templates/project_AGENTS.md) via `media-tooling-init`.
- When execution posture changes, update the packaged `.agents/skills/`, the project `AGENTS.md` template, and the user docs together.
- Run `bash scripts/check.sh` from the repo root before committing.
