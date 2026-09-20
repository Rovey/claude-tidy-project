# tidy-project

An autonomous [Claude Code](https://claude.com/claude-code) skill that tidies a git project on a
local `cleanup/<date>` branch, without changing what the project does. You run it, walk away, and
come back to small reviewable commits and a report.

## What it does

- **Structure**: moves files into a logical layout for the detected stack (application code,
  tests, scripts, docs, assets), following that stack's own conventions where they exist.
- **Clutter**: removes tracked junk (build output, stray temp files, dead code, duplicate or stale
  copies) and updates `.gitignore`.
- **Naming**: renames files, folders, and identifiers to clear, consistent English, keeping every
  reference to them updated.
- **Code split**: splits files and functions that are too large or do too many things, removes
  dead code, reduces duplication and deep nesting.
- **Tests that pin current behavior**: adds tests for critical logic that has none (calculations,
  parsing, auth, anything sent to customers or payment systems). These tests describe what the code
  currently does, bugs included — they are not meant to fix anything.
- **English internals**: file/folder names, identifiers, comments, docstrings, test names, commit
  messages, and README/CLAUDE.md become English. User-facing text is untouched (see below).
- **Report**: a Markdown report of everything done, skipped, and left for you to decide.

## What it never does

- push, merge, rebase, or otherwise touch the base branch;
- change behavior — including error/log message text or output ordering;
- change user-facing strings (GUI labels, CLI output, PDFs, emails — in whatever language they're
  already in);
- fix bugs it finds (it pins them with a test and reports them instead);
- delete or modify files that were untracked or gitignored before the run (`.env`, local config,
  browser profile folders, logs, downloads, …) — only `.gitignore` itself may change;
- add, upgrade, or remove runtime dependencies (dev-only test/format tooling is allowed);
- ask you anything once the pre-flight check has passed.

## Requirements

- [Claude Code](https://claude.com/claude-code)
- `git`
- Python 3.9+ on `PATH`, standard library only (used by `scripts/guard.py`, the safety guard)
- Whatever test runner, formatter, and smoke-check tooling the target project already uses (pytest,
  PHPUnit/Pest, xUnit, `dotnet format`, `node --test`, …) — the skill uses what's there, it does not
  install anything new

## Install

As a personal skill, available in every project:

```bash
git clone <this-repo-url> ~/.claude/skills/tidy-project
```

On Windows:

```powershell
git clone <this-repo-url> "%USERPROFILE%\.claude\skills\tidy-project"
```

Restart Claude Code so it picks up the new skill.

## Use

1. Commit or stash any pending changes in the target project — the run refuses to start on a dirty
   working tree.
2. Close any program that reads or writes local (untracked/ignored) files inside the project, such
   as a browser using a profile folder in the repo, for the duration of the run.
3. In a permission mode that does not prompt (the skill needs to run unattended after pre-flight),
   run:

   ```
   /tidy-project [path]
   ```

   `path` defaults to the current directory; it is resolved to the repository's top level.
4. Pre-flight takes about a minute and may stop with a question if something looks wrong (dirty
   tree, detached HEAD, a rebase in progress, …). Once it says you can walk away, it will not ask
   anything else.
5. The run produces a local `cleanup/YYYY-MM-DD` branch with small, conventional commits, and a
   report at `.git/tidy-project/<branch>/report.md` (plus a short summary printed at the end).
6. Review it like any other branch: `git log <base>..cleanup/...`,
   `git diff <base>...cleanup/... --stat`. Merge it with `git merge cleanup/...` if you're happy, or
   discard it with `git branch -D cleanup/...` — the base branch was never touched.

If a run is interrupted, running `/tidy-project` again on the same branch resumes it from where it
left off.

## How the safety guard works

`scripts/guard.py` (Python standard library only) protects everything the skill is not allowed to
touch:

- **snapshot**: at the very start, before any test runs, it records the base branch and commit,
  every untracked/ignored file (path, size, mtime), and a backup copy of those files. Files that are
  still changing when snapshotted (a live browser profile, for example) are tracked as "volatile" so
  a running program doesn't trip later checks.
- **verify**: after every work block and at the end of the run, it checks that the base branch is
  unchanged, the working tree is clean, every recorded local file is still there and unchanged, and
  every external contract file (entrypoints, config, launchers, …) still exists.
- **rollback**: if a block fails, this resets the branch to before that block, recovers any local
  files that got moved along with tracked files, and quarantines anything it can't account for into
  `.git/tidy-project/<branch>/quarantine/<timestamp>/` instead of deleting it.

A guard failure — a verify that finds violations it can't resolve, or a rollback that can't put
something back with certainty — stops the run rather than guessing.

## Supported stacks

| Stack | Reference |
|---|---|
| Python tool | `references/stacks/python.md` |
| Browser extension (no build step) | `references/stacks/browser-extension.md` |
| Laravel | `references/stacks/laravel.md` |
| .NET | `references/stacks/dotnet.md` |
| Node | `references/stacks/node.md` |
| Android / Gradle | `references/stacks/android-gradle.md` |
| Scripts and docs only (no real logic) | `references/stacks/scripts-and-docs.md` |

The skill detects the stack from markers in the repository (`composer.json`+`artisan`,
`manifest.json`, `*.csproj`/`*.sln`, `package.json`, `requirements.txt`/`pyproject.toml`, …) and
falls back to the scripts-and-docs reference otherwise. A repository can have a primary and a
secondary stack.

## Running the tests

```
python -m unittest discover -s tests
```

These are unit tests for the guard itself (`scripts/guard.py`), not for a project the skill tidies.

## Status and scope

Verified end-to-end on one real Python project clone, and on the dirty-tree stop path. The
browser-extension stack, the existing-tests path, and resume-after-crash are not yet covered by an
end-to-end run — read the report carefully and review the diff before merging, especially outside
of what's been exercised so far.

The skill is behavior-preserving by design: it will not fix bugs, add features, upgrade
dependencies, set up CI, or touch anything outside a local `cleanup/*` branch it creates itself.

## License

MIT — see [LICENSE](LICENSE).
