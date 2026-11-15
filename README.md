# Ten thousand monkeys

`10km` is a lightweight and flexible agent loop.

The Ralph loop iterates over a plan, the Karpathy loop optimises to a goal. The Monkey loop can do either, or both: it is a generalized loop, which you can be in, on, or outside.

In 10km, monkey agents act in four roles:
- Planner: Refines the plan into tasks
- Workers: Perform tasks
- Curator: Validates worker output
- Auditor: Inspects and improves the loop

The work is done in cycles, with a session per agent. You can run your own sessions in parallel, with an agent or without. The Curator merges it into the project.

You kick off a Monkey loop with your goals, deliverables and a high-level plan. If you're short on these, don't worry: just tell the loop what you want it to do. You can always change it later. The loop will continue running until its done, or until you tell it otherwise.

10km is designed to run in a sandbox, and to work well with small models. The loop can use any harness, with local or remote models. You can interfere with the monkeys at any time, or run your own parallel sessions.

The monkeys may use and abuse any tools you give them access to. It would be a mistake to let them out of their sandbox.

## Run it in a sandbox

Agents run with their permission prompts off: they can do anything the loop's user
can. Run the loop in a sandbox. The recommended one is the container: an
unprivileged user, no exposed ports, and only the directories you mount. A dedicated
VM or user account also works; a host you use for other things does not.

```sh
docker build -t 10km .            # add your agent harness to the Dockerfile first
mkdir central
docker run -d --name 10km -v "$PWD/central:/loop/central" -v 10km-data:/data 10km
docker exec -it 10km 10km kickoff
```

The central worktrees (the loop repo and the project repos) live on the host, in
`central/`, so you can see and edit them. The database is in the `10km-data`
volume. On first start the container creates the loop repo, `central/loop`, from
its copy of 10km, then runs `run-loop`, which calls the Dispatcher every
`DISPATCH_INTERVAL` seconds.

In another sandbox: you need Python 3.9+ (standard library only), Bash, git and
an agent CLI such as `claude`, `codex` or `kiro-cli`. Clone or fork 10km as
`<root>/central/loop`, and run its commands from there: `<root>` is the loop root
(`LOOP_ROOT`), with the database at `<root>/.10km/loop.db` unless `MSM_DB` says
otherwise. Run `central/loop/bin/run-loop`, or call `10km dispatch` from cron.

## Kickoff

`10km kickoff` runs the operator's agent (`OPERATOR_AGENT`) in `central/loop`,
with no session, after creating the database. With you, it sets the goals,
deliverables, plan, configuration, gates and prompts, and clones or creates the
project repos in `central/`, each with its branch and author in its own git
config. It commits to main and finishes with `msm loop start`; the first Planner
runs next. `10km kickoff -- "<instructions>"` does it in one shot. See
[prompts/kickoff.md](prompts/kickoff.md).

To add a repo later, clone it into `central/`, set its `tenkm.mainBranch` and
author with `git config`, and run `10km init`.

## Configuration

Settings are in `config.env` in the central loop worktree, sourced as shell. Repos and their settings (branch, author, remotes) are not: they are the git repos in `central/`, configured with `git config`. An environment variable of the same name overrides a setting. Change them in a session's loop worktree: they take effect once a Curator has merged them into main. The ones operators usually set:

| Setting | Meaning |
|---|---|
| `WORKER_GATES` | Commands Workers run (`gate worker`) before done; one per line, or `repo: command`. |
| `VALIDATION_GATES` | Commands the Curator runs (`gate validation`); same format. |
| `NOTIFY_CMD` | Notification commands, one per line, run with `TENKM_PRIORITY`, `TENKM_TITLE`, `TENKM_BODY` and `TENKM_PROJECT` set. Empty: append to `NOTIFICATIONS.md` in the central loop worktree. |
| `LOOP_AGENT` | Agent command for every role, run with `SESSION`, `PROMPT_FILE` and `FIRST_MESSAGE` set. |
| `PLANNER_AGENT`, `WORKER_AGENT`, `CURATOR_AGENT`, `AUDITOR_AGENT` | Per-role overrides of `LOOP_AGENT`, e.g. to choose a model. |
| `OPERATOR_AGENT` | The operator's agent, for kickoff and operator sessions; run with `FIRST_MESSAGE` and, for one-shot instructions, `ONE_SHOT=1`. It doesn't fall back to `LOOP_AGENT`. |

