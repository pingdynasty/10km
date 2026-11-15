"""Conformance map: Dispatcher (with Session Time-out and Resume). See tests/conformance.py."""
SECTION = "Dispatcher"

D = "tests/test_scripts.py:TestDispatchScript."
L = "tests/test_loop.py:TestDispatch."
A = "tests/test_loop.py:TestAuditorDue."
RD = "tests/test_requirements_dispatch.py:"
SC = "tests/test_scenarios.py:"
LAUNCHES = D + "test_launches_agent_with_prompt_handle_and_environment"
TIME_OUT = D + "test_time_out_sends_sigterm_first_and_relaunches_the_role"
STOP_RESUME = SC + "TestStopAndResume.test_stop_mid_cycle_then_resume_continues_the_same_cycle"
DEAD_PLANNER = SC + "TestExpiry.test_dead_planner_is_relaunched_until_it_succeeds"
CURATOR_CRASH = RD + "TestCuratorCrash.test_a_pass_cut_short_is_redone_by_the_next_curator"

MAP = {
    "R136": RD + "TestDispatchRules.test_run_loop_dispatches_every_interval",
    "R137": [D + "test_stopped_loop_launches_nothing", LAUNCHES],
    "R138": [TIME_OUT, STOP_RESUME],
    "R139": [D + "test_stopped_loop_launches_nothing",
             L + "test_stopped_loop_starts_nothing_and_notifies_nothing"],
    "R140": [D + "test_contributions_get_a_curator_in_any_phase",
             RD + "TestDispatchRules.test_done_auditor_gets_a_curator_in_the_execute_phase"],
    "R141": LAUNCHES,
    "R142": D + "test_workers_up_to_max_then_as_slots_free",
    "R143": RD + "TestDispatchRules.test_curate_phase_launches_a_curator_without_waiting",
    "R144": [D + "test_workers_up_to_max_then_as_slots_free",
             D + "test_rerun_launches_nothing_twice"],
    "R145": [A + "test_daily_time_in_timezone",
             A + "test_missed_trigger_from_yesterday_is_due_after_midnight",
             A + "test_cycle_limit",
             "tests/test_requirements_loop.py:TestDispatchRoles."
             "test_dispatcher_launches_an_auditor_when_due"],
    "R146": RD + "TestAuditorTriggers.test_either_trigger_can_be_disabled",
    "R147": A + "test_never_before_first_curated_cycle",
    "R148": [RD + "TestLaunching.test_taken_branch_name_is_tried_three_times", LAUNCHES],
    "R149": [RD + "TestLaunching.test_taken_branch_name_is_tried_three_times",
             D + "test_taken_branch_names_are_retried_then_given_up"],
    "R150": LAUNCHES,
    "R151": [LAUNCHES, L + "test_launches_curator_with_handle_and_prompt"],
    "R152": RD + "TestLaunching.test_launcher_is_configured_for_the_loop",
    "R153": [LAUNCHES, "tests/test_requirements_loop.py:TestCentralConfig."
             "test_agent_command_per_role_falls_back_to_loop_agent"],
    "R154": "tests/test_requirements_loop.py:TestCentralConfig."
            "test_agent_command_per_role_falls_back_to_loop_agent",
    # Session Time-out
    "R155": [TIME_OUT, L + "test_times_out_and_kills_agent",
             SC + "TestExpiry."
             "test_hanging_worker_is_expired_its_work_backlogged_and_the_loop_goes_on"],
    "R156": RD + "TestDispatchRules.test_operator_sessions_never_time_out",
    "R157": [TIME_OUT, D + "test_agent_ignoring_sigterm_is_killed"],
    "R158": L + "test_unstoppable_sessions_are_expired_with_an_escalation",
    "R159": [D + "test_agent_that_died_is_expired_after_the_start_grace",
             L + "test_dead_agent_is_expired_after_start_grace"],
    "R160": [RD + "TestSessionScriptRules."
             "test_sessions_not_launched_by_the_dispatcher_have_no_handle",
             L + "test_session_without_handle_only_times_out"],
    # Notes
    "R161": [DEAD_PLANNER, TIME_OUT,
             "tests/test_scripts.py:TestSessionScript."
             "test_crash_after_the_record_is_recovered_by_the_dispatcher"],
    "R162": [DEAD_PLANNER, TIME_OUT],
    "R163": "tests/test_msm.py:MsmTest.test_expired_planner_cycle_is_replaced",
    "R164": [CURATOR_CRASH, "tests/test_curate_scripts.py:TestRefusals."
             "test_curator_expired_mid_pass_removes_nothing"],
    "R165": [CURATOR_CRASH, "tests/test_curate_scripts.py:TestFullPass."
             "test_every_step_twice_in_a_row_gives_the_same_result"],
    "R166": "tests/test_curate_scripts.py:TestPrepare."
            "test_removes_old_curators_and_closed_cycle_sessions",
    "R167": RD + "TestDispatchRules.test_curate_phase_launches_a_curator_without_waiting",
    "R168": DEAD_PLANNER,
    # Resume
    "R169": [STOP_RESUME, "tests/test_msm.py:MsmTest.test_agents_cannot_restart_a_stopped_loop"],
    "R170": STOP_RESUME,
    "R172": STOP_RESUME,
    "R173": [STOP_RESUME, "tests/test_msm.py:MsmTest.test_stop_and_resume"],
}

# R171 (the operator resolves blocking escalations or updates the goals before
# resuming) is the operator's own judgement: nothing enforces it, and it is stated
# in README.md, which the map can't cite.
PENDING = {"R171"}
