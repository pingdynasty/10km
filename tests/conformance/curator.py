"""Conformance map: Curator. See tests/conformance.py.

Steps run by the agent (Triage to Assess, Exit) map to the prompt phrase that
carries them, and to the scenario or script tests where the fake agent or a test
plays them through the scripts."""
SECTION = "Curator"

P = "prompts/curator.md"
CS = "tests/test_curate_scripts.py:"
C = "tests/test_curate.py:"
RC = "tests/test_requirements_curator.py:"
SC = "tests/test_scenarios.py:"

STEPS = RC + "TestPromptSteps.test_the_prompt_runs_eleven_steps_in_order_calling_the_scripts"
FULL_PASS = CS + "TestFullPass.test_every_step_twice_in_a_row_gives_the_same_result"
EXPIRED = SC + "TestExpiry.test_hanging_and_dead_workers_are_expired_their_work_backlogged"
REJECTED = SC + "TestRejection.test_conflicting_and_failing_branches_are_rejected_and_backlogged"
VALIDATE = CS + "TestValidate.test_failing_work_is_left_out_and_revalidated"
PUBLISH = CS + "TestPublish.test_fast_forwards_main_and_closes_the_cycle_with_verdicts"
CLEANUP = CS + "TestCleanup.test_removes_selected_sessions_and_reports_unpublished_work"
SELECT = CS + "TestSelect.test_contributions_first_then_the_cycle"
SM = "tests/test_scenarios_more.py:"
IDLE = SM + "TestIdleStop.test_idle_limit_of_empty_cycles_stops_the_loop"
OFF_PHASE = SM + "TestOffPhaseCurator.test_done_auditor_and_operator_work_is_curated_outside_the_curate_phase"
TWO_REPOS = SM + "TestTwoProjectRepos.test_worker_commits_in_both_repos_are_merged"

