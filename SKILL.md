---
name: tidy-project
description: Use when the user explicitly asks to tidy, clean up, restructure or improve an entire git project autonomously on a separate branch
disable-model-invocation: true
argument-hint: "[project-path]"
---

# Tidy project

Tidy a git project on a local branch without changing what it does: logical structure, no clutter,
clean names, clean English code, tests for critical logic. The user walks away after Phase 0.
After Phase 0 you never ask the user anything.

`SKILL_DIR` is the directory containing this file. `GUARD` means `python "SKILL_DIR/scripts/guard.py"`;
it prints JSON with `ok` and `violations`.

**Read `SKILL_DIR/references/rules.md` now.** It binds you and every agent you dispatch.

## Your role

You orchestrate; subagents change the project. You yourself only:

- run read-only git commands, GUARD (every command; `refresh` only after the user asked for it),
  tests, and smoke checks;
- create and switch to the cleanup branch, and make the Phase 0 ignore commit;
- `git revert` and `git revert --abort` in Phase 3;
- write files in `STATE`.

You never delete or move project files yourself. Rollbacks go through `GUARD rollback`, which
quarantines leftovers instead of deleting them.

Dispatch agents with the Agent tool, one at a time, and wait for each result before continuing.
Never trust a subagent's STATUS alone; verify yourself. Append one line per action to
`STATE/log.md`: `<HH:MM> <phase or block> <action> <result>`.

Run every test and smoke command with the Bash tool `timeout: 600000`, output redirected to
`STATE/runs/<phase-or-block>-<command>.log` (create `STATE/runs/` first); read the log for the result.

## Phase 0 — Pre-flight

The user is still present: be quick. On any failed check, tell the user what failed and how to fix
it, then stop.

1. `REPO` = `git -C "<argument, or the current directory>" rev-parse --show-toplevel`. Not a repo →
   stop. If the argument was a subfolder, say that you use REPO.
2. Stop when any of these hold:
   - `git -C "REPO" branch --show-current` prints nothing (detached HEAD);
   - `git -C "REPO" rev-parse --absolute-git-dir` contains `MERGE_HEAD`, `CHERRY_PICK_HEAD`,
     `REVERT_HEAD`, `rebase-merge/`, or `rebase-apply/`.
3. If the current branch matches `cleanup/*`: `BRANCH` = that branch; `STATE` = `state_dir` from
   `GUARD state-dir "REPO" BRANCH`.
   - `STATE/report.md` exists → stop: this run is finished; switch to the base branch named in
     `snapshot.json` to start a new one.
   - `STATE/snapshot.json` exists → **Resume** (below).
   - Neither → stop and tell the user: "if tidy-project created this branch (it has no run state),
     switch back to your original branch and delete it with `git branch -D <branch>`; if it is your
     own branch, rename it — tidy-project reserves `cleanup/*`".
4. Otherwise:
   - `git -C "REPO" status --porcelain` prints anything → stop. List the entries and ask the user to
     commit or stash them first; untracked files count too.
   - Look for an unfinished run: for each branch from
     `git -C "REPO" for-each-ref --format='%(refname:short)' 'refs/heads/cleanup/*'`, take its
     `state_dir` from `GUARD state-dir "REPO" <branch>`. A branch whose STATE has `snapshot.json`,
     no `report.md`, and `base_branch` equal to the current branch → `git -C "REPO" switch <branch>`,
     set `BRANCH` and `STATE`, and **Resume**.
5. New run:
   - `BASE` = current branch;
   - `BRANCH` = `cleanup/<today as YYYY-MM-DD>`, with `-2`, `-3`, … appended when it exists;
   - `git -C "REPO" switch -c BRANCH`;
   - `STATE` = `state_dir` from `GUARD state-dir "REPO" BRANCH`; create it;
   - immediately, before any test runs: `GUARD snapshot "REPO" "STATE" --base BASE` (default settle
     time) must return `"ok": true`.
