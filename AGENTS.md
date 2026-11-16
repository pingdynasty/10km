# AGENTS.md

Guidance for agents working on 10km, and on loops forked from it.

## What this is

10km is an agent loop: a Planner plans cycles of tasks, Workers carry them out,
a Curator validates and merges, an Auditor improves the loop. [`docs/requirements.md`](docs/requirements.md) is
the source of truth. If the code and the requirements disagree, raise it; don't
change `docs/requirements.md` without the operator. Each requirement has a stable ID
(`R1`, `R2`, ...): cite IDs in tests and reports, and never renumber them.
How operators use a loop: [`docs/usage.md`](docs/usage.md).

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

- Unit and script tests: `make test` (`python3 tests/run.py`, in parallel; `-j N`
  sets the jobs, patterns select tests, e.g. `python3 tests/run.py test_msm`).
  Tests must be safe to run in parallel: temporary roots, no fixed ports or
  shared paths.
- Tests never launch a real agent harness. Every test module imports
  `tests/testenv.py` first, which drops the caller's loop and agent settings and
  selects `tests/config.env`, where every agent command fails (exit 97) unless
  the test sets a fake (e.g. `LOOP_AGENT`, `tests/fake-agent`).
  `tests/test_no_agent.py` guards this.
- Tests that run a real harness go in `tests/agent/` and run only with
  `make agent-test` (`tests/agent/README.md`).
- End to end: `make smoke` (container) or `make smoke-host` (Linux or macOS).
  `tests/smoke.sh` ignores a live loop's environment, so it is safe inside a loop
  session.
- Requirement IDs map to tests or prompt phrases in `tests/conformance/`, one file
  per `docs/requirements.md` section; `python3 tests/conformance.py` lists what is
  unmapped.

Run the unit tests before every commit; run the smoke test when changing scripts,
the Dispatcher or the Curator flow.

## Commits and branches

- `main` holds the product only: requirements, code, prompts, tests, docs.
- Planning, progress and project-specific files stay on working branches.
- One topic per commit. Subject in the imperative, under 72 characters; the body
  says why.

## Customising the loop

If you are running a loop in a 10km fork then feel free to adapt prompts and
scripts to your project needs. The database is best left alone and the `msm` state
machine should be the last thing that you touch.
