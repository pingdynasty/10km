"""Conformance map: Scripts and Actions. See tests/conformance.py."""
SECTION = "Scripts and Actions"

S = "tests/test_scripts.py:"
L = "tests/test_loop.py:"
RL = "tests/test_requirements_loop.py:"

MAP = {
    "R5": ("prompts/kickoff.md", "You set up a new loop with the operator, once, before it starts."),
    "R6": [S + "TestDispatchScript.test_launches_agent_with_prompt_handle_and_environment",
           L + "TestDispatch.test_launches_curator_with_handle_and_prompt",
           S + "TestDispatchScript.test_workers_up_to_max_then_as_slots_free",
           "tests/test_requirements_auditor.py:TestAuditorLaunch."
           "test_auditor_is_launched_with_its_session_name_and_prompt"],
    "R7": S + "TestSessionScript.test_creates_record_directory_branch_and_worktree_per_repo",
    "R8": L + "TestNotify.test_default_appends_to_notifications_file",
    "R9": [("prompts/common.md", "Issues are escalations (a request for help or a decision)"),
           "tests/test_msm.py:MsmTest.test_issues"],
    "R10": [RL + "TestStatus.test_report_shows_loop_cycle_sessions_and_issues",
            RL + "TestStatus.test_report_times_are_local_and_elapsed",
            RL + "TestStatus.test_empty_cycles_plural",
            "tests/test_timefmt.py:TestFormat.test_clock_today_other_day_other_year",
            "tests/test_timefmt.py:TestFormat.test_elapsed",
            "tests/test_timefmt.py:TestParse.test_iso_utc_and_git_offset_are_the_same_instant"],
}

PENDING = set()
