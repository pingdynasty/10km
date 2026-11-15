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

## Install

You need Python 3.9+ (standard library only), Bash, git, and an agent CLI such as `claude`, `codex` or `kiro-cli`. Put `bin/` on your `PATH`:

```sh
export PATH="$PWD/bin:$PATH"
10km --help
```

The loop lives under `LOOP_ROOT` (default `/loop`): the central worktrees in `$LOOP_ROOT/central/`, one directory per session beside them, and the database at `MSM_DB` (default `$LOOP_ROOT/.10km/loop.db`).

## Container or host

Agents run with their permission prompts off, so run the loop in a sandbox: they can do anything the loop's user can. The `Dockerfile` gives you one, with an unprivileged user, no exposed ports, and volumes for the worktrees (`/loop`) and the database (`/data`). Add the agent harness you use to it, then:

```sh
docker build -t 10km .
docker run -d --name 10km -v loop:/loop -v data:/data 10km   # runs bin/run-loop
docker exec -it 10km 10km status
```

`run-loop` calls the Dispatcher every `DISPATCH_INTERVAL` seconds. On a host, run it yourself, or call `10km dispatch` from cron. Use a host only if it is itself a sandbox, such as a dedicated VM or account.

## Init and kickoff

```sh
PROJECT_REPOS='app=https://example.com/app.git' 10km init
10km session start <username>
```

In a container, run them with `docker exec -it 10km ...`. `10km init` creates the database, the central loop repo and the project repos. The kickoff session then sets the goals, deliverables, plan, gates and prompts with you, and finishes with `msm loop start`: see [prompts/kickoff.md](prompts/kickoff.md). The first Curator merges the kickoff work, then the first Planner runs.

## Configuration

Settings are in `config.env` in the central loop worktree, sourced as shell. An environment variable of the same name overrides a setting. Change them in a session's loop worktree: they take effect once a Curator has merged them into main. The ones operators usually set:

| Setting | Meaning |
|---|---|
| `PROJECT_REPOS` | Project repos: `name` creates an empty repo, `name=url` clones one. |
| `WORKER_GATES` | Commands Workers run (`gate worker`) before done; one per line, or `repo: command`. |
| `VALIDATION_GATES` | Commands the Curator runs (`gate validation`); same format. |
| `NOTIFY_CMD` | Notification commands, one per line, run with `TENKM_PRIORITY`, `TENKM_TITLE`, `TENKM_BODY` and `TENKM_PROJECT` set. Empty: append to `NOTIFICATIONS.md` in the central loop worktree. |
| `LOOP_AGENT` | Agent command for every role, run with `SESSION`, `PROMPT_FILE` and `FIRST_MESSAGE` set. |
| `PLANNER_AGENT`, `WORKER_AGENT`, `CURATOR_AGENT`, `AUDITOR_AGENT` | Per-role overrides of `LOOP_AGENT`, e.g. to choose a model. |
| `SESSION_COMMAND` | Command for interactive operator sessions. |

Also in `config.env`: `MAIN_BRANCH`, `GIT_NAME`, `GIT_EMAIL`, `SESSION_TIMEOUT` (and per-role `PLANNER_TIMEOUT` etc.), `MAX_WORKERS`, `BACKLOG_SIZE`, `AUDIT_TIME`, `AUDIT_TIMEZONE`, `AUDIT_CYCLES_LIMIT` and `IDLE_CYCLE_LIMIT`.

## Operating the loop

```sh
10km status                        # phase, cycle, tasks, sessions, escalations, main
msm loop stop [reason]             # stop: the Dispatcher launches nothing new
msm loop resume                    # resume a stopped loop
10km session start <username>      # operator session with SESSION_COMMAND
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


Jorge Luis Borges explored the Infinite Monkey Theorem in his 1939 essay "The Total Library" (La biblioteca total). Borges referenced the idea—often attributed to Thomas Huxley—that "a half-dozen monkeys provided with typewriters would, in a few eternities, produce all the books in the British Museum".
"Strictly speaking, one immortal monkey would suffice".
 Two years later, in 1941, Borges transformed this probabilistic thought experiment into his famous short story "The Library of Babel". Borges imagined a universe consisting of endless hexagonal galleries containing books with every possible permutation of 25 basic symbols. Like the output of random typing, the library holds every masterpiece, the true history of the future, and the exact account of your death. However, these meaningful texts are buried inside an ocean of incomprehensible nonsense.
 