6. Detect stacks; a repo can have a primary and a secondary stack.

   | Marker | Stack file |
   |---|---|
   | `artisan` and `composer.json` requiring `laravel/framework` | `laravel.md` (its `package.json` belongs to Laravel) |
   | `manifest.json` with `manifest_version`, no bundler config | `browser-extension.md` |
   | `*.sln`, `*.slnx`, or `*.csproj` | `dotnet.md` |
   | `package.json` | `node.md` |
   | `requirements.txt`, `pyproject.toml`, `setup.py`, or `*.py` in the root | `python.md` |
   | none of the above | `scripts-and-docs.md` |

   Read every matching file in `SKILL_DIR/references/stacks/`.
7. Determine the test command, smoke checks, and formatter from the stack files. Check each tool
   runs (`--version`). Record missing tools.
8. Baseline: run the tests and smoke checks once, following the timeout rule in "Your role". Record
   per command: passed or failed, counts, failing test names, and duration. A command that does not
   finish within 10 minutes → stop and tell the user the suite is too slow for this skill (and how
   to discard BRANCH, as in Resume step 4).
9. Clean up after the baseline:
   - `git -C "REPO" status --porcelain` is not empty → the baseline left output behind. If build or
     test output (`__pycache__/`, `.pytest_cache/`, `pytest-of-*/`, `bin/`, `obj/`, `coverage/`,
     `.coverage`) is among it, append the patterns to `.gitignore`, `git -C "REPO" add .gitignore`,
     and commit `chore: ignore build and test output`. Then `GUARD rollback "REPO" "STATE" HEAD`
     (undoes tracked-file changes, quarantines other leftovers, deletes nothing).
   - The tree is clean → `GUARD verify "REPO" "STATE"`.

   If GUARD still reports local files changed or missing, stop and tell the user which files the
   test suite modifies (the run cannot guard them). Otherwise GUARD must be ok and
   `git -C "REPO" status --porcelain` empty.
10. Write `STATE/baseline.md`: REPO, BASE, BRANCH, stacks and stack files, interpreter or tool
    paths, test/smoke/format commands, missing tools, baseline results and durations, the project
    `CLAUDE.md` path (or `none`).
11. Tell the user, in at most 7 lines: branch, stacks, baseline result, missing tools, "Keep
    programs that use this project's local files closed during the run (for example a browser
    using a profile folder inside the project).", "The session must run in a permission mode that
    does not prompt.", and "You can walk away now. I won't ask anything; the report comes at the
    end." Continue immediately without waiting for a reply.

### Resume

Used by Phase 0 steps 3 and 4.

1. Read `STATE/snapshot.json` (`BASE` = `base_branch`, `BRANCH` = `cleanup_branch`) and whichever
   of `baseline.md`, `plan.md`, `review.md`, `final-gate.md`, `stopped.md`, and `log.md` exist.
2. `stopped.md` exists (and `report.md` does not) → the run stopped on a rollback it could not
   finish: go directly to Phase 4, before any other resume step or marker; don't roll back or verify
   again.
3. If `plan.md` has a block with `Status: todo` and a filled `Start commit`, working-tree changes
   belong to that interrupted block: `GUARD rollback "REPO" "STATE" <start commit>` and set that
   block to `Status: skipped: interrupted`; save `plan.md`. A rollback result with `ok: false` stops
   the resume here, whatever verify would say (verify does not check live files): show the complete
   rollback JSON (violations, errors, ambiguous, missing_volatile) so the user can find the moved
   files, and offer the step 4 options that apply. Without such a block, if
   `git -C "REPO" status --porcelain` prints anything, stop and show that output: the changes are
   not from a block; the user commits, stashes, or discards them and starts `/tidy-project` again.
