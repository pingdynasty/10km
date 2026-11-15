# Kickoff

Run once, after `init`, as an operator session:

    session operator <username>        # prints the session, with its directory

In the session's loop worktree, set the goals, deliverables and high-level plan,
adapt the role prompts and config.env to the project, and commit. Then:

    msm session done <session>
    msm loop start

The first Curator merges the kickoff work, then the first Planner runs.
