#!/usr/bin/env python3
"""Safety guard for tidy-project runs.

snapshot      record the invariants on the cleanup branch before any work block
verify        check the invariants after every work block
restore       copy backed-up local files back after a violation
rollback      reset the cleanup branch to a start commit; recover and quarantine, never delete
refresh       re-record base commit, remote refs and local files after the user confirmed changes
add-contract  register an extra file that must keep existing
state-dir     print the run state directory for a cleanup branch

Live local files: snapshot and refresh stat the local files twice, a settle time apart.
`volatile_unstable` lists the files that changed, appeared, or disappeared in between;
`volatile` lists their parent directories (a root-level file: the file itself). Unstable files are
never checked, recovered, or restored. Other ("stable") files under a volatile path keep an
existence check in verify and may be recovered or restored when missing, but their content is not
checked and never overwritten.

Rollback never guesses. Under a volatile path that is gone (`missing_volatile`), or under its
highest missing ancestor directory that held recorded local files, nothing is recovered or
restored. A missing file that was not moved back, unstable files included, is reported and never
restored from backup while an untracked or ignored file with the same name exists elsewhere (it may
be the moved copy). Those candidates are never quarantined. For a stable file, a same-named file
inside a regenerable directory is not such a candidate unless it matches exactly (name, size,
mtime); for an unstable file it always is. An exact match there is still moved back. Both cases
leave rollback with `ok: false`.

Python 3.9+, standard library only. Prints JSON; exit code 0 = ok, 1 = violation.
"""
import argparse
import fnmatch
import json
import shutil
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

SNAPSHOT_FILE = "snapshot.json"
BACKUP_DIR = "backup"
QUARANTINE_DIR = "quarantine"
BACKUP_MAX_FILE_BYTES = 10 * 1024 * 1024
BACKUP_MAX_TOTAL_BYTES = 200 * 1024 * 1024
REGENERABLE_DIRS = {
    "node_modules", "vendor", ".venv", "venv", "__pycache__",
    ".pytest_cache", ".ruff_cache", "bin", "obj",
}
REGENERABLE_PREFIXES = ("storage/framework/", "bootstrap/cache/")
CONTRACT_NAMES = {
    "main.py", "app.py", "__main__.py", "manage.py", "artisan", "manifest.json",
    "index.html", "package.json", "composer.json", "requirements.txt", "pyproject.toml",
}
CONTRACT_PATTERNS = ("*.bat", "*.cmd", "*.ps1", "*.sh", "*.sln")


def git(repo, *args):
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, encoding="utf-8", errors="surrogateescape", check=True,
    )
    return result.stdout


def fail(message):
    return {"ok": False, "violations": [message]}


def branch_commit(repo, branch):
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", "refs/heads/" + branch],
        capture_output=True, encoding="utf-8", errors="surrogateescape",
    )
    return result.stdout.strip() or None


def utc_timestamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def git_paths(repo, *ls_files_args):
    output = git(repo, "ls-files", *ls_files_args, "-z")
    return sorted(path for path in output.split("\0") if path)


def wrong_branch(repo, snapshot, command):
    current = git(repo, "branch", "--show-current").strip()
    if current == snapshot["cleanup_branch"]:
        return None
    return fail("{} must run on {!r}, current branch is {!r}".format(
        command, snapshot["cleanup_branch"], current or "detached HEAD"))


def is_regenerable(rel_path):
    parts = rel_path.split("/")
    if any(part in REGENERABLE_DIRS for part in parts[:-1]):
        return True
    return rel_path.startswith(REGENERABLE_PREFIXES)


def is_contract_name(name):
    return name in CONTRACT_NAMES or any(fnmatch.fnmatch(name, pattern) for pattern in CONTRACT_PATTERNS)


def local_files(repo):
    output = git(repo, "ls-files", "--others", "--ignored", "--exclude-standard", "-z")
    return sorted(path for path in output.split("\0") if path and not is_regenerable(path))


def file_state(path):
    info = path.stat()
    return {"size": info.st_size, "mtime_ns": info.st_mtime_ns}


def stat_local_files(repo):
    files = {}
    for rel in local_files(repo):
        try:
            files[rel] = file_state(Path(repo) / rel)
        except OSError:
            continue
    return files


