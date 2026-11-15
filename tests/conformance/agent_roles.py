"""Conformance map: Agent Roles and Responsibilities. See tests/conformance.py."""
SECTION = "Agent Roles and Responsibilities"

MAP = {
    "R1": ("prompts/worker.md", "You carry out one task."),
    "R2": ("prompts/planner.md", "You prepare the next cycle of work."),
    "R3": ("prompts/curator.md", "You validate session work and merge accepted work into main."),
    "R4": ("prompts/auditor.md", "You inspect how the loop is working and improve it."),
}

PENDING = set()
