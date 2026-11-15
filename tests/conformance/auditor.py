"""Conformance map: Auditor. See tests/conformance.py."""
SECTION = "Auditor"

A = "prompts/auditor.md"
T = "tests/test_requirements_auditor.py"

MAP = {
    "R260": f"{T}:TestAuditorLaunch.test_auditor_is_launched_with_its_session_name_and_prompt",
    "R261": (A, "Read your session (`msm session get <session>`)"),
    "R262": [f"{T}:TestAuditorLaunch.test_auditor_is_launched_with_its_session_name_and_prompt",
             (A, "the last audit (`msm audit list`, highest id)")],
    "R263": (A, "the last audit (`msm audit list`, highest id), LEARNINGS.md"),
    "R264": (A, "and open escalations (`msm issue list '{\"type\":\"escalation\",\"status\":\"open\"}'`)"),
    "R265": (A, "Commits per session: `git log --since=<from>"),
    "R266": (A, "Time per role and cycle: commit times"),
    "R267": (A, "Harness metrics (tokens, credits), if the harness records them per session."),
    "R268": (A, "Prompt sizes and growth: `wc -c prompts/*.md`"),
    "R269": (A, "Progress against the goals, deliverables and plan."),
    "R270": (A, "Expired tasks (`msm task list '{\"status\":\"expired\"}'`), recurring ones, "
                "and long-running or expired sessions"),
    "R271": (A, "trim files that grew too large by summarising, culling or archiving"),
    "R272": (A, "remove branches merged into main (`git branch --merged main`)"),
    "R273": (A, "update role prompts"),
    "R274": (A, "the Planner to make smaller or bigger tasks or use fewer or more workers"),
    "R275": (A, "the Curator to relax or tighten validation"),
    "R276": (A, "clarify definitions of done for deliverables, milestones and goals"),
    "R277": (A, "add scripts to bin/ that automate common agent tasks"),
    "R278": (A, "Resolve open escalations you can answer"),
    "R279": [(A, "Fix what you can and commit to your session branch"),
             (A, "For what you can't fix, create backlog items or escalations.")],
    "R280": (A, "Add to LEARNINGS.md only learnings that are general"),
    "R281": ["tests/test_msm.py:MsmTest.test_audits_and_auditor_naming",
             (A, "Store your report: `msm audit create")],
    "R282": f"{T}:TestAuditorLaunch.test_no_auditor_until_the_previous_audit_is_curated",
}

PENDING = set()