MAP = {
    "R203": [STEPS, FULL_PASS, CS + "TestRefusals.test_steps_out_of_order_are_errors"],
    "R204": STEPS,
    "R205": [CS + "TestRefusals.test_every_step_refuses_without_an_active_curator",
             CS + "TestRefusals.test_done_curator_is_refused",
             CS + "TestRefusals.test_curator_expired_mid_pass_removes_nothing",
             C + "TestRefusals.test_steps_refuse_an_inactive_curator"],
    "R206": [CS + "TestPrepare.test_keeps_branches_of_unresolved_issues",
             CS + "TestCleanup.test_keeps_branches_of_unresolved_issues"],
    # Step 1: Prepare
    "R207": [STEPS, CS + "TestPrepare.test_removes_old_curators_and_closed_cycle_sessions",
             CS + "TestPrepare.test_rerun_after_a_crash_mid_removal_finishes"],
    "R208": [C + "TestRefusals.test_prepare_removes_leftover_sessions",
             CS + "TestPrepare.test_removes_old_curators_and_closed_cycle_sessions",
             CS + "TestPrepare.test_keeps_the_open_cycles_sessions"],
    "R209": [CS + "TestPrepare.test_removes_old_curators_and_closed_cycle_sessions",
             CS + "TestPrepare.test_keeps_the_open_cycles_sessions"],
    # Step 2: Select
    "R210": [STEPS, SELECT],
    "R211": SELECT,
    "R212": [SELECT, RC + "TestSelectRoles.test_a_done_auditor_is_selected_before_the_cycle",
             OFF_PHASE],
    "R213": [SELECT, CS + "TestSelect.test_expired_workers_are_selected_too",
             RC + "TestSelectRoles.test_done_workers_are_not_selected_before_the_curate_phase"],
    "R214": [CS + "TestSelect.test_nothing_outside_the_curate_phase",
             RC + "TestSelectRoles.test_done_workers_are_not_selected_before_the_curate_phase"],
    "R215": [(P, "If it is empty, skip to step 8"),
             CS + "TestPublish.test_publishes_own_commits_with_nothing_selected"],
    # Step 3: Merge
    "R216": [STEPS, CS + "TestMerge.test_merges_sessions_and_reports_json"],
    "R217": [CS + "TestMerge.test_merges_sessions_and_reports_json", TWO_REPOS],
    "R218": [CS + "TestMerge.test_merges_sessions_and_reports_json",
             CS + "TestMerge.test_unknown_and_ambiguous_items_are_errors",
             C + "TestDeclarativeMerge.test_partial_acceptance_by_commit"],
    "R219": [CS + "TestMerge.test_merges_sessions_and_reports_json",
             CS + "TestValidate.test_curator_fix_is_kept_and_published"],
    "R220": [(P, "Always pass the full list"),
             CS + "TestMerge.test_leaving_a_session_out_rejects_its_work"],
    "R221": [CS + "TestMerge.test_leaving_a_session_out_rejects_its_work",
             C + "TestDeclarativeMerge.test_leaving_an_item_out_rebuilds_and_keeps_own_commits_and_resolutions"],
    "R222": CS + "TestMerge.test_conflict_exits_3_with_instructions_then_rerun_completes",
    "R223": [CS + "TestMerge.test_conflict_exits_3_with_instructions_then_rerun_completes",
             CS + "TestMerge.test_rerun_after_a_crash_mid_step_does_not_merge_twice",
             C + "TestDeclarativeMerge.test_agent_can_finish_the_merge_itself"],
    # Step 4: Triage
    "R224": (P, "Triage: merge the done sessions"),
    "R225": [(P, "Triage: merge the done sessions, Planner first. Of expired sessions"),
             CS + "TestSelect.test_expired_workers_are_selected_too", EXPIRED],
    "R226": [(P, "add complete work (unless its conflicts aren't worth it)"), REJECTED],
    "R227": [(P, "backlog or discard the rest"), EXPIRED,
             CS + "TestPublish.test_expired_task_needs_no_verdict"],
    # Step 5: Read
    "R228": (P, "Read the plan, goals, open escalations"),
    "R229": (P, "Read the plan, goals, open escalations (`msm issue list '{\"status\":\"open\"}'`), "
                "the cycle (`msm cycle get`) and audits since it was planned"),
    # Step 6: Evaluate
    "R230": (P, "Evaluate each included Worker session's commits and diffs"),
    "R231": (P, "against its task"),
    "R232": (P, "Evaluate each included Worker session's commits and diffs against its task and "
                "the goals"),
    "R233": [(P, "accept or reject it, in whole or in part"), REJECTED,
             C + "TestDeclarativeMerge.test_partial_acceptance_by_commit"],
    "R234": [(P, "Rerun `curate-merge` with only the accepted sessions and commits"),
             CS + "TestMerge.test_leaving_a_session_out_rejects_its_work"],
    # Step 7: Validate
    "R235": VALIDATE,
    "R236": [(P, "Validate: `gate validation`"), VALIDATE,
             "tests/test_curate.py:TestGate.test_repo_prefix_selects_repo"],
    "R237": [(P, "If a gate fails, find the responsible work"), VALIDATE],
    "R238": [(P, "commit small fixes"), CS + "TestValidate.test_curator_fix_is_kept_and_published"],
    "R239": [(P, "rerun `curate-merge` without it"), VALIDATE, REJECTED],
    "R240": [(P, "validate again"), VALIDATE],
    "R241": (P, "Escalate rejected operator work to the operator"),
    "R242": [(P, "backlog or discard other rejected work"), REJECTED,
             CS + "TestCleanup.test_keeps_branches_of_unresolved_issues"],
    # Step 8: Assess
    "R243": (P, "Assess milestones, goals and deliverables"),
    "R244": (P, "Assess milestones, goals and deliverables"),
    "R245": (P, "update the plan and backlog"),
    "R246": (P, "answer or resolve escalations you can"),
    "R247": [(P, "create a blocking operator escalation whose title starts with its reason"),
             RC + "TestIdleLimit.test_the_idle_limit_and_empty_cycle_count_the_prompt_names_exist",
             IDLE],
    "R248": (P, "If there are open blocking operator escalations, `notify"),
    # Step 9: Publish
    "R249": [STEPS, PUBLISH],
    "R250": [PUBLISH, CS + "TestPublish.test_rerun_after_a_crash_before_closing_the_cycle",
             CS + "TestPublish.test_moved_main_is_an_error_until_merge_is_rerun",
             OFF_PHASE, TWO_REPOS],
    "R251": [PUBLISH, CS + "TestPublish.test_bad_verdicts_are_errors_and_publish_nothing"],
    "R252": [PUBLISH, CS + "TestPublish.test_bad_verdicts_are_errors_and_publish_nothing"],
    "R253": CS + "TestPublish.test_publishes_own_commits_with_nothing_selected",
    # Step 10: Cleanup
    "R254": [STEPS, CLEANUP],
    "R255": [CLEANUP, CS + "TestCleanup.test_warns_about_a_dirty_central_repo", TWO_REPOS],
    "R256": [CLEANUP, CS + "TestCleanup.test_rerun_after_a_crash_mid_cleanup_finishes",
             OFF_PHASE, TWO_REPOS],
    # Step 11: Exit
    "R257": (P, "Exit: if there are open blocking operator escalations"),
    "R258": [(P, "if there are open blocking operator escalations, `msm loop stop <reason>` with the escalation's reason"), IDLE],
    "R259": [(P, "`msm session done $LOOP_SESSION`"), CLEANUP],
    "R321": (P, "answered issues raised by Curators (`msm issue list '{\"status\":\"answered\",\"assigner_role\":\"curator\"}'`)"),
}

PENDING = set()
