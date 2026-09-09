# Comprehensive reviews

Periodic full-repo review reports — code health, doc/workflow drift, real-
world usage analysis, prompt assessment, recommendations. Distinct from
`design-workspace.md` (a working scratchpad) and the per-PR review comments
on GitHub (per-change, not whole-repo).

Each review lives in a dated subdirectory. Entry point is `SUMMARY.md`;
detailed findings are in `findings-*.md` alongside it. `PROCESS.md` and
`AGENT-PROMPTS.md` document how the review was produced (sequential
subagents with incremental disk writes — see the Fable budget protocol
memory).

## Index

- [`2026-06-11/`](2026-06-11/SUMMARY.md) — first comprehensive review. Done
  just after PRs #631-633 merged on dev. Headline findings: two injection
  vectors (one shell, one Python heredoc), `install.md` 404 on fresh
  install, distillation silently broken in `/agent-design`, `test.yml`
  doesn't run on dev PRs. Also: the council layer is the current working
  defense against premature-victory and closing the council loop is the
  recommended highest-leverage next feature.
