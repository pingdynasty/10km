# AGENTS.md

Guidance for agents working on 10km, and on loops forked from it.

## What this is

10km is an agent loop: a Planner plans cycles of tasks, Workers carry them out,
a Curator validates and merges, an Auditor improves the loop. `REQUIREMENTS.md` is
the source of truth. If the code and the requirements disagree, raise it; don't
change `REQUIREMENTS.md` without the operator. Each requirement has a stable ID
(`R1`, `R2`, ...): cite IDs in tests and reports, and never renumber them.

## Layout

- `tenkm/`: the Python library. `msm` (the state machine), config, git,
  sessions, launchers, notifications, dispatch. Rules live here, not in the CLI.
- `bin/`: entry points. Python entry points are thin wrappers over `tenkm`; Bash is
  only for light scripts.
- `hooks/`: git hooks (Bash).
- `prompts/`: role prompts. Each loop adapts these.
- `config.env`: loop settings, sourced as shell; environment variables override.
- `tests/`: unit tests, and an end-to-end smoke test with a fake agent.

## Conventions

- Python standard library only; Python 3.9+. Code must run on Linux and macOS.
- Bash only for short scripts and hooks: no JSON handling, no state logic.
- Every state change goes through `tenkm.msm`, one transaction per call.
- Scripts are safe to rerun after a crash at any point.
- Keep functions small and documented; agents script against `tenkm`.
- Use inclusive terms (allowlist, primary/replica, main).

## Testing

- Unit and script tests: `make test` runs them in parallel with `tests/run.py`
  (`-j N` jobs, default the CPU count; name patterns select classes, e.g.
  `python3 tests/run.py test_msm`). `python3 -m unittest discover tests` runs the
  same tests serially. Tests must be safe to run in parallel: temporary roots, no
  fixed ports or shared paths.
- End to end, in the container: `make smoke` (builds the image, runs `tests/smoke.sh`)
- End to end, on the host (Linux or macOS): `make smoke-host` (runs `tests/smoke.sh`)

Run the unit tests before every commit; run the smoke test when changing scripts,
the Dispatcher or the Curator flow. To map a requirement ID, add it to `MAP` in its
section's file in `tests/conformance/` (a `tests/<file>.py:Class.method` that
checks it, or a `prompts/<file>.md` with a phrase for agent-only behaviour) and drop
it from `PENDING`; `python3 tests/conformance.py` lists what is left. `tests/smoke.sh` works in a temporary
directory and ignores a live loop's environment, so it is safe to run inside a loop
session.

## Commits and branches

- `main` holds the product only: requirements, code, prompts, tests, docs.
- Planning, progress and project-specific files stay on working branches.
- One topic per commit. Subject in the imperative, under 72 characters; the body
  says why.
