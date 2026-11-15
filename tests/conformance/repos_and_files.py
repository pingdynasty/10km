"""Conformance map: Git Repositories and File System (with Configuration).
See tests/conformance.py."""
SECTION = "Git Repositories and File System"

S = "tests/test_scripts.py:"
L = "tests/test_loop.py:"
C = "tests/test_curate.py:"
RL = "tests/test_requirements_loop.py:"
TWO_REPOS = ("tests/test_scenarios_more.py:TestTwoProjectRepos."
             "test_worker_commits_in_both_repos_are_merged")

MAP = {
    "R11": [L + "TestInit.test_init_registers_central_repos_and_rerun_is_safe", TWO_REPOS],
    "R12": ("prompts/auditor.md", "Your loop worktree holds the prompts, scripts, plan, goals, "
                                  "deliverables, BACKLOG.md and LEARNINGS.md."),
    "R13": RL + "TestStatePaths.test_database_and_action_log_are_at_the_configured_paths",
    "R14": [RL + "TestCentralConfig.test_scripts_read_config_env_from_the_central_loop_worktree",
            L + "TestConfig.test_environment_overrides_config"],
    "R15": RL + "TestCentralConfig.test_scripts_read_config_env_from_the_central_loop_worktree",
    "R16": [("prompts/kickoff.md", "then clone, copy or create each one in `central/<name>`"),
            TWO_REPOS],
    "R17": ("prompts/kickoff.md", "then clone, copy or create each one in `central/<name>`"),
    "R18": [S + "TestSessionScript.test_creates_record_directory_branch_and_worktree_per_repo",
            S + "TestGateScript.test_gate_runs_in_the_session_worktree_with_scratch_dir"],
    "R19": [L + "TestInit.test_init_registers_central_repos_and_rerun_is_safe",
            C + "TestEdgeCases.test_main_branch_is_recorded_not_guessed"],
    "R20": [C + "TestContributionPass.test_operator_work_reaches_main_and_session_is_removed",
            TWO_REPOS],
    "R21": ("prompts/curator.md", "Of expired sessions, add complete work (unless its conflicts "
                                  "aren't worth it); backlog or discard the rest."),
    "R22": C + "TestContributionPass.test_operator_work_reaches_main_and_session_is_removed",
    "R23": [S + "TestSessionScript.test_creates_record_directory_branch_and_worktree_per_repo",
            S + "TestSessionScript.test_names_follow_role_cycle_and_counters", TWO_REPOS],
    "R24": [RL + "TestCommitTrailer.test_commits_carry_a_loop_session_trailer",
            "tests/test_init.py:InitHooksTest."
            "test_session_worktree_sets_hooks_path_and_central_does_not",
            "tests/test_init.py:InitHooksTest.test_chains_to_inherited_hooks"],
    "R25": [RL + "TestCommitTrailer.test_commits_carry_a_loop_session_trailer",
            ("prompts/common.md", "Commits get a `Loop-Session:` trailer from the commit hook")],
    "R26": ["tests/test_requirements_roles.py:TestHarnessSessionName."
            "test_agent_sessions_are_named_after_the_loop_session",
            "tests/test_requirements_roles.py:TestHarnessSessionName."
            "test_operator_sessions_are_named_and_kickoff_is_not",
            "tests/test_metrics_e2e.py:TestMetricsOfACuratedLoop."
            "test_metrics_report_every_session_of_a_curated_cycle"],
    # Configuration
    "R27": [RL + "TestStatePaths.test_database_and_action_log_are_at_the_configured_paths",
            "tests/test_requirements_roles.py:TestStatePathSettings.test_defaults_are_unchanged",
            "tests/test_requirements_roles.py:TestStatePathSettings."
            "test_config_env_paths_reach_agents_and_this_process"],
    "R28": [RL + "TestCentralConfig.test_agent_command_per_role_falls_back_to_loop_agent",
            S + "TestDispatchScript.test_launches_agent_with_prompt_handle_and_environment"],
    "R29": L + "TestConfig.test_environment_overrides_config",
    "R30": S + "TestDispatchScript.test_workers_up_to_max_then_as_slots_free",
    "R31": [L + "TestAuditorDue.test_daily_time_in_timezone",
            L + "TestAuditorDue.test_cycle_limit"],
    "R32": ("prompts/curator.md", "`empty_cycles` at `IDLE_CYCLE_LIMIT`"),
    "R33": ("prompts/planner.md", "when the open backlog reaches `BACKLOG_SIZE` from `config.env`"),
    "R34": S + "TestGateScript.test_tiers_read_their_own_setting",
    "R35": L + "TestNotify.test_commands_get_variables_and_keys_send_once",
}

PENDING = set()