def unstable_files(before, after):
    return sorted(rel for rel in set(before) | set(after) if before.get(rel) != after.get(rel))


def volatile_paths(before, after):
    """Parent directories of local files that changed, appeared, or disappeared; root files as themselves."""
    return sorted({rel.rsplit("/", 1)[0] if "/" in rel else rel for rel in unstable_files(before, after)})


def is_volatile(rel, volatile):
    return any(rel == path or rel.startswith(path + "/") for path in volatile)


def scan_local_files(repo, settle_seconds):
    before = stat_local_files(repo)
    time.sleep(settle_seconds)
    after = stat_local_files(repo)
    # A path that vanished while settling was never a lasting local file; don't report it missing later.
    volatile = [path for path in volatile_paths(before, after) if (Path(repo) / path).exists()]
    return after, volatile, unstable_files(before, after)


def remote_refs(repo):
    output = git(repo, "for-each-ref", "--format=%(refname) %(objectname)", "refs/remotes")
    return dict(line.split(" ", 1) for line in output.splitlines() if line)


def root_contracts(repo):
    output = git(repo, "ls-files", "-z")
    return sorted({path for path in output.split("\0") if path and "/" not in path and is_contract_name(path)})


def state_dir_for(repo, branch):
    common_dir = Path(git(repo, "rev-parse", "--git-common-dir").strip())
    if not common_dir.is_absolute():
        common_dir = Path(repo) / common_dir
    return (common_dir / "tidy-project" / branch.replace("/", "-")).resolve()


def load_snapshot(state_dir):
    return json.loads((Path(state_dir) / SNAPSHOT_FILE).read_text(encoding="utf-8"))


def save_snapshot(state_dir, snapshot):
    (Path(state_dir) / SNAPSHOT_FILE).write_text(json.dumps(snapshot, indent=2), encoding="utf-8")


def backup_local_files(repo, state_dir, files):
    backed_up = []
    total = 0
    for rel in sorted(files, key=lambda path: files[path]["size"]):
        size = files[rel]["size"]
        if size > BACKUP_MAX_FILE_BYTES or total + size > BACKUP_MAX_TOTAL_BYTES:
            continue
        target = state_dir / BACKUP_DIR / rel
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(Path(repo) / rel, target)
        except OSError:
            continue
        backed_up.append(rel)
        total += size
    return sorted(backed_up)


def cmd_snapshot(repo, state_dir, base, settle_seconds=0):
    state_dir = Path(state_dir)
    if (state_dir / SNAPSHOT_FILE).exists():
        return fail("snapshot already exists in {}; resume the run instead".format(state_dir))
    base_commit = branch_commit(repo, base)
    if base_commit is None:
        return fail("base branch {} does not exist".format(base))
    cleanup_branch = git(repo, "branch", "--show-current").strip()
    if not cleanup_branch or cleanup_branch == base:
        return fail("snapshot must be taken on the cleanup branch, not on {!r}".format(cleanup_branch or "detached HEAD"))
    files, volatile, unstable = scan_local_files(repo, settle_seconds)
    state_dir.mkdir(parents=True, exist_ok=True)
    backed_up = backup_local_files(repo, state_dir, files)
    snapshot = {
        "base_branch": base,
        "base_commit": base_commit,
        "cleanup_branch": cleanup_branch,
        "remote_refs": remote_refs(repo),
        "local_files": files,
        "volatile": volatile,
        "volatile_unstable": unstable,
        "backed_up": backed_up,
        "contracts": root_contracts(repo),
    }
    save_snapshot(state_dir, snapshot)
    return {
        "ok": True,
        "violations": [],
        "local_files": len(files),
        "volatile": volatile,
        "backed_up": len(backed_up),
        "contracts": snapshot["contracts"],
    }


