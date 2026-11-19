# ten thousand monkeys

10km is a lightweight and flexible agent loop.

The Ralph loop iterates over a plan, the Karpathy loop optimises to a goal. The
Monkey loop can do either, or both: it is a generalized loop, which you can be in,
on, or outside.

In 10km, agents have four roles:
- Planner: Refines the plan into tasks
- Workers: Perform tasks
- Curator: Validates worker output
- Auditor: Inspects and improves the loop

And there's you, the operator.

You kick off a Monkey loop with goals, deliverables and a high-level plan. If you're
short on hard specs, don't worry: just tell the loop what you want it to do. You
can always change it later.

The work is done in cycles, with sessions managed by a simple but effective state
machine. You can run your own sessions in parallel, with an agent or without. The
Curator merges it all into the project, and if there are conflicts or validation
errors that it can't resolve then it notifies you.

10km is designed to run in a sandbox, and to work well with small models. The loop
can use any harness or coding agent, with cloud or local models.

## Run it in a container

The recommended way to run 10km is in a container or secure sandbox: unprivileged
user, no exposed ports, and only the directories you mount. Network egress control is
a good idea.

```sh
docker build -t 10km .            # add your agent harness to the Dockerfile first
mkdir central
docker run -d --name 10km -v "$PWD/central:/loop/central" -v 10km-data:/data 10km
docker exec -it 10km 10km kickoff
```

The central worktrees (the loop repo and the project repos) live in a host mount in
`central/`, so you can see and edit them. The database is in a volume called `10km-data`.
On first start the container creates the loop repo, `central/loop`, from its copy of
10km, then runs `run-loop`, which calls a dispatcher every `DISPATCH_INTERVAL` seconds.

## Run it on a host

### Requirements

Python 3.9+ (standard library only; an older one is refused with a message), Bash,
git 2.26+ and an agent CLI such as `pi`, `hermes`, `claude`, `codex` or `kiro-cli`.

The loop root (`LOOP_ROOT`) is a directory holding 10km, your worktrees (`central/`),
this host's settings (`host.env`) and the database (`.10km/loop.db` unless `MSM_DB`
says otherwise). If `LOOP_ROOT` isn't set, the scripts guess it from where they are.

```sh
git clone <10km or your fork> ~/10km
~/10km/bin/10km create ~/myloop --agent claude   # or kiro, codex
export LOOP_ROOT=~/myloop PATH=~/myloop/central/loop/bin:$PATH
10km kickoff                     # set up the loop with your agent
10km start                       # run the dispatcher every DISPATCH_INTERVAL seconds
```

`10km create` clones 10km into `central/loop` on a branch of the loop's own (`myloop`;
`--branch` to choose), so the loop's changes stay off `main`, and 10km's updates can be
merged from `origin` (where your 10km came from) or `local` (`~/10km`), both fetch
only. It writes `host.env` with the agent's commands, and creates the database.

`10km start` runs `run-loop` in the background; `10km pause`, `resume` and `stop`
control the loop. Or call `10km dispatch` from cron or another scheduler instead.

Remember that the monkeys may use and abuse any tools you give them access to. It
would be a mistake not to give them a sandbox.

## Kickoff

`10km kickoff` sets up the loop with you: goals, deliverables and plan, the project
repos in `central/`, gates, notifications and prompts. It ends by asking whether to
start the loop (`10km start`): the first Planner runs. `10km kickoff -- "<instructions>"`
does it in one shot, and leaves starting to you.

## Some Commands

```
10km create <dir> [--agent NAME] a new loop, from this 10km checkout
10km kickoff [-- message]       set up the loop
10km status                     status report
10km start                      start the dispatcher; start or resume the loop
10km pause|resume               stop or continue the loop
10km stop [--now]               stop the loop and the dispatcher (--now: and the agents)
10km dispatch                   launch any agents that are due
10km session start <username> [--no-agent] [-- instruction]
                                start an operator session
10km session create <role> [username]
                                create a session (prints JSON)
10km session done <name>        mark a session done
10km doctor                     check that the loop is healthy
10km msm ...                    the state machine
```

```sh
msm loop stop <reason>      # stop the loop but let running agents finish
msm loop resume             # continue a stopped loop
```

Configuration, escalations, backlog items, operator sessions, metrics and
recovering from a stop are in [docs/usage.md](docs/usage.md).

The requirements are in [docs/requirements.md](docs/requirements.md); testing and
contributing in [docs/contributing.md](docs/contributing.md).
