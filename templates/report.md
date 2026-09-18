# Tidy report — {{repo_name}}

Branch `{{branch}}` from `{{base_branch}}` ({{base_commit_short}}), {{date}}.

## Summary

<3–6 sentences: what changed, test status before and after, what needs attention first>

| | Before | After |
|---|---|---|
| Tracked files | {{files_before}} | {{files_after}} |
| Tests | {{tests_before}} | {{tests_after}} |
| Blocks | | {{blocks_done}} done, {{blocks_skipped}} skipped |

## Layout

Before:

```
{{root_before}}
```

After:

```
{{root_after}}
```

## Commits

### Safety net
### Clutter
### Structure
### Code
### Formatting
### Docs
### Review fixes

(`- <hash> <subject>` per commit; `- none` for an empty group)

## Tests added

- `<test file>` — <what it covers>

## Bugs found (not fixed)

- `<path:line>` — <problem> — pinned by `<test>`

## Skipped blocks

- <block id> <title> — <reason>

## Decisions for you

- <item> — <why it was left alone> — <suggested action>

## Missing tools

- <tool> — <what was skipped>

## Review and merge

```bash
git log --oneline {{base_branch}}..{{branch}}
git diff -M --stat {{base_branch}}...{{branch}}
git switch {{base_branch}}
git merge --no-ff {{branch}}
```

Discard the branch instead: `git branch -D {{branch}}`

<stack-specific follow-up, e.g. `pip install -r requirements-dev.txt`, reload the unpacked extension>
