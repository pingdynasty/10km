"""Conformance map: Prompts. See tests/conformance.py."""
SECTION = "Prompts"

MAP = {
    "R283": ["prompts/planner.md", "prompts/worker.md", "prompts/curator.md",
             "prompts/auditor.md", "prompts/kickoff.md",
             ("prompts/session.md", "You are the operator's agent in a 10km operator session"),
             ("prompts/status.md", "You write a status report on this 10km loop"),
             ("prompts/escalation.md", "An escalation asks another role, or the operator, "
                                       "for help or a decision"),
             "tests/test_requirements_dispatch.py:TestSessionScriptRules."
             "test_operator_sessions_are_interactive_or_one_shot"],
    "R284": [("prompts/kickoff.md", "Adapt `prompts/*.md` to the project"),
             ("prompts/auditor.md", "update role prompts")],
}

PENDING = set()
