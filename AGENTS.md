# AGENTS.md

Guidance for agents working on 10km, and on loops forked from it.

10km is an agent loop: a Planner plans cycles of tasks, Workers carry them out,
a Curator validates and merges, an Auditor improves the loop.

- [docs/requirements.md](docs/requirements.md) is the source of truth. If the code
  and the requirements disagree, raise it; don't change the requirements without
  the operator.
- [docs/contributing.md](docs/contributing.md): layout, conventions, testing,
  commits. Run the unit tests (`make test`) before every commit.
- [docs/usage.md](docs/usage.md): how operators run and work with a loop.

## Customising the loop

If you are running a loop in a 10km fork then feel free to adapt prompts and
scripts to your project needs. The database is best left alone and the `msm` state
machine should be the last thing that you touch.