def cmd_verify(repo, state_dir):
    snapshot = load_snapshot(state_dir)
    violations = []
    base = snapshot["base_branch"]
    base_commit = branch_commit(repo, base)
    if base_commit != snapshot["base_commit"]:
        violations.append("base branch {} moved: {} -> {}".format(base, snapshot["base_commit"], base_commit))
    current = git(repo, "branch", "--show-current").strip()
    if current != snapshot["cleanup_branch"]:
        violations.append("current branch is {!r}, expected {!r}".format(current, snapshot["cleanup_branch"]))
    status = git(repo, "status", "--porcelain").rstrip()
    if status:
        violations.append("working tree not clean:\n" + status)
    volatile = snapshot["volatile"]
    unstable = set(snapshot["volatile_unstable"])
    for rel, expected in snapshot["local_files"].items():
        if rel in unstable:
            continue
        path = Path(repo) / rel
        if not path.exists():
            violations.append("local file missing: " + rel)
        elif not is_volatile(rel, volatile) and file_state(path) != expected:
            violations.append("local file changed: " + rel)
    for rel in volatile:
        if not (Path(repo) / rel).exists():
            violations.append("local path missing: " + rel)
    for rel in snapshot["contracts"]:
        if not (Path(repo) / rel).exists():
            violations.append("contract file missing: " + rel)
    if remote_refs(repo) != snapshot["remote_refs"]:
        violations.append("remote-tracking refs changed (push or fetch happened)")
    return {"ok": not violations, "violations": violations}


def cmd_restore(repo, state_dir):
    snapshot = load_snapshot(state_dir)
    backed_up = set(snapshot["backed_up"])
    restored = []
    unrestorable = []
    unstable = set(snapshot["volatile_unstable"])
    for rel, expected in snapshot["local_files"].items():
        if rel in unstable:
            continue
        path = Path(repo) / rel
        if path.exists() and (is_volatile(rel, snapshot["volatile"]) or file_state(path) == expected):
            continue
        backup = Path(state_dir) / BACKUP_DIR / rel
        if rel in backed_up and backup.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, path)
            restored.append(rel)
        else:
            unrestorable.append(rel)
    return {
        "ok": not unrestorable,
        "violations": ["cannot restore (no backup): " + rel for rel in unrestorable],
        "restored": restored,
    }


def recovery_key(rel, state):
    return rel.rsplit("/", 1)[-1], state["size"], state["mtime_ns"]


def same_name_candidates(repo, snapshot, rels):
    """Untracked or ignored, non-recorded files, by name, for the names of rels."""
    names = {rel.rsplit("/", 1)[-1] for rel in rels}
    present = set(git_paths(repo, "--others")) | set(git_paths(repo, "--others", "--ignored", "--exclude-standard"))
    same_name = {}
    for candidate in sorted(present - set(snapshot["local_files"])):
        name = candidate.rsplit("/", 1)[-1]
        if name in names:
            same_name.setdefault(name, []).append(candidate)
    return same_name


def recover_moved_files(repo, snapshot, missing, errors):
    """Move missing local files carried away by a directory move back, only when the match is unambiguous.

    Returns the recovered and ambiguous paths, and for every file that is still missing the
    untracked or ignored files with the same name that may be its moved copy.
    """
    recorded = snapshot["local_files"]
    if not missing:
        return [], [], {}
    wanted = Counter(recovery_key(rel, recorded[rel]) for rel in missing)
    same_name = same_name_candidates(repo, snapshot, missing)
    matches = {}
    for candidate in [path for paths in same_name.values() for path in paths]:
        try:
            key = recovery_key(candidate, file_state(repo / candidate))
        except OSError:
            continue
        if key in wanted:
            matches.setdefault(key, []).append(candidate)
    recovered = []
    ambiguous = []
    moved = set()
    for rel in missing:
        key = recovery_key(rel, recorded[rel])
        candidates = matches.get(key, [])
        if not candidates:
            continue
        if len(candidates) > 1 or wanted[key] > 1:
            ambiguous.append(rel)
            continue
        try:
            (repo / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(repo / candidates[0]), str(repo / rel))
        except OSError as error:
            errors.append("recover {}: {}".format(rel, error))
            continue
        recovered.append(rel)
        moved.add(candidates[0])
    possible_copies = {}
    for rel in missing:
        # A same-named file in a regenerable directory is unrelated, unless it matched exactly.
        exact = matches.get(recovery_key(rel, recorded[rel]), [])
        copies = [
            path for path in same_name.get(rel.rsplit("/", 1)[-1], [])
            if path not in moved and (path in exact or not is_regenerable(path))
        ]
        if rel not in recovered and copies:
            possible_copies[rel] = copies
    return recovered, ambiguous, possible_copies


