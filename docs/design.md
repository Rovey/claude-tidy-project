# tidy-project — design

Date: 2026-09-16
Status: approved in brainstorming, pending written-spec review

## Goal

A Claude Code skill, invoked as `/tidy-project [path]`, that autonomously tidies a git project:
logical folder structure, no clutter, clean file names, clean code (split where needed), tests for
important logic, everything internal in English. The user starts it, walks away, and comes back to
a local branch with small commits and a report. No questions after the pre-flight phase.

## Decisions (from brainstorming)

| Topic | Decision |
|---|---|
| Scope of change | Behavior-preserving only. Bugs found are pinned by tests and reported, never fixed. |
| End state | Local branch `cleanup/YYYY-MM-DD` only. Never push, never merge, never open a PR. |
| Dirty working tree | Stop immediately in pre-flight with a list of the offending files. |
| Large projects | Same treatment, executed module by module. Framework conventions are sacred. |
| Execution | Orchestrator (main session) + sequential fresh subagents per work block + a final reviewer agent. |
| Language | Everything internal becomes English: file/folder names, identifiers, comments, docstrings, test names, commit messages, README/CLAUDE.md, the report. |
| User-facing text | GUI labels, messages, PDFs, CLI output stay exactly as they are (in whatever language the project already uses). |
| Skill name | `tidy-project`, `disable-model-invocation: true` (only runs when the user types it). |

## Skill layout

```
~/.claude/skills/tidy-project/
  SKILL.md                    orchestrator: phases, resume logic, dispatching, report
  references/rules.md         hard rules, language rules, doubt policy (every subagent reads this)
  references/stacks/
    python.md                 layout, pytest, ruff format, smoke checks, pitfalls
    browser-extension.md      manifest rules, node --test on extracted pure logic
    laravel.md                conventions, Pest/PHPUnit, Pint, artisan smoke checks
    dotnet.md                 src/tests layout, xUnit, dotnet format, Designer.cs rules
    node.md                   src/tests, existing runner or node:test
    android-gradle.md         Gradle/Android conventions, JVM unit tests only, manifest contracts
    scripts-and-docs.md       PowerShell/batch/HTML/markdown-only repos
  prompts/work-block.md       prompt template for an execution subagent
  prompts/reviewer.md         prompt template for the final reviewer agent
  templates/plan.md           plan skeleton
  templates/report.md         report skeleton
  scripts/guard.py            snapshot/verify/rollback invariants (Python stdlib only)
  docs/design.md              this document
```

Frontmatter:

```yaml
---
name: tidy-project
description: Use when the user explicitly asks to tidy, clean up, restructure or improve an entire git project autonomously on a separate branch
disable-model-invocation: true
argument-hint: "[project-path]"
---
```

## State

All run state lives inside the git directory so it never clutters the working tree and is never
committed: `<git-common-dir>/tidy-project/<branch-name-with-slashes-replaced>/`

| File | Content |
|---|---|
| `snapshot.json` | written by `guard.py snapshot`, re-recorded by `guard.py refresh` |
| `backup/` | copies of local files made by `guard.py snapshot`; `refresh` keeps the previous one as `backup-previous-<UTC timestamp>/` |
| `baseline.md` | stack(s), test/smoke/format commands, baseline test result and durations, failing tests at start |
| `plan.md` | numbered work blocks with status `todo / done / skipped (reason)`, start commit, and commit hashes |
| `review.md` | the reviewer's findings, saved verbatim; when it exists the reviewer is never dispatched again |
| `runs/` | output of every test and smoke command (`<phase-or-block>-<command>.log`) |
| `quarantine/<UTC timestamp>/` | leftovers moved out of the working tree by `guard.py rollback` (`-2`, `-3` … appended when that folder already exists) |
| `final-gate.md` | results of the Phase 3 final gate (tests, smoke checks, guard result and violations) |
| `stopped.md` | written when a run stops on a rollback it could not finish: the reason and the complete rollback JSON |
| `report.md` | final report |
| `log.md` | one line per orchestrator action (for resume and debugging) |

