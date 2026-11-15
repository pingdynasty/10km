"""Conformance map: State Machine (with Side effects, Callers, Role Preconditions,
State and Phase Transitions). See tests/conformance.py."""
SECTION = "State Machine"

M = "tests/test_msm.py:MsmTest."
RM = "tests/test_requirements_msm.py:"
S = "tests/test_scripts.py:"

FIELDS = RM + "TestResults.test_records_have_the_fields_of_the_state_block"
LIST_UPDATE_REMOVE = RM + "TestCycles.test_list_update_and_remove"
REPLACED = ("tests/test_requirements_roles.py:TestReplacedCycleCount."
            "test_a_replaced_cycle_does_not_count_as_an_idle_cycle")
SESSION_CALLS = RM + "TestSessions.test_update_get_and_list_with_a_filter"

MAP = {
    "R36": RM + "TestTransactions.test_a_failing_call_changes_nothing",
    "R37": RM + "TestTransactions.test_msm_touches_only_the_database",
    "R38": RM + "TestTransactions.test_msm_touches_only_the_database",
    # Commands
    "R39": RM + "TestInit.test_init_sets_counters_phase_curate_and_stopped",
    "R40": [M + "test_stop_and_resume", RM + "TestLoopRecord.test_start_clears_reason_and_goes_to_plan"],
    "R41": [M + "test_stop_and_resume", RM + "TestLoopRecord.test_stop_sets_stopped_and_reason"],
    "R42": M + "test_stop_and_resume",
    "R43": RM + "TestLoopRecord.test_update_changes_fields_but_not_the_protected_ones",
    "R44": M + "test_full_cycle",
    "R45": SESSION_CALLS,
    "R46": SESSION_CALLS,
    "R47": SESSION_CALLS,
    "R48": M + "test_full_cycle",
    "R49": M + "test_remove_worker_returns_task",
    "R50": [M + "test_full_cycle", LIST_UPDATE_REMOVE],
    "R51": [M + "test_full_cycle", M + "test_cycle_curate_sets_verdicts_and_closed_cycle_is_frozen"],
    "R52": M + "test_remove_worker_returns_task",
    "R53": M + "test_full_cycle",
    "R54": LIST_UPDATE_REMOVE,
    "R55": [M + "test_issues", RM + "TestIssuesAndAudits.test_issue_get_and_update",
            RM + "TestIssuesAndAudits.test_audit_create_get_list_update_remove"],
    "R56": RM + "TestResults.test_create_returns_the_resource_and_errors_are_json",
    "R57": [M + "test_issues", SESSION_CALLS],
    "R58": [SESSION_CALLS, RM + "TestIssuesAndAudits.test_issue_get_and_update"],
    "R59": [RM + "TestIssuesAndAudits.test_issue_get_and_update",
            RM + "TestIssuesAndAudits.test_audit_create_get_list_update_remove"],
    "R60": [M + "test_issues", SESSION_CALLS],
    "R61": RM + "TestLoopRecord.test_update_changes_fields_but_not_the_protected_ones",
    # Exit status
    "R62": M + "test_preconditions",
    "R63": M + "test_preconditions",
    "R64": M + "test_preconditions",
    "R65": M + "test_preconditions",
    # Side effects
    "R66": RM + "TestWorkerSideEffects.test_creating_a_worker_claims_the_first_waiting_task",
    "R67": RM + "TestWorkerSideEffects.test_done_or_expired_worker_sets_its_task_and_done_at",
    "R68": [M + "test_remove_worker_returns_task",
            RM + "TestWorkerSideEffects.test_removing_an_active_worker_returns_its_task"],
    "R69": [M + "test_preconditions",
            RM + "TestCycles.test_create_needs_plan_phase_and_a_running_loop"],
    "R70": RM + "TestCycles.test_create_sets_id_status_planned_at_and_task_fields",
    "R71": [M + "test_expired_planner_cycle_is_replaced", REPLACED],
    "R72": [RM + "TestCycles.test_empty_cycles_counts_consecutive_empty_cycles", REPLACED],
    "R73": M + "test_cycle_curate_sets_verdicts_and_closed_cycle_is_frozen",
    "R74": RM + "TestLoopRecord.test_start_clears_reason_and_goes_to_plan",
    "R75": [M + "test_stop_and_resume", RM + "TestLoopRecord.test_resume_outside_plan_keeps_the_phase"],
    "R76": [M + "test_stop_and_resume", RM + "TestLoopRecord.test_stop_sets_stopped_and_reason"],
    "R77": RM + "TestLoopRecord.test_status_changes_update_updated_at",
    "R78": RM + "TestSessions.test_expired_session_cannot_be_set_to_done",
    "R79": M + "test_cycle_curate_sets_verdicts_and_closed_cycle_is_frozen",
    "R80": RM + "TestCycles.test_create_sets_id_status_planned_at_and_task_fields",
    "R81": RM + "TestCycles.test_curate_sets_curated_at_report_and_closes",
    "R82": RM + "TestCycles.test_create_sets_id_status_planned_at_and_task_fields",
    "R83": M + "test_full_cycle",
    "R84": RM + "TestIssuesAndAudits.test_audit_create_get_list_update_remove",
    "R85": RM + "TestInit.test_init_sets_counters_phase_curate_and_stopped",
    # Callers
    "R86": S + "TestDispatchScript.test_launches_agent_with_prompt_handle_and_environment",
    "R87": M + "test_expired_or_removed_caller_cannot_change_state",
    "R88": M + "test_agents_cannot_restart_a_stopped_loop",
    "R89": [M + "test_changes_are_appended_to_the_action_log",
            "tests/test_requirements_loop.py:TestStatePaths."
            "test_database_and_action_log_are_at_the_configured_paths"],
    # Role preconditions
    "R90": [M + "test_preconditions", M + "test_stop_and_resume"],
    "R91": [M + "test_curator_runs_in_any_phase_for_contributions", M + "test_preconditions"],
    "R92": M + "test_full_cycle",
    "R93": M + "test_audits_and_auditor_naming",
    "R94": RM + "TestSessions.test_operator_sessions_need_no_precondition",
    # State
    "R95": FIELDS,
    "R96": FIELDS,
    "R97": FIELDS,
    "R98": FIELDS,
    "R99": FIELDS,
    "R100": FIELDS,
    "R101": RM + "TestCycles.test_create_and_curate_inputs_are_checked",
    "R102": [RM + "TestCycles.test_create_and_curate_inputs_are_checked",
             M + "test_cycle_curate_sets_verdicts_and_closed_cycle_is_frozen"],
    "R103": RM + "TestTransactions.test_a_failing_call_changes_nothing",
    "R104": FIELDS,
    "R105": RM + "TestCycles.test_empty_cycles_counts_consecutive_empty_cycles",
    "R106": LIST_UPDATE_REMOVE,
    "R107": ("prompts/common.md", "Only the operator decides when cycles, tasks, audits and "
                                  "issues are archived or removed, and may delegate this"),
    "R108": LIST_UPDATE_REMOVE,
    # Phase transitions
    "R109": [M + "test_full_cycle", M + "test_empty_cycle_goes_to_curate"],
    "R110": M + "test_full_cycle",
    "R111": [M + "test_full_cycle", M + "test_curator_runs_in_any_phase_for_contributions"],
    "R112": [M + "test_preconditions", RM + "TestLoopRecord.test_start_clears_reason_and_goes_to_plan"],
    "R113": [M + "test_stop_and_resume", RM + "TestLoopRecord.test_resume_outside_plan_keeps_the_phase"],
}

PENDING = set()
