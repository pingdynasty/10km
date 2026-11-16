# Contributing to 10km

For people and agents changing 10km itself, or a loop forked from it. The
requirements are in [requirements.md](requirements.md); how a loop is used is in
[usage.md](usage.md).

## Layout

- `tenkm/`: the Python library. `msm` (the state machine), config, git, sessions,
  launchers, notifications, dispatch. Rules live here, not in the CLI.
- `bin/`: entry points. Python entry points are thin wrappers over `tenkm`; Bash is
  only for light scripts.
- `hooks/`: git hooks (Bash).
- `prompts/`: role prompts. Each loop adapts these.
- `config.env`: loop settings, sourced as shell; environment variables override.
- `docs/`: requirements, usage, this file.
- `tests/`: unit and script tests, the conformance map, and an end-to-end smoke
  test with a fake agent.

## Conventions

- Python standard library only; Python 3.9+. Code must run on Linux and macOS.
- Bash only for short scripts and hooks: no JSON handling, no state logic.
- Every state change goes through `tenkm.msm`, one transaction per call.
- Scripts are safe to rerun after a crash at any point.
- Keep functions small and documented; agents script against `tenkm`.
- Cite requirement IDs (`R1`, `R2`, ...) in tests and reports; never renumber them.
- Use inclusive terms (allowlist, primary/replica, main).

## Testing

```sh
make test         # unit and script tests, in parallel: python3 tests/run.py
make smoke        # end to end with a fake agent, in the container (needs Docker)
make smoke-host   # the same end-to-end test on this host (Linux or macOS)
make agent-test   # tests that run a real agent harness (spend credits)
```

Run the unit tests before every commit; run the smoke test when changing scripts,
the Dispatcher or the Curator flow.

- `tests/run.py` runs each test (or test class with shared setup) in its own
  process: `-j N` sets the jobs (default: the CPU count; `make test JOBS=4`), `-v`
  lists every test, and patterns pick tests by id
  (`python3 tests/run.py test_msm TestDispatch`). It ends with the slowest tests.
  `python3 -m unittest discover tests` also works, serially.
- Tests must be safe to run in parallel: temporary roots, no fixed ports or shared
  paths.
- Tests never launch a real agent harness. Every test module imports
  `tests/testenv.py` first, which drops the caller's loop and agent settings and
  selects `tests/config.env`, where every agent command fails (exit 97) unless the
  test sets a fake (e.g. `LOOP_AGENT`, `tests/fake-agent`).
  `tests/test_no_agent.py` guards this. Tests that run a real harness go in
  `tests/agent/` and run only with `make agent-test` (`tests/agent/README.md`).
- The end-to-end test, `tests/smoke.sh`, needs Bash, git, jq and Python 3.9+. It
  runs in a temporary directory, removed on exit, and uses neither a live loop's
  settings nor your git config, so it is safe inside a loop session.
- Requirement IDs map to tests or prompt phrases in `tests/conformance/`, one file
  per section of the requirements; `python3 tests/conformance.py` lists what is
  unmapped.
- `loopstate.schema.json` is generated from the State block of the requirements:
  after changing that block run `python3 -m tenkm.schema` (a test checks it).
- A loop's gates are plain commands, e.g.
  `WORKER_GATES="10km: python3 tests/run.py -j 4"`.

## Commits and branches

- `main` holds the product only: requirements, code, prompts, tests, docs.
- Planning, progress and project-specific files stay on working branches.
- One topic per commit. Subject in the imperative, under 72 characters; the body
  says why.
