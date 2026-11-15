"""Conformance map: Agent Files. See tests/conformance.py."""
SECTION = "Agent Files"

K = "prompts/kickoff.md"

MAP = {
    "R285": (K, "Agree what files agents may produce (research notes, reports, logs)"),
    "R286": (K, "and where (repo, directory, committed or scratch). Record it in "
                "`prompts/common.md`."),
}

PENDING = set()
