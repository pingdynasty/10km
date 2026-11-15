"""Conformance map: Escalations. See tests/conformance.py."""
SECTION = "Escalations"

MAP = {
    "R176": ("prompts/common.md", "Any role may escalate to the planner, curator or auditor."),
    "R177": ("prompts/common.md", "Only the planner, curator and auditor may escalate to the "
                                  "operator."),
    "R178": ("prompts/common.md", "An operator escalation states what is needed from the "
                                  "operator, the options, and your recommendation."),
}

PENDING = set()