## Phase 0 — Pre-flight (user is still present, ~1 minute)

1. Resolve path (argument or cwd) to the repo top level (`git rev-parse --show-toplevel`). If the
   given path is a subfolder, say so and use the top level.
2. Stop with a clear message if any of these hold:
   - not a git repository;
   - detached HEAD, or a merge/rebase/cherry-pick/revert in progress.
3. Current branch is a `cleanup/*` branch: its state dir has `report.md` → stop (the run is
   finished; switch to the base branch named in `snapshot.json` to start a new one, so a new run
   never branches off a finished cleanup branch); has `snapshot.json` → Resume (below); has neither
   → stop and tell the user: if tidy-project created this branch (it has no run state), switch back
   to the original branch and delete it with `git branch -D <branch>`; if it is the user's own
   branch, rename it — tidy-project reserves `cleanup/*`.
4. Otherwise stop if `git status --porcelain` is non-empty (modified, staged, or
   untracked-not-ignored files). Untracked files also stop the run: they would be at risk of being
   committed or moved. Then look for an unfinished run: a `cleanup/*` branch whose state dir has
   `snapshot.json`, no `report.md`, and `base_branch` equal to the current branch → check it out
   and Resume.
5. New run: create `cleanup/YYYY-MM-DD` from the current branch (suffix `-2`, `-3` if taken). The
   current branch is the base branch. Immediately, before any test runs, `guard.py snapshot` with
   the default settle time, so every local file the baseline could touch is already recorded and
   backed up.
6. Detect stack(s) from markers (`composer.json`+`artisan` → Laravel, `manifest.json` with
   `manifest_version` → browser extension, `*.sln`/`*.csproj` → .NET, `package.json` → Node,
   `requirements.txt`/`pyproject.toml`/`*.py` → Python, otherwise scripts-and-docs). A repo can
   have a primary and secondary stack.
7. Determine test, smoke and format commands from the stack reference; check the tools exist on
   the machine. Missing tool → that step is skipped later and listed in the report.
8. Run the existing test suite (if any) and the smoke checks once; record the result and the
   durations in `baseline.md`. Tests failing at baseline may stay failing; no new failures are
   allowed. A smoke check that already fails at baseline is recorded and not used as a gate.
   Timeout rule (every phase, orchestrator and subagents): every test and smoke command runs with
   the Bash tool `timeout: 600000` (10 minutes, the tool maximum; the default is 2 minutes), and the
   orchestrator redirects the output to `<state-dir>/runs/<phase-or-block>-<command>.log`. A
   command that does not finish within 10 minutes at baseline stops the run: the suite is too slow
   for this skill.
9. If the baseline run left the working tree dirty: add ignore patterns for build/test output it
   created (`__pycache__/`, `.pytest_cache/`, `pytest-of-*/`, `bin/`, `obj/`, coverage output) and
   commit `chore: ignore build and test output` (only if such output exists); then
   `guard.py rollback <repo> <state-dir> HEAD`, which resets tracked files the tests modified,
   quarantines other leftovers, and deletes nothing. With a clean tree, `guard.py verify` instead.
   If the guard still reports local files changed or missing, stop and tell the user which files
   the test suite modifies; the run cannot guard them.
10. Read the project's `CLAUDE.md` if present. Project rules override skill defaults, except the
    hard rules in `references/rules.md`.
11. Tell the user: branch name, detected stack, baseline result, missing tools, "keep programs that
    use this project's local files closed during the run (for example a browser using a profile
    folder inside the project)", "you can walk away now". Remind that the skill needs a permission
    mode that does not prompt (bypass). From here on: no questions.

### Resume

Used when Phase 0 finds an unfinished run (steps 3 and 4):

1. Read `snapshot.json` (base and cleanup branch) and whichever of `baseline.md`, `plan.md`,
   `review.md`, `final-gate.md`, `stopped.md`, `log.md` exist.