def quarantine_batch(state_dir):
    first = Path(state_dir) / QUARANTINE_DIR / utc_timestamp()
    batch = first
    suffix = 2
    while batch.exists():
        batch = first.with_name("{}-{}".format(first.name, suffix))
        suffix += 1
    return batch


def quarantine_untracked(repo, state_dir, snapshot, keep, errors):
    batch = quarantine_batch(state_dir)
    quarantined = []
    for rel in git_paths(repo, "--others", "--exclude-standard"):
        if rel in snapshot["local_files"] or rel in keep or is_volatile(rel, snapshot["volatile"]):
            continue
        target = batch / rel
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(repo / rel), str(target))
        except OSError as error:
            errors.append("quarantine {}: {}".format(rel, error))
            continue
        quarantined.append(rel)
    return quarantined


def restore_missing(repo, state_dir, snapshot, rels, errors):
    backed_up = set(snapshot["backed_up"])
    restored = []
    for rel in rels:
        path = repo / rel
        backup = Path(state_dir) / BACKUP_DIR / rel
        if path.exists() or rel not in backed_up or not backup.exists():
            continue
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, path)
        except OSError as error:
            errors.append("restore {}: {}".format(rel, error))
            continue
        restored.append(rel)
    return restored


def missing_live_roots(repo, snapshot, missing_volatile):
    """For each missing volatile path, its highest missing ancestor directory that held recorded local files.

    Recovering a file from such an ancestor would recreate the folder around the live folder that
    is still gone, splitting what was moved as a whole. Without such an ancestor: the path itself.
    """
    roots = []
    for path in missing_volatile:
        parts = path.split("/")
        root = path
        for depth in range(1, len(parts)):
            ancestor = "/".join(parts[:depth])
            if not (repo / ancestor).exists() and any(
                rel.startswith(ancestor + "/") for rel in snapshot["local_files"]
            ):
                root = ancestor
                break
        roots.append(root)
    return roots


def cmd_rollback(repo, state_dir, start_commit):
    snapshot = load_snapshot(state_dir)
    refusal = wrong_branch(repo, snapshot, "rollback")
    if refusal:
        return refusal
    repo = Path(repo)
    git(repo, "reset", "--hard", start_commit)
    # A live folder that is gone was moved as a whole; putting single files back would split it.
    missing_volatile = [path for path in snapshot["volatile"] if not (repo / path).exists()]
    missing_roots = missing_live_roots(repo, snapshot, missing_volatile)
    unstable = set(snapshot["volatile_unstable"])
    gone = [
        rel for rel in sorted(snapshot["local_files"])
        if not is_volatile(rel, missing_roots) and not (repo / rel).exists()
    ]
    missing = [rel for rel in gone if rel not in unstable]
    errors = []
    recovered, ambiguous, possible_copies = recover_moved_files(repo, snapshot, missing, errors)
    # A live file is never moved back, but a same-named file elsewhere may be where it went.
    gone_unstable = [rel for rel in gone if rel in unstable]
    if gone_unstable:
        same_name = same_name_candidates(repo, snapshot, gone_unstable)
        for rel in gone_unstable:
            copies = same_name.get(rel.rsplit("/", 1)[-1])
            if copies:
                possible_copies[rel] = copies
    named = {path for copies in possible_copies.values() for path in copies}
    quarantined = quarantine_untracked(repo, state_dir, snapshot, named, errors)
    restored = restore_missing(repo, state_dir, snapshot, [rel for rel in missing if rel not in possible_copies], errors)
    result = cmd_verify(repo, state_dir)
    not_restored = [
        "local file not restored, possible moved copy: {} (candidates: {})".format(rel, ", ".join(copies))
        for rel, copies in sorted(possible_copies.items())
    ]
    violations = result["violations"] + not_restored
    result.update({
        "ok": not violations and not errors,
        "violations": violations,
        "recovered": recovered,
        "ambiguous": ambiguous,
        "quarantined": quarantined,
        "restored": restored,
        "missing_volatile": missing_volatile,
        "errors": errors,
    })
    return result


