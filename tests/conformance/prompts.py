"""Conformance map: Prompts. See tests/conformance.py."""
SECTION = "Prompts"

MAP = {
    "R284": [("prompts/kickoff.md", "Adapt `prompts/*.md` to the project"),
             ("prompts/auditor.md", "update role prompts")],
}

# R283: there are role prompts and prompts/kickoff.md, but no Session, Status or
# Escalation prompt (10km session and 10km status take none); raised with the Curator.
PENDING = {"R283"}