2. `stopped.md` exists (and `report.md` does not) → go directly to Phase 4, before any other step
   or marker: the run already stopped on a rollback it could not finish, so it is neither rolled
   back nor verified again.
3. A block with status `todo` and a recorded start commit was interrupted mid-block; working-tree
   changes belong to it: `guard.py rollback <repo> <state-dir> <start commit>` and mark it
   `skipped: interrupted`, so unverified commits are never kept. A rollback result with `ok: false`
   stops the resume with the complete rollback JSON (violations, errors, ambiguous,
   missing_volatile), whatever verify says: verify does not check live files, so a possible moved
   copy of one would otherwise go unnoticed; the step 4 options apply. Without such a block, a
   dirty tree stops the resume with the `git status --porcelain` output: the changes are not from a
   block, and the user commits, stashes, or discards them and starts again. Resume never rolls back
   to `HEAD`.
4. `guard.py verify`. Remaining violations → stop and show them, with the complete result of the
   step 3 rollback if one ran. Options: when every violation is
   base branch moved, remote refs changed, or a local file violation and the changes are the
   user's → `guard.py refresh <repo> <state-dir>` and start `/tidy-project` again; a
   `contract file missing` violation → the user restores the file on the cleanup branch and starts
   again (refresh does not apply); always → discard the run (`git switch <base>`,
   `git branch -D <branch>`; then check the state dir's `quarantine/` and `backup*` for files still
   needed, since they can hold the only copies of moved or quarantined local files, and delete the
   state dir only after that). Resume never restores over files the user may have changed.
5. Tell the user it resumes and they can walk away, then continue at the first applicable step:
   no `baseline.md` → Phase 0 step 6; no `plan.md` → Phase 1; a non-review `todo` block → Phase 2;
   no `review.md` → Phase 3; `review.md` has findings but `plan.md` has no `review-fix` blocks →
   Phase 3 grouping of findings; a `todo` review-fix block → Phase 3 fix loop; no `final-gate.md` →
   Phase 3 final gate; no `report.md` → Phase 4.

## Phase 1 — Inventory and plan (orchestrator; Explore agents for large repos)

Produce `plan.md` covering:

- **External contracts** (must not break): root launchers (`*.bat`, `*.cmd`, `*.ps1`, `*.sh`),
  root entrypoints (`main.py`, `app.py`, `artisan`, `manifest.json`, `index.html`), CLI arguments,
  routes/URLs, API field names, config keys, env var names, DB schema/migrations, extension id and
  permissions, files the code reads or writes by path at runtime (templates, data, export folders),
  exported API of anything that looks like a library. Contract files not auto-detected by the
  guard are added with `guard.py add-contract <path>`.
- **Clutter**: tracked junk (`nul`, `__pycache__`, `.DS_Store`, build output, logs), one-off debug
  scripts, dead code, duplicate files, stale copies (`*_old`, `*_backup`, `foo_simplified.py`-style
  forks — only when provably unused).
- **Structure and naming**: target tree per stack reference; files/folders/identifiers that are
  non-English or break naming conventions.
- **Code**: files and functions that are too large or do several things, duplication, deep nesting.
- **Test targets**: critical logic without tests (see Testing policy).

Work blocks, in this order:

1. Safety-net tests (pin current behavior of critical logic).
2. Clutter removal and `.gitignore` update.
3. Structure and file/folder renames (`git mv`, update every reference).
4. Code: split, remove dead code, deduplicate, rename identifiers to clear English, translate
   comments/docstrings.
5. Formatter (one separate commit per formatter).
6. Docs: README (how to run, layout), CLAUDE.md if present.

Large repos: blocks 1 and 4 are split per module (a module = a folder/domain a subagent can hold
in context, roughly ≤15 files or ≤3000 lines per block). Blocks 2, 3, 5, 6 may also be split if large.

## Phase 2 — Execution (sequential fresh subagents)

For each `todo` block, the orchestrator:

1. Records the block start commit in `plan.md` and saves it before dispatching, so a resumed run
   can roll back an interrupted block.
2. Dispatches a `general-purpose` subagent with `prompts/work-block.md` filled in: repo path,
   branch, block spec, paths to `rules.md` and the stack reference, test/smoke/format commands,
   baseline failures, contract list.
3. Subagent works in small commits; after each change it runs tests + smoke checks (timeout rule);
   on red it gets at most 3 fix attempts. It returns: status, commits, bugs found, deferred
   decisions.
4. Orchestrator independently runs tests (no new failures versus baseline) + the smoke checks that
   passed at baseline + `guard.py verify`.
5. Pass → mark `done` with commits and notes. Fail → `guard.py rollback <repo> <state-dir> <block
   start>`, which quarantines leftovers and never deletes. If its only problems are
   `local file changed` violations → `guard.py restore` and verify again. Any other `ok: false`
   rollback result (violations, `errors`, `ambiguous`, or `missing_volatile`), or still failing
   after that restore, is unrecoverable → mark the block `skipped (reason)` and stop to the report.
   Otherwise mark `skipped (reason)`.
6. Update `plan.md` and `log.md` after every block.

Stop conditions:

- 3 consecutive skipped blocks (something systemic; `review-fix` blocks do not count) → every
  remaining non-review `todo` block is marked `skipped: not run — <reason>`, then Phase 3.
- Stop to the report (step 5, also for `review-fix` blocks run from Phase 3, and for a failed
  rollback after a Phase 3 revert): first `stopped.md` records the reason and the complete rollback
  JSON (so a run interrupted during the stop still resumes straight into Phase 4), then every
  remaining `todo` block, non-review and `review-fix`, is marked `skipped: not run — <reason>` and
  `plan.md` is saved, and the run goes straight to Phase 4, which puts that content first in the
  summary so the user can find moved files.

A resumed run therefore never picks up abandoned blocks. The same block is never retried within a
run.

## Phase 3 — Review

1. Fresh reviewer agent with `prompts/reviewer.md` reads `git diff <base>...HEAD` in chunks and
   checks: behavior changes, broken contracts, changed user-facing strings, secrets in commits,
   leftover non-English internal names/comments, tests that assert nothing or mock the thing under
   test, dangling references after moves. The reviewer runs at most once per run: its findings are
   saved verbatim to `review.md` immediately, and when `review.md` exists (for example after a
   resume) its findings are used instead of dispatching again.
2. Findings are grouped by file into `review-fix` blocks and run through the Phase 2 loop; the
   three-skips rule does not apply. If a fix block ends skipped, `git revert --no-edit` every commit
   named in its findings, newest first, then gate as in Phase 2. Gate green → next `review-fix`
   block. A revert conflicts or the gate goes red → `git revert --abort` when a revert is in
   progress, then `guard.py rollback <repo> <state-dir> <commit before the first revert>`. That
   rollback not ok → stop to the report (no restore); ok → list the findings under "Decisions for
   you" and continue with the next `review-fix` block. No path returns to reverting the same block.
3. Final full test run + the smoke checks that passed at baseline + `guard.py verify`. When verify
   fails, `guard.py restore` runs only if every violation is `local file changed`; with any other
   violation nothing is restored (a missing file may have been moved, and a restore would put a
   stale copy next to it). Either way the violations come first in the report summary. The results
   (including recorded violations) are written to `final-gate.md`, which marks the gate as done for
   a resumed run.

## Phase 4 — Report

`report.md` (English) from `templates/report.md`, and a short summary in the terminal:

- summary and top-level tree before/after; when `stopped.md` exists, its reason and rollback JSON
  come first in the summary;
- commits grouped by phase;
- tests added and what they cover;
- bugs found (pinned, not fixed);
- skipped blocks with reasons;
- decisions for the user (doubt cases deliberately left alone);
- missing tools;
- review and merge commands: `git log <base>..<branch>`, `git diff <base>...<branch> --stat`,
  `git merge <branch>`, and how to discard (`git branch -D <branch>`).