def cmd_refresh(repo, state_dir, settle_seconds=0):
    state_dir = Path(state_dir)
    snapshot = load_snapshot(state_dir)
    refusal = wrong_branch(repo, snapshot, "refresh")
    if refusal:
        return refusal
    base_commit = branch_commit(repo, snapshot["base_branch"])
    if base_commit is None:
        return fail("base branch {} does not exist".format(snapshot["base_branch"]))
    files, volatile, unstable = scan_local_files(repo, settle_seconds)
    backup = state_dir / BACKUP_DIR
    if backup.exists():
        backup.rename(state_dir / "{}-previous-{}".format(BACKUP_DIR, utc_timestamp()))
    snapshot.update({
        "base_commit": base_commit,
        "remote_refs": remote_refs(repo),
        "local_files": files,
        "volatile": volatile,
        "volatile_unstable": unstable,
        "backed_up": backup_local_files(repo, state_dir, files),
    })
    save_snapshot(state_dir, snapshot)
    return {
        "ok": True,
        "violations": [],
        "local_files": len(files),
        "volatile": volatile,
        "backed_up": len(snapshot["backed_up"]),
    }


def cmd_add_contract(state_dir, path):
    snapshot = load_snapshot(state_dir)
    rel = path.replace("\\", "/")
    if rel not in snapshot["contracts"]:
        snapshot["contracts"] = sorted(snapshot["contracts"] + [rel])
        save_snapshot(state_dir, snapshot)
    return {"ok": True, "violations": [], "contracts": snapshot["contracts"]}


def build_parser():
    parser = argparse.ArgumentParser(description="Safety guard for tidy-project runs.")
    commands = parser.add_subparsers(dest="command", required=True)
    state_dir = commands.add_parser("state-dir", help="print the state directory for a cleanup branch")
    state_dir.add_argument("repo")
    state_dir.add_argument("branch")
    snapshot = commands.add_parser("snapshot", help="record invariants on the cleanup branch")
    snapshot.add_argument("repo")
    snapshot.add_argument("state_dir")
    snapshot.add_argument("--base", required=True)
    snapshot.add_argument("--settle-seconds", type=float, default=5)
    verify = commands.add_parser("verify", help="check invariants")
    verify.add_argument("repo")
    verify.add_argument("state_dir")
    restore = commands.add_parser("restore", help="restore backed-up local files")
    restore.add_argument("repo")
    restore.add_argument("state_dir")
    rollback = commands.add_parser("rollback", help="reset to a start commit; recover moved files, quarantine leftovers")
    rollback.add_argument("repo")
    rollback.add_argument("state_dir")
    rollback.add_argument("start_commit")
    refresh = commands.add_parser("refresh", help="re-record base commit, remote refs and local files")
    refresh.add_argument("repo")
    refresh.add_argument("state_dir")
    refresh.add_argument("--settle-seconds", type=float, default=5)
    add_contract = commands.add_parser("add-contract", help="register an extra contract file")
    add_contract.add_argument("state_dir")
    add_contract.add_argument("path")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command == "state-dir":
            result = {"ok": True, "violations": [], "state_dir": str(state_dir_for(args.repo, args.branch))}
        elif args.command == "snapshot":
            result = cmd_snapshot(args.repo, args.state_dir, args.base, args.settle_seconds)
        elif args.command == "verify":
            result = cmd_verify(args.repo, args.state_dir)
        elif args.command == "restore":
            result = cmd_restore(args.repo, args.state_dir)
        elif args.command == "rollback":
            result = cmd_rollback(args.repo, args.state_dir, args.start_commit)
        elif args.command == "refresh":
            result = cmd_refresh(args.repo, args.state_dir, args.settle_seconds)
        else:
            result = cmd_add_contract(args.state_dir, args.path)
    except subprocess.CalledProcessError as error:
        result = fail("git {} failed: {}".format(" ".join(error.cmd[3:]), (error.stderr or "").strip()))
    except OSError as error:
        result = fail(str(error))
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
