"""Conformance map: Worker. See tests/conformance.py."""
SECTION = "Worker"

W = "prompts/worker.md"

MAP = {
    "R197": "tests/test_requirements_roles.py:TestWorkerLaunch."
            "test_worker_is_launched_with_its_session_name_and_prompt",
    "R198": (W, "Read your session (`msm session get <session>`) and your task"),
    "R199": [(W, "The task's `branch` field is your base branch: the Planner's session branch "
                 "for a new task, or a backlog item's branch for a continuation."),
             (W, "In every repo worktree, including `loop`, rebase your session branch on the "
                 "base: `git rebase <base>`.")],
    "R200": (W, "Then record your branch on the task:"),
    "R201": (W, "Do the work in your worktrees and commit to your session branch."),
    "R202": [(W, "Finish with `msm session done <session>` (this also sets the task to done)."),
             "tests/test_requirements_msm.py:TestWorkerSideEffects."
             "test_done_or_expired_worker_sets_its_task_and_done_at"],
}

PENDING = set()
