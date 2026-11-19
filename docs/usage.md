# Using 10km

See the [README](../README.md) for what 10km is and how to run it.

## Kickoff

`10km kickoff` runs the operator's agent (`OPERATOR_AGENT`) in `central/loop`,
with no session, after creating the database. With you, it sets the goals,
deliverables, plan, configuration, gates and prompts, and clones or creates the
project repos in `central/`, each with its branch and author in its own git
config. It commits to main and finishes with `msm loop start`; the first Planner
runs next. `10km kickoff -- "<instructions>"` does it in one shot. See
[prompts/kickoff.md](../prompts/kickoff.md).

To add a repo later, clone it into `central/`, set its `tenkm.mainBranch` and
author with `git config`, and run `10km init`.

## Configuration

Settings are in `config.env` in the central loop worktree, sourced as shell. Repos and
their settings (branch, author, remotes) are not: they are the git repos in `central/`,
configured with `git config`. An environment variable of the same name overrides a
setting. Change them in a session's loop worktree: they take effect once a Curator has
merged them into main. The ones operators usually set:

| Setting | Meaning |
|---|---|
| `WORKER_GATES` | Commands Workers run (`gate worker`) before done; one per line, or `repo: command`. |
| `VALIDATION_GATES` | Commands the Curator runs (`gate validation`); same format. |
| `NOTIFY_CMD` | Notification commands, one per line, run with `TENKM_PRIORITY`, `TENKM_TITLE`, `TENKM_BODY` and `TENKM_PROJECT` set. Empty: append to `NOTIFICATIONS.md` in the central loop worktree. |
| `LOOP_AGENT` | Agent command for every role, run with `SESSION`, `PROMPT_FILE` and `FIRST_MESSAGE` set. |
| `PLANNER_AGENT`, `WORKER_AGENT`, `CURATOR_AGENT`, `AUDITOR_AGENT` | Per-role overrides of `LOOP_AGENT`, e.g. to choose a model. |
| `OPERATOR_AGENT` | The operator's agent, for kickoff and operator sessions; run with `FIRST_MESSAGE` and, for one-shot instructions, `ONE_SHOT=1`. It doesn't fall back to `LOOP_AGENT`. |

Settings for this host, rather than for the loop (tool locations, gate inputs, `PATH`), go in `<root>/host.env`, outside the repos. It is sourced before `config.env`, so its values win over `config.env`'s, and what it sets is exported to agents, gates and the commands they run. Write each setting as `X="${X-value}"` so the environment can still override it. Agents don't change it, and don't put keys in it: agents can read it.

Also in `config.env`: `SESSION_TIMEOUT` (and per-role `PLANNER_TIMEOUT` etc.), `MAX_TASKS_PER_CYCLE` (tasks per cycle, default no limit), `MAX_CONCURRENT_AGENTS` (agents the Dispatcher runs at once, 2 or more so the Auditor gets a place; operator sessions don't count), `BACKLOG_SIZE`, `AUDIT_TIME`, `AUDIT_TIMEZONE`, `AUDIT_CYCLES_LIMIT`, `IDLE_CYCLE_LIMIT`, `DISPATCH_INTERVAL`, `KILL_GRACE`, `START_GRACE`, `GATE_WAIT` (how long `gate` waits before exiting 3; keep it under the agent's tool-call limit), `LAUNCHER`, `PROJECT_NAME`, `MSM_DB`, `MSM_LOG` and `USAGE_LOG`. Each is described in the file.

## Interacting with a loop

There are two ways to act on a running loop: change its state directly with `msm`, or work in an operator session. Use `msm` for decisions and bookkeeping; use a session for anything that changes files in a repo. Both are for the operator, or an agent acting for the operator.

