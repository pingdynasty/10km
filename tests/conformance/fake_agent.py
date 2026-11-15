"""Conformance map: Test Scripts (the fake agent). See tests/conformance.py."""
SECTION = "Test Scripts"

T = "tests/test_requirements_auditor.py:TestFakeAgent.test_fake_agent_plays_each_role"

MAP = {rid: T for rid in ("R301", "R304", "R305", "R306", "R307", "R308", "R309", "R310",
                          "R311")}

# R302, R303: tests/fake-agent picks its behaviour per session from FAKE_* settings;
# it reads no script of items and runs no 'verify' items. Raised with the Curator.
PENDING = {"R302", "R303"}
