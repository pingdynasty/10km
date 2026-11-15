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
             "test_hanging_and_dead_workers_are_expired_their_work_backlogged",
             "tests/test_scenarios.py:TestRejection."
             "test_conflicting_and_failing_branches_are_rejected_and_backlogged"],
    "R314": [RR + "TestIssueLifecycle.test_status_goes_open_answered_resolved",
             RR + "TestIssueLifecycle.test_status_cannot_go_back"],
    "R315": RR + "TestIssueLifecycle.test_status_goes_open_answered_resolved",
    "R316": RR + "TestIssueLifecycle.test_operator_answers_operator_escalations",
    "R317": [RR + "TestIssueLifecycle.test_status_goes_open_answered_resolved",
             RR + "TestIssueLifecycle.test_assigner_role_is_set_by_msm"],
    "R318": [RR + "TestIssueLifecycle.test_assignee_may_resolve_without_answering",
             RR + "TestIssueLifecycle.test_status_cannot_go_back"],
    "R319": ["tests/test_requirements_msm.py:TestLoopRecord."
             "test_resume_is_allowed_once_the_blocking_escalation_is_answered",
             RR + "TestIssueLifecycle.test_status_cannot_go_back"],
}

PENDING = set()
