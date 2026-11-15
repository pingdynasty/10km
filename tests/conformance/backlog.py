"""Conformance map: Backlog. See tests/conformance.py."""
SECTION = "Backlog"

MAP = {
    "R179": "tests/test_requirements_roles.py:TestIssueTypes."
            "test_agents_and_operators_create_backlog_items",
    "R180": ("prompts/planner.md", "Update the plan and BACKLOG.md"),
    "R181": ("prompts/planner.md", "when the open backlog reaches `BACKLOG_SIZE` from "
                                   "`config.env`, you must prioritise or prune it."),
    "R182": ("prompts/common.md", "`urgent_if`: for backlog items, the condition under which "
                                  "the item becomes urgent."),
    "R183": ("prompts/common.md", "Before creating one, search for a similar open issue"),
}

PENDING = set()
