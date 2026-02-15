# Changelog

## v0.3.0 — Mode-based commands + compiled workflows (Feb 15, 2026)

### New features
- **Two command modes**: `/agent-resolve` (opens a PR) and `/agent-design` (posts design analysis as a comment). Replaces the old bare `/agent` command.
- **Multi-provider model support**: OpenAI (GPT) and Google (Gemini) model aliases alongside Anthropic (Claude). Configure in `remote-dev-bot.yaml`.
- **Two-file compiled install**: Single-file workflows (`agent-resolve.yml` and `agent-design.yml`) that users download into their repos — no shim or cross-repo reference needed.
- **Security guardrails**: Microagent injection prevents secret exfiltration. Author association gate restricts who can trigger agent runs.
- **Config layering**: Target repos can override defaults with their own `remote-dev-bot.yaml`.

### Improvements
- **Runbook overhaul**: Guided setup with cost limits, PAT walkthrough, provider-specific instructions, private repo support, troubleshooting table. Phases renumbered 1-5.
- **Testing framework**: Unit tests for config parsing and YAML validation, E2E test script with per-provider and all-models modes, security E2E tests, compiled workflow tests.
- **PR feedback loop**: Comment `/agent-resolve` on a PR to iterate with feedback.
- **Compiler rewrite**: Step lookup by name instead of hardcoded indices. Produces two self-contained workflow files.

### Breaking changes
- `/agent` and `/agent-<model>` commands no longer work. Use `/agent-resolve` or `/agent-resolve-<model>`.
- Compiled workflow install is now two files (`agent-resolve.yml` + `agent-design.yml`) instead of one.

## v0.2.0 — Shim + reusable workflow (Feb 11, 2026)

- Refactored into a thin shim (`agent.yml`) per target repo that calls a shared reusable workflow (`resolve.yml`).
- Cross-repo support tested with separate test repo.
- Dev cycle infrastructure in place.

## v0.1.0 — First working version (Feb 9, 2026)

- End-to-end pipeline operational: `/agent` comment on an issue triggers OpenHands, which resolves the issue and opens a draft PR.