## Hard rules (`references/rules.md`)

Never:

- push, merge, rebase, or modify the base branch; rewrite history, except `guard.py rollback`
  resetting the cleanup branch to a block's start commit; use `--no-verify`;
- stage with `git add -A` / `git add .` — always stage explicit paths;
- delete or modify untracked or ignored files that existed before the run (`.env`, `config.json`,
  `chrome_profile/`, `logs/`, `downloads/` …); only `.gitignore` itself may change. Leftovers of a
  failed block are never deleted: `guard.py rollback` moves them into the run's quarantine folder;
- print, copy, or commit secrets; tests use fake values;
- break an external contract (see Phase 1);
- add, upgrade, or remove runtime dependencies (dev-only test/format tooling is allowed);
- perform real external actions in tests or smoke checks (network APIs, printers, mail, scraping
  live sites, payments) — mock them;
- change behavior, including error message text, log text, output ordering;
- change user-facing strings;
- normalize line endings;
- ask the user anything. Only the orchestrator's pre-flight may stop with a message; after that,
  the doubt policy applies.

Doubt policy — when unsure, do not change it; add it to "Decisions for you":

- a file might be used externally (loose `.bat`/`.ps1`, Task Scheduler, shortcuts);
- code looks dead but could be called dynamically (reflection, strings, framework magic);
- a root script with a `__main__` block that no launcher references: keep it runnable at the same
  path (thin shim) unless its name clearly marks it as one-off (`debug_*`, `tmp_*`, `test_*.py`
  outside tests), in which case move it to `scripts/` or remove it and report it.

Bugs: pin current behavior in a test with the comment `# Current behavior, see tidy-project report`
(language-appropriate comment syntax) and list it in the report.

Guidelines (not hard limits): split files over ~300–400 lines or with multiple responsibilities;
split functions over ~50 lines or deeply nested; naming follows the language convention, otherwise
the dominant convention already in the project.

Language: internal names, comments, docs, commits in English. Renaming stops at contracts (config
keys, JSON/API field names, DB columns, env vars stay as they are). User-facing strings unchanged.

Commits: Conventional Commits in English, matching the user's existing style
(`test(scope): …`, `chore: …`, `refactor(scope): …`, `style: …`, `docs: …`).

## Default layout

Root holds only: entrypoints/launchers, README, LICENSE, `.gitignore`, dependency manifests,
`*.example` configs. Everything else lives in:

| Folder | Content |
|---|---|
| `<package>/` or `src/` | application code |
| `tests/` | tests |
| `scripts/` | helper and one-off scripts that are still useful |
| `docs/` | documentation, analyses, HTML reports |
| `assets/` | icons, templates, images |

Framework conventions override this layout.

## Stack references (summary)

| Stack | Layout | Tests | Formatter | Smoke check |
|---|---|---|---|---|
| Python tool | `main.py` stays in root as thin launcher, code in `<tool_name>/` (no `src/` layout, so `python main.py` and `start.bat` keep working) | pytest via `requirements-dev.txt`, run with `PYTHONDONTWRITEBYTECODE=1` and `-p no:cacheprovider` | ruff format | syntax check with `ast.parse` (writes no bytecode); import modules only when top-level code has no side effects |
| Browser extension (no build) | `manifest.json` in root, extension id/permissions unchanged, code in `src/`, icons in `assets/`, manifest paths updated | `node --test` on extracted pure logic, no `package.json` added | none | `node --check` per file, manifest parses, every manifest-referenced file exists |
| Laravel | Laravel conventions; new patterns (Actions/Services) only if the project already uses them | existing Pest/PHPUnit | Pint | `php artisan route:list`, `php artisan test` |
| .NET | `src/<Project>/`, `tests/<Project>.Tests/`; never hand-edit `*.Designer.cs` | xUnit | `dotnet format` | `dotnet build` |
| Node | `src/`, `tests/` | existing runner, else `node:test` | only if already configured | existing build script or `node --check` |
| Android/Gradle | Gradle conventions (`app/src/main|test`), tidy within them; class/package renames are contract changes | JVM unit tests (`testDebugUnitTest`); never `connectedAndroidTest` | only an already configured ktlint/Spotless | `assembleDebug`, else `compileDebug*` |
| Scripts and docs | clutter, naming, `docs/` structure only | none unless there is real logic | none | PowerShell parser check for `.ps1` |

