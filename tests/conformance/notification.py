"""Conformance map: Notification. See tests/conformance.py."""
SECTION = "Notification"

MAP = {
    "R297": ["tests/test_loop.py:TestNotify.test_commands_get_variables_and_keys_send_once",
             ("prompts/kickoff.md", "**Notification.** `NOTIFY_CMD`")],
    "R298": "tests/test_loop.py:TestNotify.test_default_appends_to_notifications_file",
    "R299": "tests/test_requirements_auditor.py:TestNotification.test_notifications_file_is_gitignored",
    "R300": ["tests/test_requirements_auditor.py:TestNotification.test_routine_passes_notify_nothing",
             "tests/test_loop.py:TestDispatch.test_missing_database_is_notified",
             ("prompts/curator.md", "If there are open blocking operator escalations, "
                                    "`notify \"<title>\" \"<body>\"`"),
             ("prompts/kickoff.md", "The loop notifies only blocking escalations and fatal "
                                    "errors unless the operator wants more")],
}

PENDING = set()
