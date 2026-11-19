"""Conformance map: Create. See tests/conformance.py."""
SECTION = "Create"

C = "tests/test_create.py:TestCreate."

MAP = {
    "R339": [C + "test_clones_onto_the_loops_own_branch", C + "test_refusals",
             C + "test_a_full_image_updates_through_local",
             C + "test_a_shallow_image_updates_through_origin"],
    "R340": [C + "test_clones_onto_the_loops_own_branch",
             C + "test_source_without_origin_gives_only_local",
             C + "test_a_full_image_updates_through_local",
             C + "test_a_shallow_image_updates_through_origin"],
    "R341": [C + "test_writes_host_env_and_initialises", C + "test_without_an_agent_says_so"],
}
