# Python projects

## Detect

`requirements.txt`, `pyproject.toml`, `setup.py`, or `*.py` files in the root.

## Interpreter

1. A project virtual environment (`venv/`, `.venv/`): `venv/Scripts/python.exe` (Windows) or
   `venv/bin/python`.
2. Otherwise `python`. If the baseline syntax check fails because of newer syntax, try `py -3`.

Record the chosen interpreter as `PY` in `baseline.md`.

## Target layout (apps and tools without packaging)

```
main.py                 thin launcher, same path (every root launcher stays)
start.bat               launchers stay untouched
<tool_name>/            application package, snake_case, named after the tool
  __init__.py
  <modules by responsibility, e.g. client.py, parsing.py, reports.py, gui/>
tests/
  test_<module>.py
scripts/                helper scripts that are still useful
docs/
assets/                 images, fonts, templates not tied to a framework
requirements.txt
requirements-dev.txt    dev tooling only (pytest)
```

- An existing package or `src/` layout stays.
- Flask/FastAPI/Django: keep `templates/` and `static/` where the framework finds them, unless the
  app config sets the path explicitly and is updated in the same commit.
- Thin launcher, keeping what the old file did when run directly:

  ```python
  from tool_name.cli import main

  if __name__ == "__main__":
      main()
  ```

  If the old file ran code at top level without a `__main__` guard, the launcher runs it at top
  level too.
- Paths: code that finds files via `Path(__file__).parent` or relative to the working directory
  must still find the same files after a move. Adjust the base path in the same commit and add a
  test that asserts the resolved path.
- Scripts moved into `scripts/` that import the package add
  `sys.path.insert(0, str(Path(__file__).resolve().parents[1]))` before the import.
- Imports inside the package are absolute: `from tool_name.parsing import parse_rows`.
- Tracked `venv/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `pytest-of-*/`: `git rm -r --cached`
  and add them to `.gitignore`.
- PyInstaller `*.spec` files reference paths: update them with the move.

## Tests

- Command: `PYTHONDONTWRITEBYTECODE=1 PY -m pytest -q -p no:cacheprovider`
- pytest missing for `PY`:
  - project venv exists → `PY -m pip install pytest` and add `pytest` to `requirements-dev.txt`;
  - no venv → skip test blocks; report "pytest not available".
- Mock external boundaries with `unittest.mock.patch`: `requests`/`httpx` calls, Selenium or
  Playwright drivers, `smtplib`, `subprocess`, printers, `time.sleep` in retry loops. Use `tmp_path`
  for written files. Tests pass without network access.
- GUI code (tkinter, PyQt): don't create windows in tests. Test the logic behind event handlers once
  it lives in plain functions.
- Example of pinning current behavior:

  ```python
  from tool_name.payouts import dealer_payout


  def test_dealer_payout_is_half_of_isv_fee_excluding_vat():
      assert dealer_payout(isv_fee_incl_vat=121.00) == 50.00
  ```

## Formatter

- `ruff format` when `ruff --version` or `PY -m ruff --version` works; otherwise skip and report
  "ruff not available". Never install it globally; a project venv may get it via pip plus
  `requirements-dev.txt`.
- Existing `black` configuration and `black` available → use `black` instead.
- One commit: `style: format with ruff`. Never run `ruff check --fix` (lint autofixes can change
  behavior).

## Smoke checks

- Syntax, without writing bytecode:

  ```bash
  PY -c "import ast, pathlib; skip={'venv','.venv','node_modules','.git'}; [ast.parse(p.read_bytes(), str(p)) for p in pathlib.Path('.').rglob('*.py') if not skip & set(p.parts)]"
  ```

  A syntax error raises `SyntaxError` and exits non-zero.

- Import check `PYTHONDONTWRITEBYTECODE=1 PY -c "import tool_name.parsing"` only for modules whose
  top-level code has no side effects (no GUI start, network, or file writes at import).

## Pitfalls

- `.bat` launchers call `python something.py`: `something.py` is a contract and stays as a launcher.
- Config loaded with `open("config.json")` depends on the working directory: keep that behavior;
  don't switch to `__file__`-relative paths.
- Circular imports appear when splitting modules; run the import check after each split.
