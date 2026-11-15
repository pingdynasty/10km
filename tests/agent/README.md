# Agent tests (opt-in)

Tests that launch a real agent harness (claude, codex, kiro-cli) go here, as
`test_*.py`. They cost credits, so they never run by default:

- `make test`, `python3 tests/run.py` and the gates run only the deterministic
  tests in `tests/` (unit, script and fake-agent scenario tests). This directory
  has no `__init__.py`, so `python3 -m unittest discover tests` skips it too, and
  `tests/run.py` skips `agent.*` even if it becomes a package.
- Run them on purpose with `make agent-test` (or `python3 tests/run.py --agent`).

Agent tests run with the test config like any other test (`tests/testenv.py`):
every agent command fails unless the test sets its own, so each test sets the
harness command it means to run (e.g. `LOOP_AGENT`) explicitly. Keep them few and
short, and say in the docstring what they cost.
