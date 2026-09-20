# tidy-project rules

These rules bind the orchestrator and every agent in a tidy-project run. A project's own
`CLAUDE.md` may override defaults from the stack references, never these rules.

## Goal

Make the project tidy — logical structure, no clutter, clean names, clean English code, tests for
critical logic — while it keeps doing exactly what it does today.

## Never

- Push, pull, fetch, merge, or rebase. Never touch the base branch.
- Rewrite history, except `guard.py rollback` resetting the cleanup branch to a block's start commit.
- Use `--no-verify`, `git add -A`, `git add .`, or `git commit -a`. Stage explicit paths only.
- Delete, move, or modify untracked or ignored files that existed before the run started (`.env`,
  `config.json`, `chrome_profile/`, `logs/`, `downloads/`, `exports/`, …). Changing `.gitignore`
  itself is allowed. Leftovers of a failed block are never deleted: `guard.py rollback` moves them
  into the run's quarantine folder.
- Put secrets into your output, commits, tests, or the report. Tests use obviously fake values.
- Break a contract (see Contracts).
- Add, remove, or upgrade runtime dependencies. Dev-only test and formatter tooling is allowed.
- Perform real external actions in tests or checks: network APIs, scraping live sites, printers,
  mail, payments, cloud resources. Mock them.
- Change behavior (see Behavior). That includes fixing bugs.
- Change user-facing text: UI labels, dialogs, messages, printed or PDF output, CLI output, e-mail
  text, log lines. It stays exactly as it is, in whatever language it is written.
- Normalize line endings or change file encodings; keep BOMs as they are.
- Edit or rename existing database migrations.
- Install anything into a global interpreter or global package store.
- Ask the user anything. Only the orchestrator's pre-flight may stop with a message; after that,
  apply the doubt policy.

## Contracts

A contract is anything outside the code that depends on a name, path, or format. It must keep
working exactly as before:

- launchers and entrypoints in the root (`*.bat`, `*.cmd`, `*.ps1`, `*.sh`, `main.py`, `app.py`,
  `artisan`, `manifest.json`, `index.html`, `*.sln`) and every file a launcher runs;
- command-line arguments and exit codes;
- routes, URLs, API endpoints and their field names;
- config file names and keys, environment variable names;
- database tables and columns, class names stored in a database or in queued jobs;
- browser extension id, permissions, match patterns, message types, storage keys;
- files the program reads or writes by path at runtime (templates, data, exports, logs);
- the public API of anything other projects import;
- anything the README or the project's `CLAUDE.md` tells people to run or open;
- `.gitattributes` patterns, including Git LFS `filter=lfs` rules and `eol`/`text` settings.

Root launchers never move or get renamed. Another contract file may move only when every consumer
is inside the repository and is updated in the same commit.

Git LFS: never run `git lfs` commands, and treat pointer files as ordinary tracked files. Moving a
file that a `.gitattributes` LFS pattern matches takes it out of LFS at its new path, which commits
the binary into the repository. Move such a file only when the same commit updates the pattern;
otherwise leave it where it is and report it.

## Behavior

Behavior is everything an outside observer can see: return values, raised errors and their text,
files written (names, locations, contents), network calls (endpoints, payloads, order), exit codes,
printed and logged text, UI text and layout, timing and retry logic, ordering of output.

Refactoring keeps all of it identical. When code is wrong, keep it wrong:

- pin the current behavior in a test with the comment `Current behavior, see tidy-project report`
  (in the language's comment syntax);
- report it under BUGS with file and line.

## Doubt policy

When you are not sure a change is safe, don't make it. Report it under DECISIONS: what you would
change, and why you did not. Typical cases:

- a script or file might be used from outside the repository (Task Scheduler, shortcuts, other
  repositories, documentation for colleagues);
- code looks unused but could be reached dynamically (reflection, string lookups, `getattr`,
  `importlib`, framework auto-discovery, event names);
- a tracked file might contain real data (customer lists, serial numbers, exports) — suggest
  untracking it, don't do it;
- a root script with a `__main__` block (or the equivalent) that no launcher references: keep it
  runnable at the same path as a thin launcher — unless its name marks it as one-off (`debug_*`,
  `tmp_*`, `old_*`, `*_backup`, `*_copy`, `test_*` outside the test folder); then move it to
  `scripts/` when still useful, or remove it, and report it.

## Language

- English for file and folder names, identifiers, comments, docstrings, test names, commit
  messages, README, `CLAUDE.md`, and the report.
- Renaming stops at contracts: config keys, JSON/API fields, database columns, environment
  variables, and storage keys stay as they are.
- User-facing text stays exactly as it is (see Never).

## Git

- Work only on the cleanup branch named in your task.
- Move and rename with `git mv` so history follows. A case-only rename needs two steps on Windows:
  `git mv Name.py name_tmp.py` then `git mv name_tmp.py name.py`.
- Tracked file with a reserved Windows name (`nul`, `con`, `prn`, `aux`): `git rm --cached -- <name>`
  and commit. If deleting it from disk fails, leave the file (it is now untracked) and report it.
- One logical change per commit. Conventional Commits in English, matching the project's style:
  `test(scope): …`, `chore: …`, `refactor(scope): …`, `style: …`, `docs: …`.
- Run tests and smoke checks before every commit.
- Finish every block with `git status --porcelain` empty.

## Structure and naming

- Precedence: framework conventions, then the stack reference's target layout, then the dominant
  existing convention in the project.
- The root holds only launchers and entrypoints, README, LICENSE, `.gitignore`, dependency
  manifests, `*.example` configs, and tool configs that must live in the root. Everything else
  lives in folders: `<package>/` or `src/`, `tests/`, `scripts/`, `docs/`, `assets/`.
- Don't create empty folders, or a folder for a single trivial file just to match a layout.
- File names follow the language convention: `snake_case.py`, `kebab-case.js`, `PascalCase.cs`,
  `PascalCase.php` for classes.
- After every move or rename, search the whole repository for the old name and old path (code,
  launchers, configs, manifests, HTML, docs, tests) and update every hit.

## Code

- Split a file over ~300–400 lines or with several responsibilities. Split a function over ~50
  lines or nested deeper than ~3 levels. Guidelines, not limits.
- Remove code only when it is provably unused: no references anywhere, including strings,
  launchers, and configs. Otherwise apply the doubt policy.
- Extract a shared function only when the duplicated copies behave identically.
- Clear English names. Comments explain why, not what. Remove commented-out code.
- Follow patterns the project already uses. Don't introduce new architecture, frameworks, or
  libraries.

## Testing policy

- Test critical logic: calculations (payouts, fees, costs, totals), parsing and data
  transformation, anything sent to customers or payment systems, authentication and authorization.
- Don't test UI layout, trivial getters and setters, or framework behavior.
- Tests pin current behavior with exact expected values.
- Mock every external boundary: HTTP, browsers and drivers, printers, mail, subprocesses, the clock
  where it matters. Use temporary directories for file output. Tests pass without network access.
- Never mock the unit under test.
- When logic is only testable after extracting it from a UI handler, the extraction belongs in a
  `code` block; the safety-net block notes it instead.