Windows pitfalls (in every stack reference where relevant): reserved file names (`nul`, `con`,
`aux`) need `git rm --cached` plus removal via a `\\?\` path; case-only renames need a two-step
`git mv`; long paths.

## Testing policy (for the projects the skill tidies)

Write tests for: calculations (payouts, fees, costs), parsing and data transformation, anything
sent to customers or payment systems, authentication/authorization. Do not write tests that only
cover UI layout, trivial getters, or framework behavior. Tests pin current behavior, including
known bugs.

## `scripts/guard.py`

Python 3, stdlib only. JSON output, exit code 0 = ok, 1 = violation.

- `snapshot <repo> <state-dir> --base <branch> [--settle-seconds N]` (default 5) records:
  - base branch name and commit;
  - cleanup branch name;
  - remote-tracking refs (`git for-each-ref refs/remotes`);
  - every untracked and ignored file (path, size, mtime), excluding regenerable directories
    (`node_modules`, `vendor`, `.venv`, `venv`, `__pycache__`, `.pytest_cache`, `.ruff_cache`,
    `bin`, `obj`, `storage/framework`, `bootstrap/cache`);
  - volatile paths: the local files are stat'ed, then again after the settle time. Files that
    changed, appeared, or disappeared in between are unstable (`volatile_unstable`); their parent
    directories (a root-level file: the file itself) are volatile (`volatile`). Files under a
    volatile path that stayed identical in both scans are stable. This keeps a program that is
    still running (for example a browser with a live `chrome_profile/`) from tripping `verify`
    without giving up on its stable neighbors;
  - a backup copy of untracked/ignored files ≤10 MB each (≤200 MB in total) into
    `<state-dir>/backup/`;
  - root contract files matching the entrypoint patterns.
- `add-contract <state-dir> <path>` adds a path to the contract list.
- `verify <repo> <state-dir>` checks:
  - base branch commit unchanged;
  - current branch is the cleanup branch;
  - working tree clean (no modified, staged, or untracked-not-ignored files);
  - recorded untracked/ignored files unchanged (size, mtime) and still present; stable files under a
    volatile path only need to exist (`local file missing`), unstable files are not checked; a
    volatile path itself must still exist (`local path missing`);
  - every contract file still exists;
  - remote-tracking refs unchanged.
- `restore <repo> <state-dir>` copies backed-up local files back when `verify` reports them changed
  or missing; stable files under a volatile path only when missing, unstable files never.
- `rollback <repo> <state-dir> <start-commit>` undoes a failed block and never deletes anything,
  directories included. It refuses without changing anything unless the cleanup branch is checked
  out. Then, in order:
  1. `git reset --hard <start-commit>`, then record the volatile paths that do not exist
     (`missing_volatile`): a live folder that is gone was moved as a whole, so no recorded file
     under it is recovered or restored (that would split it). The same holds for every recorded
     file under the highest missing ancestor directory of that path that held recorded local files
     (for example `chrome_profile/First Run` when the live folder `chrome_profile/Default` is gone
     together with `chrome_profile/`): recovering it would recreate the parent around a live folder
     that is still gone. `missing_volatile` itself lists only the volatile paths. The path stays
     missing, verify reports `local path missing`, and rollback returns `ok: false`;
  2. recover moved local files: a recorded, non-unstable local file that is missing (for example
     carried away by `git mv` of its directory) is matched to untracked or ignored files by name,
     size, and mtime, regenerable directories included (a folder renamed to `bin/` is still moved
     back). It is moved back when exactly one candidate matches and no other missing file has the
     same key. It is `ambiguous` only when candidates with that key exist but more than one
     matches, or another missing file shares the key; then nothing is moved;
  3. look for possible moved copies of every recorded file that is still missing (except the files
     step 1 leaves alone): a stable file that was not moved back (key mismatch, ambiguity, or a
     failed move), and an unstable file, which is never moved back. Candidates are untracked or
     ignored, non-recorded files with the same name. For a stable file, regenerable directories
     only count through the exact matches from step 2 (so `node_modules/x/.env` never blocks
     restoring `.env`); for an unstable file they always count (a live file moved into `bin/` is
     flagged). With candidates, nothing is moved or
     restored for that file and rollback adds the violation
     `local file not restored, possible moved copy: <recorded path> (candidates: <path>[, <path>])`.
     A missing unstable file without candidates is ignored (live programs delete their own
     temporary files);
  4. quarantine: every remaining untracked, non-ignored file (except recorded local files, files
     under volatile paths, and every candidate named in step 3, ambiguous ones included) moves to
     `<state-dir>/quarantine/<UTC timestamp>/<same relative path>`, with `-2`, `-3` … appended to
     the timestamp folder when it already exists; a named candidate therefore stays where the
     violation says it is;
  5. restore from backup a stable file that is still missing and has no candidates (the file is
     truly gone). Existing files are never overwritten; unstable files are never restored;
  6. `verify`.

  Every per-file move or copy is attempted separately; a failure is recorded under `errors`
  (`"<action> <path>: <message>"`), the remaining steps still run, and `ok` is false when `errors`
  or violations are not empty. When rollback cannot put a local file back with certainty it does
  not guess: it returns `ok: false` and the run stops. Output: `ok`, `violations` (from verify, plus
  the possible-moved-copy violations), `recovered`, `ambiguous`, `quarantined`, `restored`,
  `missing_volatile`, `errors`.
- `refresh <repo> <state-dir> [--settle-seconds N]` (default 5), for resume only, after the user
  confirmed that external changes are theirs: on the cleanup branch, re-records the base commit,
  remote-tracking refs, local files, volatile paths and unstable files, and backups. The previous
  backup is kept as `backup-previous-<UTC timestamp>/`. Base branch, cleanup branch, and contracts
  stay unchanged.

The orchestrator treats a failing `verify` as a failed block regardless of what the subagent reports.

## Testing the skill (before first real use)

Use a scratch copy, never a real working checkout: clone a real project into a scratch folder and
point its `origin` at a bare copy in that same scratch area, so an accidental push cannot reach the
real repository. Plant a few fake untracked/ignored files (`.env`, `config.json`) in the clone to
exercise the do-not-touch rule.

Cycle:

1. **RED**: on the clone, a subagent without the skill gets the user's original request ("clean up
   this project: logical folders, no clutter, neat names, tidy code, split where needed, tests for
   important parts, everything in English, work autonomously"). Record what goes wrong.
2. **GREEN**: run the skill on a fresh clone. Acceptance checklist:
   - `guard.py verify` passes; the bare remote received nothing;
   - tests green, no new failures versus baseline;
   - user-facing strings identical (diff check on string literals by the reviewer + manual spot check);
   - internal names, comments, and commits in English;
   - root layout matches the stack reference;
   - `report.md` exists with all sections.
3. **REFACTOR**: close gaps found, rerun the failing case.

Repeat the cycle against clones covering each supported stack before relying on the skill for a
project that matters; a large or costly-to-test repository is best run only after smaller ones have
succeeded.

## Out of scope

Fixing bugs, adding features, dependency upgrades, CI setup, pushing or PRs, non-git folders,
parallel execution.

## Status

Verified end-to-end on one real Python project clone, and on the dirty-tree stop path. The
browser-extension stack, the existing-tests path, and resume-after-crash are not yet covered by an
end-to-end run.
