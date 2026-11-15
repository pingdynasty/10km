"""Conformance map: Kickoff. See tests/conformance.py."""
SECTION = "Kickoff"

K = "prompts/kickoff.md"
T = "tests/test_requirements_auditor.py:TestKickoff"

MAP = {
    "R287": [f"{T}.test_kickoff_creates_the_database_and_runs_in_central_without_a_session",
             (K, "once, before it starts. The operator started you with `10km kickoff`")],
    "R288": [f"{T}.test_kickoff_is_interactive_or_one_shot",
             (K, "`10km kickoff` (interactive), or with `-- <message>` holding their "
                 "instructions (one-shot")],
    "R289": [f"{T}.test_kickoff_creates_the_database_and_runs_in_central_without_a_session",
             (K, "there is no session. You work directly in the central worktrees")],
    "R290": f"{T}.test_kickoff_creates_the_database_and_runs_in_central_without_a_session",
    "R291": [(K, "Write `GOALS.md` (what the loop is for, with numbered deliverables"),
             (K, "Commit straight to each repo's main branch.")],
    "R292": (K, "`tenkm.mainBranch`: the branch the loop merges into"),
    "R293": (K, "then clone, copy or create each one in `central/<name>`. For each repo, "
                "set with `git config` in that repo"),
    "R294": (K, "Adapt `prompts/*.md` to the project"),
    "R295": (K, "leave them clean and on their main branch"),
    "R296": (K, "Then `msm loop start`: the first Planner runs."),
}

PENDING = set()