Also in `config.env`: `SESSION_TIMEOUT` (and per-role `PLANNER_TIMEOUT` etc.), `MAX_WORKERS`, `BACKLOG_SIZE`, `AUDIT_TIME`, `AUDIT_TIMEZONE`, `AUDIT_CYCLES_LIMIT` and `IDLE_CYCLE_LIMIT`.

## Operating the loop

```sh
10km status                        # phase, cycle, tasks, sessions, escalations, main
msm loop stop [reason]             # stop: the Dispatcher launches nothing new
msm loop resume                    # resume a stopped loop
10km session start <username>      # operator session with OPERATOR_AGENT
10km session start <username> --no-agent      # worktrees only; work by hand
10km session start <username> -- "<message>"  # one-shot instruction
10km session done <name>           # hand the session's work to the Curator
```

Run `msm` from your own shell or an operator session: it refuses loop changes from agent sessions while the loop is stopped. An operator session gets its own worktrees and branch, named `operator-<username>-<suffix>`. When you mark it done, the next Dispatcher pass launches a Curator to merge it, whatever the phase. Operator sessions never time out.

Agents raise escalations as issues for the Planner, Curator, Auditor or you. The loop notifies you only of blocking escalations and fatal errors, through `NOTIFY_CMD`. Test it with `10km notify <title> [body]`. To list and answer escalations:

```sh
msm issue list '{"status": "open", "assignee_role": "operator"}'
msm issue update <id> '{"status": "resolved", "resolution": "..."}'
```

## Recovering from a stop

The Curator stops the loop with reason `blocked` when there is a blocking operator escalation: a decision only you can make, the project is done, or the loop has been idle for `IDLE_CYCLE_LIMIT` empty cycles. A stopped loop launches nothing, but its state and worktrees stay as they were. Inspect it:

```sh
10km status
msm loop get
msm issue list '{"status": "open", "severity": "blocking"}'
msm session list '{"status": "expired"}'
msm task list '{"status": "rejected"}'
```

Each session directory holds the agent's `agent.log` and its `prompt.txt`. To resume:

1. Start an operator session: `10km session start <username>`.
2. Resolve the blocking escalations, or update the goals and plan; commit.
3. `10km session done <name>`.
4. `msm loop resume`.

The next Curator merges your session, then the loop carries on from its phase.

## Testing

```sh
make test         # unit and script tests, in parallel: python3 tests/run.py
make smoke        # end to end with a fake agent, in the container (needs Docker)
make smoke-host   # the same end-to-end test on this host (Linux or macOS)
```

The end-to-end test, `tests/smoke.sh`, needs Bash, git, jq and Python 3.9+. It
runs in a temporary directory, removed on exit, and uses neither a live loop's
settings nor your git config, so you can run it from inside a loop session.


Jorge Luis Borges explored the Infinite Monkey Theorem in his 1939 essay "The Total Library" (La biblioteca total). Borges referenced the idea—often attributed to Thomas Huxley—that "a half-dozen monkeys provided with typewriters would, in a few eternities, produce all the books in the British Museum".
"Strictly speaking, one immortal monkey would suffice".
 Two years later, in 1941, Borges transformed this probabilistic thought experiment into his famous short story "The Library of Babel". Borges imagined a universe consisting of endless hexagonal galleries containing books with every possible permutation of 25 basic symbols. Like the output of random typing, the library holds every masterpiece, the true history of the future, and the exact account of your death. However, these meaningful texts are buried inside an ocean of incomprehensible nonsense.
 
