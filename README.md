# ten thousand monkeys

10km is a lightweight and flexible agent loop.

The Ralph loop iterates over a plan, the Karpathy loop optimises to a goal. The
Monkey loop can do either, or both: it is a generalized loop, which you can be in,
on, or outside.

In 10km, monkey agents have four roles:
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
Curator merges it all into the project, and if there are conflicts it can't resolve
then it notifies you.

10km is designed to run in a sandbox, and to work well with small models. The loop
can use any harness or coding agent, with local or remote models. You can interfere 
with the monkeys at any time.

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

10km requires Python 3.9+ (standard library only), Bash, git 2.26+ and an agent
CLI such as `pi`, `hermes`, `claude`, `codex` or `kiro-cli`. The loop root (`LOOP_ROOT`)
is a directory holding 10km, your worktrees (`central/`) and the database (`.10km/loop.db`
unless `MSM_DB` says otherwise).

```sh
mkdir -p ~/myloop/central && cd ~/myloop
git clone <10km or your fork> central/loop
export LOOP_ROOT=~/myloop PATH=~/myloop/central/loop/bin:$PATH
10km kickoff                     # create the database and set up the loop
run-loop                         # the Dispatcher every DISPATCH_INTERVAL seconds
```

Keep `run-loop` running (in `tmux`, or as a service), or call `10km dispatch` from
cron instead. Stopping `run-loop` only stops the dispatcher; start it again to carry
on. To stop the loop itself, see [Interacting with a loop](docs/usage.md#interacting-with-a-loop).

Remember that the monkeys may use and abuse any tools you give them access to. It
would be a mistake not to give them a sandbox.

## Kickoff

`10km kickoff` sets up the loop with you: goals, deliverables and plan, the project
repos in `central/`, gates, notifications and prompts. It ends by starting the loop,
and the first Planner runs. `10km kickoff -- "<instructions>"` does it in one shot.

## Commands

```
10km init                       create the database; register the central repos
10km kickoff [-- message]       set up the loop with OPERATOR_AGENT
10km status                     status report
10km metrics [--cycle N] [--json]
                                sessions, times, commits and usage per cycle and role
10km dispatch                   one Dispatcher pass
10km session start <username> [--no-agent] [-- message]
                                start an operator session
10km session create <role> [username]
                                create a session (prints JSON)
10km session done <name>        mark a session done
10km notify <title> [body] [--priority critical|default|passive] [--key K]
10km doctor                     check that the loop can run
10km launch-test [role] [--timeout SECONDS]
                                launch a trivial agent outside the loop state
10km gate worker|validation     run a tier's gates in the central worktrees
10km msm ...                    the state machine
```

```sh
msm loop start              # once, after kickoff: the first Planner runs
msm loop stop <reason>      # launch nothing new; running agents finish
msm loop resume             # continue a stopped loop from its phase
```

Configuration, working with a running loop (escalations, backlog items, operator
sessions), metrics, recovering from a stop and testing are in
[docs/usage.md](docs/usage.md). The requirements are in
[docs/requirements.md](docs/requirements.md).
