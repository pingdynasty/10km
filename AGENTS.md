# AGENTS.md

Guidance for agents working on 10km, and on loops forked from it.

## What this is

10km is an agent loop: a Planner plans cycles of tasks, Workers carry them out,
a Curator validates and merges, an Auditor improves the loop. `REQUIREMENTS.md` is
the source of truth. If the code and the requirements disagree, raise it; don't
change `REQUIREMENTS.md` without the operator.

## Layout

- `tenkm/`: the Python library. State (the `msm` state machine), config, git,
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
- Every state change goes through `tenkm.state`, one transaction per call.
- Scripts are safe to rerun after a crash at any point.
- Keep functions small and documented; agents script against `tenkm`.
- Use inclusive terms (allowlist, primary/replica, main).

## Testing

- Unit: `python3 -m unittest discover tests`
- End to end (container): `docker build -t 10km . && docker run --rm 10km /opt/10km/tests/smoke.sh`

Run the unit tests before every commit; run the smoke test when changing scripts,
the Dispatcher or the Curator flow.

## Commits and branches

- `main` holds the product only: requirements, code, prompts, tests, docs.
- Planning, progress and project-specific files stay on working branches.
- One topic per commit. Subject in the imperative, under 72 characters; the body
  says why.
