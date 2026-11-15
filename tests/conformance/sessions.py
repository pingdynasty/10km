"""Conformance map: Sessions. See tests/conformance.py."""
SECTION = "Sessions"

S = "tests/test_scripts.py:TestSessionScript."
D = "tests/test_scripts.py:TestDispatchScript."
RD = "tests/test_requirements_dispatch.py:"
CREATES = S + "test_creates_record_directory_branch_and_worktree_per_repo"
NAMES = S + "test_names_follow_role_cycle_and_counters"
DONE = "Finish with `msm session done <session>`"
TWO_REPOS = ("tests/test_scenarios_more.py:TestTwoProjectRepos."
             "test_worker_commits_in_both_repos_are_merged")

MAP = {
    "R114": [CREATES, D + "test_launches_agent_with_prompt_handle_and_environment"],
    "R115": CREATES,
    "R116": CREATES,
    "R117": [CREATES, TWO_REPOS],
    "R118": [CREATES, TWO_REPOS],
    # Agents set their own session done as their last step.
    "R119": [("prompts/worker.md", DONE), ("prompts/planner.md", DONE),
             ("prompts/auditor.md", DONE),
             ("prompts/curator.md", "`msm session done $LOOP_SESSION`")],
    "R120": RD + "TestSessionScriptRules.test_done_or_expired_sessions_are_inactive",
    "R121": [D + "test_time_out_sends_sigterm_first_and_relaunches_the_role",
             "tests/test_loop.py:TestDispatch.test_times_out_and_kills_agent"],
    "R122": [NAMES, CREATES,
             RD + "TestDispatchRules.test_curate_phase_launches_a_curator_without_waiting"],
    "R123": [NAMES, "tests/test_scenarios.py:TestStopAndResume."
             "test_stop_mid_cycle_then_resume_continues_the_same_cycle"],
    "R124": "tests/test_msm.py:MsmTest.test_audits_and_auditor_naming",
    "R125": [CREATES, TWO_REPOS],
    "R126": [NAMES, CREATES],
    "R127": RD + "TestSessionScriptRules.test_operator_sessions_are_interactive_or_one_shot",
    "R128": [RD + "TestSessionScriptRules.test_creation_waits_for_the_session_lock",
             NAMES],
    "R129": S + "test_precondition_failures_exit_with_msm_code_and_leave_nothing",
    "R130": [CREATES, "tests/test_curate.py:TestGitCalls."
             "test_a_pass_reads_each_repos_setup_once_for_all_its_launches"],
    "R131": [S + "test_branch_name_taken_is_eagain_and_rolls_back_other_repos",
             S + "test_git_failure_is_egit_and_rolls_back",
             "tests/test_loop.py:TestSessions.test_git_failure_rolls_back"],
    "R132": CREATES,
    "R133": S + "test_precondition_failures_exit_with_msm_code_and_leave_nothing",
    "R134": S + "test_branch_name_taken_is_eagain_and_rolls_back_other_repos",
    "R135": S + "test_git_failure_is_egit_and_rolls_back",
}

PENDING = set()