4. `GUARD verify "REPO" "STATE"`. If violations remain, stop, show them (with the complete result
   of the step 3 rollback, if one ran, so the user can find moved files), and offer the options that
   apply, paths filled in:
   - only base branch moved, remote refs changed, or local file violations (`local file changed`,
     `local file missing`, `local path missing`), and the changes are yours → run
     `GUARD refresh "REPO" "STATE"` and start `/tidy-project` again;
   - a `contract file missing` violation → restore that file on the cleanup branch yourself and
     start `/tidy-project` again (refresh does not apply);
   - always → discard the run: `git -C "REPO" switch <BASE>` and `git -C "REPO" branch -D <BRANCH>`;
     then check `STATE/quarantine/` and `STATE/backup*` for files you still need (they can hold the
     only copies of moved or quarantined local files), and delete STATE only after that.
5. Tell the user "Resuming BRANCH — you can walk away" and continue at the first applicable step:
   - no `baseline.md` → Phase 0 step 6;
   - no `plan.md` → Phase 1;
   - a non-review block with `Status: todo` → Phase 2;
   - no `review.md` → Phase 3;
   - `review.md` has findings but `plan.md` has no `review-fix` blocks → Phase 3 step 2 (group
     findings);
   - a `review-fix` block with `Status: todo` → Phase 3 step 3 (fix loop);
   - no `final-gate.md` → Phase 3 step 4 (final gate);
   - no `report.md` → Phase 4.

## Phase 1 — Inventory and plan

1. Read the project `CLAUDE.md` if present. Its rules override stack defaults, never `rules.md`.
2. Inventory. When `git -C "REPO" ls-files | wc -l` is above 150, dispatch `Explore` agents one at a
   time (one per top-level folder or group of small folders) with the checklist below, asking each
   for a summary of at most 60 lines. Otherwise inventory yourself. Checklist:
   - **Contracts** as defined in `rules.md`.
   - **Clutter**: tracked junk, one-off debug scripts, dead files, duplicates, stale copies; mark
     each as provably unused or doubtful.
   - **Structure and naming**: current tree versus the stack file's target layout; non-English or
     badly named files, folders, identifiers.
   - **Code**: files over ~300–400 lines or with several responsibilities, functions over ~50
     lines or deeply nested, duplication.
   - **Test targets**: critical logic per the testing policy in `rules.md`, and whether tests exist.
3. Register file contracts GUARD did not detect: `GUARD add-contract "STATE" "<path>"` (compare with
   `contracts` in `snapshot.json`).
4. Write `STATE/plan.md` from `SKILL_DIR/templates/plan.md`: contracts, target layout, blocks.
   - Order: safety-net → clutter → structure → code → format → docs.
   - Leave out block types with nothing to do; add `format` only when a formatter is available.
   - At most ~15 files or ~3000 changed lines per block. Large repos get one safety-net block and
     one code block per module (a folder or domain).
   - Every block has a concrete scope (paths) and an observable acceptance line.

## Phase 2 — Execute

Repeat for the first block with `Status: todo`:

1. `START` = `git -C "REPO" rev-parse HEAD`; write it into the block's `Start commit` and save
   `plan.md` immediately, before dispatching.
2. Fill `SKILL_DIR/prompts/work-block.md` (replace every `{{…}}`) and dispatch one
   `general-purpose` agent with it. Wait for its result.
3. Verify yourself: tests (no new failures versus the baseline), the smoke checks that passed at
   baseline (a smoke check already failing at baseline is not a gate), and
   `GUARD verify "REPO" "STATE"`.
4. All green and `STATUS: done` → `Status: done`; list the commits; copy BUGS, DECISIONS, and NOTES
   into the block's Notes.
