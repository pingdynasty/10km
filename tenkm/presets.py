"""tenkm.presets: agent commands for the harnesses 10km knows (R153).

Agent commands are this host's settings: they go in host.env. There is no
default: with none set, launches fail and say so.

LOOP_AGENT runs every role, with SESSION, PROMPT_FILE and FIRST_MESSAGE set; it
must run without asking. Usage figures reach USAGE_LOG only from harnesses that
print them: Claude Code with --output-format json, kiro-cli with
--output-format stream-json. OPERATOR_AGENT runs kickoff and operator sessions,
interactively, or without asking when ONE_SHOT=1.
"""

PRESETS = {
    "claude": {
        "LOOP_AGENT": 'claude --no-session-persistence --dangerously-skip-permissions '
                      '--output-format json -n "$SESSION" -p "$FIRST_MESSAGE"',
        "OPERATOR_AGENT": 'claude ${SESSION:+-n "$SESSION"} ${ONE_SHOT:+-p} '
                          '${FIRST_MESSAGE:+"$FIRST_MESSAGE"}',
    },
    "kiro": {
        "LOOP_AGENT": 'kiro-cli chat --no-interactive --output-format stream-json '
                      '--trust-all-tools "$FIRST_MESSAGE"',
        "OPERATOR_AGENT": 'kiro-cli chat ${ONE_SHOT:+--no-interactive --trust-all-tools} '
                          '${FIRST_MESSAGE:+"$FIRST_MESSAGE"}',
    },
    "codex": {
        "LOOP_AGENT": 'codex exec "$FIRST_MESSAGE"',
        "OPERATOR_AGENT": 'codex ${ONE_SHOT:+exec} ${FIRST_MESSAGE:+"$FIRST_MESSAGE"}',
    },
    "pi": {  # pi asks no permissions; --no-approve: ignore a project's own pi config
        "LOOP_AGENT": 'pi --no-session --no-approve -n "$SESSION" -p "$FIRST_MESSAGE"',
        "OPERATOR_AGENT": 'pi ${SESSION:+-n "$SESSION"} ${ONE_SHOT:+-p} '
                          '${FIRST_MESSAGE:+"$FIRST_MESSAGE"}',
    },
    "hermes": {
        "LOOP_AGENT": 'hermes chat --oneshot --quiet --yolo -q "$FIRST_MESSAGE"',
        "OPERATOR_AGENT": 'hermes chat ${ONE_SHOT:+--oneshot --quiet --yolo} '
                          '${FIRST_MESSAGE:+-q "$FIRST_MESSAGE"}',
    },
}


def command(name, setting):
    """A preset's command for LOOP_AGENT or OPERATOR_AGENT."""
    return PRESETS[name][setting]


def host_env_lines(name):
    """host.env lines setting a preset's commands, unless the environment does."""
    lines = [f"# Agent commands: the {name} preset."]
    for setting, cmd in PRESETS[name].items():
        assert "'" not in cmd
        lines.append(f"[ -n \"${{{setting}+x}}\" ] || {setting}='{cmd}'")
    return lines
