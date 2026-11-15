"""Conformance map: Planner. See tests/conformance.py."""
SECTION = "Planner"

P = "prompts/planner.md"
M = "tests/test_msm.py:MsmTest."

MAP = {
    "R184": "tests/test_scripts.py:TestDispatchScript."
            "test_launches_agent_with_prompt_handle_and_environment",
    "R185": (P, "Read your session (`msm session get <session>`)"),
    "R186": [(P, "the plan and goals, and the last curator report"),
             (P, "escalations assigned to the planner, and backlog items")],
    "R187": (P, "Read open issues (`msm issue list '{\"status\": \"open\"}'`): escalations "
                "assigned to the planner"),
    "R188": (P, "Resolve escalations you can answer"),
    "R189": (P, "Consolidate, reprioritise or prune the backlog"),
    "R190": (P, "Decide the headline: the focus of this cycle. Update the plan"),
    "R191": (P, "Plan the tasks."),
    "R192": (P, "To continue a backlog item"),
    "R193": (P, "To continue a backlog item that has a branch, rebase that branch on your "
                "session branch, use it as the task's `branch`"),
    "R194": (P, "and resolve the item."),
    "R195": [(P, "Create the cycle, with `\"tasks\": []` if there is nothing to do"),
             M + "test_full_cycle", M + "test_empty_cycle_goes_to_curate"],
    "R196": [(P, "Finish with `msm session done <session>`. This sets the phase to execute, or "
                 "to curate if the cycle has no tasks."),
             M + "test_full_cycle", M + "test_empty_cycle_goes_to_curate"],
}

PENDING = set()