5. Anything red, or `STATUS: failed`:
   - `GUARD rollback "REPO" "STATE" START`;
   - `ok: false` with only `local file changed` violations (`errors`, `ambiguous`, and
     `missing_volatile` empty) → `GUARD restore "REPO" "STATE"`, then `GUARD verify "REPO" "STATE"`;
   - any other `ok: false` rollback result (violations, `errors`, `ambiguous`, or
     `missing_volatile`), or still not ok after that restore → unrecoverable: mark the block
     `skipped: <reason>` and **stop to Phase 4** (below);
   - otherwise → `Status: skipped: <one-line reason>` (a `review-fix` block first gets Phase 3
     step 3).
6. Save `plan.md`; append to `log.md`.
7. Three non-review blocks skipped in a row → mark every remaining non-review block with
   `Status: todo` as `skipped: not run — three blocks skipped in a row`, save `plan.md`, and go to
   Phase 3. This does not apply to `review-fix` blocks.

**Stop to Phase 4** (step 5, also for `review-fix` blocks run from Phase 3, and for a failed
rollback after a Phase 3 revert): first write `STATE/stopped.md` with the reason and the complete
rollback JSON (violations, errors, ambiguous, missing_volatile) so the user can find the moved
files; then mark every remaining block with `Status: todo`, non-review and `review-fix`, as
`skipped: not run — <reason>` and save `plan.md`; log it; go directly to Phase 4.

Never retry a skipped block in the same run.

## Phase 3 — Review

1. Dispatch the reviewer at most once per run. If `STATE/review.md` exists, don't dispatch; use its
   findings. Otherwise fill `SKILL_DIR/prompts/reviewer.md`, dispatch one fresh `general-purpose`
   agent, and save its FINDINGS verbatim to `STATE/review.md` immediately.
2. If `plan.md` has no `review-fix` blocks yet, group the findings by file into `review-fix` blocks
   (the scope lists the findings verbatim) and append them to `plan.md`.
3. Run the `review-fix` blocks through the Phase 2 loop; the three-skips rule does not apply. When a
   `review-fix` block ends skipped, before saving `plan.md`:
   1. revert every commit named in its findings, newest first, with
      `git -C "REPO" revert --no-edit <commit>`;
   2. gate as in Phase 2 step 3; green → Phase 2 step 6, then the next `review-fix` block;
   3. a revert conflicts or the gate goes red → `git -C "REPO" revert --abort` when a revert is in
      progress (`REVERT_HEAD` exists), then `GUARD rollback "REPO" "STATE" <commit before the first
      revert>`:
      - `ok: false` → **stop to Phase 4** (no restore);
      - `ok: true` → list the findings under "Decisions for you" (note them in the block's Notes),
        then Phase 2 step 6 and the next `review-fix` block.

   No path returns to reverting the same block.
4. Final gate: full tests, the smoke checks that passed at baseline, `GUARD verify "REPO" "STATE"`.
   If GUARD fails and every violation is `local file changed`, run `GUARD restore "REPO" "STATE"`;
   with any other violation don't restore (a missing file may have been moved, and a restore would
   put a stale copy next to it) and only record the violations. Either way put the violations first
   in the report summary. When the gate passes, or after it recorded violations, write its results
   (tests, smoke checks, GUARD result and violations) to `STATE/final-gate.md`.

## Phase 4 — Report

1. Fill `SKILL_DIR/templates/report.md` into `STATE/report.md` using `plan.md`, `log.md`,
   `git -C "REPO" log --oneline BASE..BRANCH`, `git -C "REPO" ls-tree --name-only BASE` and
   `git -C "REPO" ls-tree --name-only BRANCH` (root before and after),
   `git -C "REPO" ls-tree -r --name-only <ref> | wc -l` (file counts), and the final test results.
   Add the follow-up steps from the stack files. If `STATE/stopped.md` exists, its content (reason
   and complete rollback JSON) comes first in the report summary.
2. Stay on BRANCH. Don't merge, push, or switch back.
3. Print a terminal summary of at most 15 lines: branch, blocks done and skipped, tests before and
   after, number of bugs found, number of decisions for the user, and the full path of
   `STATE/report.md`.
