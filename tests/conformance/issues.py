"""Conformance map: Issues. See tests/conformance.py."""
SECTION = "Issues"

RR = "tests/test_requirements_roles.py:"

MAP = {
    "R174": [RR + "TestIssueTypes.test_issues_are_escalations_or_backlog_items",
             ("prompts/common.md", "Issues are escalations (a request for help or a decision) "
                                   "or backlog items (work for later)")],
    "R175": [("prompts/common.md", "`branch`: the branch holding unmerged work (expired, "
                                   "incomplete or rejected), if any."),
             "tests/test_scenarios.py:TestExpiry."
             "test_hanging_worker_is_expired_its_work_backlogged_and_the_loop_goes_on",
             "tests/test_scenarios.py:TestRejection."
             "test_branch_failing_validation_is_rejected_and_backlogged"],
}

PENDING = set()