Run the commands from your own shell, with `LOOP_ROOT` and `PATH` set as in [Run it on a host](../README.md#run-it-on-a-host); in the container both are set already. Unset `LOOP_SESSION`: msm treats a set `LOOP_SESSION` as an agent's session.

```sh
10km status               # phase, cycle, Dispatcher, tasks, sessions, issues, audits, repos
```

For example:

```
10km loop, Nov 15 19:47 CET
Loop: running, phase curate, cycle 1
Dispatcher: last pass 19:46, 40s ago (ok); run-loop running (pid 4120)

Cycle 1 (open, planned 19:35, 12m ago):
  PH1: DEL2 (resume resets the idle count) and DEL3 (small bugs)
  done  msm-fixes       cycle1-worker1-uru425rs
  done  dispatch-fixes  cycle1-worker2-bhuva5n5

Active sessions: 1
  cycle1-curator-y7hgc9yb  since 19:47  25s  pid 20940
Waiting to be curated or removed: 3
  cycle1-planner-48y3tkot  done 19:37  10m ago
  cycle1-worker1-uru425rs  done 19:44  3m ago
  cycle1-worker2-bhuva5n5  done 19:46  1m ago

Open escalations: 0
Open backlog items: 0
Answered issues: 0
Audits: 0

Repository  Branch  Commit   When     Message
loop        main    47b55b0  0s ago   Kickoff: goals, plan and settings
10km        main    e6075ca  54m ago  Metrics: skip trailer values with control characters
```

Times are local (`TZ`, else the system zone), with the zone in the first line.

Agents raise escalations as issues for the Planner, Curator, Auditor or you. The loop notifies you only of blocking escalations and fatal errors, through `NOTIFY_CMD`. Test it with `10km notify <title> [body]`.

### 1. With msm: state only

`msm` changes the database at once: no session, no merge, no Curator pass. It never touches files or git, so it can't change goals, prompts, code or `docs/requirements.md` directly.

**Answer an escalation.** List what is waiting for you, read it in full, then record your decision as the resolution:

```sh
msm issue list '{"status": "open", "assignee_role": "operator"}'
msm issue get <id>
msm issue update <id> '{"status": "answered", "resolution": "<your decision>"}'
```

Write the resolution as an instruction: what you decided, and what the loop should do now. An issue goes open, answered, resolved: the role that raised it (its `assigner_role`) reads your answer, acts on it (a plan change, a backlog item, a task) and resolves it. An escalation with no `assigner_session`, such as the Dispatcher's, has no role to follow up: resolve it yourself (`"status": "resolved"`).

**Create a backlog item.** The Planner turns open backlog items into tasks:

```sh
msm issue create '{"type": "backlog", "title": "<one line>",
  "description": "<what you want, and why>", "assignee_role": "planner",
  "severity": "low|high|blocking", "urgent_if": "<when it becomes urgent>"}'
```

Search first (`msm issue list '{"status": "open"}'`) and update a similar item instead of adding another. Say in the description if you approve a change that would otherwise need you, such as a change to `docs/requirements.md`.

**Start, pause, resume and stop.**

```sh
10km start                  # start run-loop unless one runs; resume a stopped loop
10km pause [--now] [reason] # stop the loop: the Dispatcher launches nothing new
10km resume                 # continue a stopped loop from its phase
10km stop [--now]           # stop the loop and run-loop
msm loop get                # stopped or not, the reason, phase and cycle
```

Without `--now`, running agents finish their work; with it, they and their gate runs are stopped and their sessions expired (operator sessions are left alone). After `pause` the Dispatcher still runs, so it expires timed-out sessions and records usage; after `stop` nothing does until `10km start`. `run-loop` logs to `<root>/.10km/run-loop.log`; only one runs per loop. In the container `run-loop` is the main process, so `10km stop` ends the container: use `pause` there.

`run-loop` is optional: anything that runs `10km dispatch` every `DISPATCH_INTERVAL` seconds will do, such as cron (`* * * * * LOOP_ROOT=<root> <root>/central/loop/bin/dispatch >> <root>/.10km/dispatch.log 2>&1`), a systemd timer or launchd. Then use `pause` and `resume`, and start or stop the scheduler yourself. `10km status` shows the last Dispatcher pass, and flags it OVERDUE when passes stop coming while the loop runs.

Kickoff starts the loop with `msm loop start`; `10km resume` is `msm loop resume`, and `10km pause` is `msm loop stop` with a reason. A stopped loop keeps its state and worktrees. Agents can't restart it: msm refuses loop changes from agent sessions while the loop is stopped. `10km resume` is refused while a blocking escalation assigned to you is open; answer it first.

### 2. In an operator session: files and repos

An operator session is a session like an agent's: its own directory, `<root>/operator-<username>-<suffix>/`, with a worktree of every repo on a branch of the same name. Changes made there reach main the way agents' work does: when the session is marked done, the next Dispatcher pass launches a Curator, whatever the phase, which merges and validates it. Operator sessions never time out. The Curator escalates rather than drop operator work.

Use a session to change goals, the plan, prompts, `config.env`, `docs/requirements.md` or code. Don't edit or commit in `central/`: those worktrees belong to the Curator.

There are three kinds:

**Interactive.** You talk with your agent (`OPERATOR_AGENT`), in the session's loop worktree. It follows [prompts/session.md](../prompts/session.md).

```sh
10km session start <username>
```

**One-shot.** The agent gets your instructions as its first message and runs them without asking:

```sh
10km session start <username> -- "<instructions>"
10km session start <username> -- "Follow prompts/status.md"   # a status report
```

Write one-shot instructions to be complete: what to change, in which repo, what is approved (for example a `docs/requirements.md` change), which escalations to answer and with what decision, "mark the session done" at the end (or run `10km session done <session>` yourself), and "do not resume the loop" if the loop should stay stopped. For long instructions, put them in a file and pass `"$(cat file)"`. Start one session per topic, after the previous one is done; two sessions that change the same files conflict when the Curator merges them. A status report ([prompts/status.md](../prompts/status.md): state, deliverables, recent cycles, audits, cost and open escalations) changes nothing but marking its session done.

**Manual.** No agent: you, or an agent you run yourself, work in the worktrees by hand.

```sh
10km session start <username> --no-agent      # prints the session name and directory
cd <root>/<session>/<repo>                     # one worktree per repo
# edit, then commit on the session branch as usual
git add <files> && git commit -m "<what and why>"
10km session done <session>                    # hand the work to the Curator
```

Commit everything before `session done`: the Curator merges commits only, and uncommitted changes are lost when the session is removed. Commits get a `Loop-Session:` trailer from the session branch, added by the hooks `10km init` generates; each session worktree uses them, and they then run your own hooks. Commits made in `central/` run only your own hooks.

**Which to use.**

| You want to | Use |
|---|---|
| Answer an escalation with a decision | `msm issue update` |
| Ask for work | `msm issue create` (backlog item) |
| Pause or continue the loop | `10km pause` / `10km resume` |
| Change files yourself | a manual session |
| Have your agent change files, with you | an interactive session |
| Have your agent change files from written instructions | a one-shot session |

### Checking a loop

After kickoff, a configuration change, or when agents fail to start. None of these
creates a session or writes to the database.

```sh
10km doctor                    # tools, repos, database, config, agents, gates: ok or FAIL
10km launch-test [role]        # launch a role's agent with a trivial prompt (default: worker)
10km gate worker|validation    # run a tier's gates in the central worktrees
```

`doctor` only looks commands up, running no agent or gate; it exits 1 if a check fails.
`launch-test` starts a real agent through `LAUNCHER`, as the Dispatcher would, in a
temporary directory (kept) with its own `LOOP_ROOT` and `MSM_DB`, and prints the
exit code, time and log (`--timeout SECONDS`, default 600). `10km gate` waits until
the gates finish and keeps its logs in `<root>/.10km/evidence/operator/`; such a
run never counts as a session's gate.

## Metrics and logs

`10km metrics [--cycle N] [--json]` lists every session the loop still knows of, by cycle and role: its task and outcome, start and duration, commits on main (by `Loop-Session:` trailer) and harness usage (agent time, turns, tokens, cost or credits); then totals per cycle and role. Sessions are removed once curated, so times come from what survives: the session row, the Worker's task, the session's lines in the action log, and usage records. `--json` gives the same data for agents.

Each session directory holds the agent's `agent.log` and its `prompt.txt` until the session is removed. Usage outlives it in `usage.jsonl` next to the database (`USAGE_LOG`): one JSON line per agent run, with its session, role, cycle and harness, and the figures its harness reports: Claude Code with `--output-format json` (as in the default `LOOP_AGENT`), kiro-cli with `--output-format stream-json` (credits and time).

## Recovering from a stop

The Curator stops the loop when there is an open blocking operator escalation: a decision only you can make (reason `blocked`), the project is done (`done`), or the loop has been idle for `IDLE_CYCLE_LIMIT` empty cycles (`idle`). A stopped loop launches nothing, but its state and worktrees stay as they were. Inspect it:

```sh
10km status
msm loop get
msm issue list '{"status": "open", "severity": "blocking"}'
msm session list '{"status": "expired"}'
msm task list '{"status": "rejected"}'
```

To resume (see [Interacting with a loop](#interacting-with-a-loop)):

1. Answer each blocking escalation with `msm issue update <id> '{"status": "answered", "resolution": "..."}'`. If a decision needs changes to files, make them in an operator session and mark it done, or create a backlog item for them.
2. `msm loop resume`. msm refuses it while a blocking operator escalation is still open; answered ones don't count.

The next Curator merges any operator sessions, then the loop carries on from its phase, and the roles that raised the escalations act on your answers.
