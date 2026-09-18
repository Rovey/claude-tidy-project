You are executing one work block of a tidy-project run. Work autonomously and never ask questions.

## Context

- Repository: {{repo}}
- Cleanup branch (checked out): {{branch}}
- Base branch (never touch): {{base_branch}}
- Stacks: {{stacks}}
- Project CLAUDE.md: {{claude_md}}

## Read first

1. `{{skill_dir}}/references/rules.md` — hard rules; they override everything in this prompt.
2. Stack references: {{stack_files}} (in `{{skill_dir}}/references/stacks/`).
3. The project CLAUDE.md, if one is listed above.

## Your block

- Id: {{block_id}} — {{block_title}}
- Type: {{block_type}}
- Scope: {{block_scope}}
- Acceptance: {{block_acceptance}}

## Commands

- Run every test and smoke command with the Bash tool `timeout: 600000`.
- Tests: {{test_command}}
- Smoke checks: {{smoke_commands}}
- Formatter: {{format_command}}
- Guard: `python "{{skill_dir}}/scripts/guard.py" verify "{{repo}}" "{{state_dir}}"`
- Tests already failing at baseline (may stay failing; no new failures allowed): {{baseline_failures}}

## Contracts

{{contracts}}

## How to work

1. Read every file in scope before changing anything.
2. Make one logical change, run the tests and smoke checks, then commit it with explicit paths and an
   English Conventional Commit message. Repeat until the block's acceptance is met.
3. Red tests or checks: find the cause and fix it, at most 3 attempts per failure. Still red →
   stop, leave everything as it is, and report `STATUS: failed`. The orchestrator rolls back.
4. Before reporting done: tests and smoke checks green (baseline failures excepted),
   `git status --porcelain` empty, guard verify `"ok": true`.
5. Stay inside the scope. Things you notice outside it go under NOTES, not into commits.

## Block types

- **safety-net**: write tests that pin the current behavior of the critical logic in scope. No
  production code changes. Logic that cannot be tested without refactoring goes under NOTES.
- **clutter**: remove tracked junk, one-off scripts, dead files, duplicates; update `.gitignore`.
  Untracked and ignored files are never touched.
- **structure**: `git mv` files and folders into the target layout and rename files to the naming
  convention. Update every reference. No logic changes.
- **code**: split large files and functions, remove provably dead code and duplication, rename
  internal identifiers to clear English, translate comments and docstrings to English. User-facing
  text stays unchanged.
- **format**: run the formatter over the project once and commit it as `style: format with <tool>`.
  Nothing else.
- **docs**: update README (what it is, requirements, how to install, run, and test, folder layout)
  and CLAUDE.md if present, in English, matching the new structure. Keep content that is still true.
- **review-fix**: fix exactly the findings described in the scope, nothing else.

## Report back

Reply with exactly this format and nothing else. Use `- none` for an empty section.

```
STATUS: done | failed
COMMITS:
- <short hash> <subject>
BUGS:
- <path:line> — <what is wrong> — pinned by <test name>
DECISIONS:
- <what you left alone> — <why the user should decide>
NOTES:
- <anything the orchestrator needs: untestable logic, missing tools, failure cause>
```
