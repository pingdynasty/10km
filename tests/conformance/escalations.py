"""Conformance map: Escalations. See tests/conformance.py."""
SECTION = "Escalations"

E = "prompts/escalation.md"

MAP = {
    "R176": [(E, "Any role may escalate to the Planner, Curator or Auditor."),
             ("prompts/common.md", "read `prompts/escalation.md`")],
    "R177": (E, "Only the Planner, Curator and Auditor escalate to the operator"),
    "R178": (E, "`description`, in this order: what is needed, the context (why the loop "
                "can't settle it, with evidence: commits, logs, test names), the options, "
                "and your recommendation."),
}

PENDING = set()
