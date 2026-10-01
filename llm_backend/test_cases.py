"""
test_cases.py
-------------
Curated evaluation dataset for the LLM instruction parser.
Each test case has a natural language instruction, expected ground truth,
and a use case category label.

Categories:
    simple          - Straightforward single-action instructions
    spatial         - Instructions involving positional relationships
    synonym         - Words that map to valid actions (grab, drop, find...)
    multi_step      - Instructions implying a sequence of actions
    ambiguous       - Unclear or underspecified instructions
    edge_case       - Empty, vague, unknown objects, malformed input

Usage:
    from test_cases import TEST_CASES, get_cases_by_category
"""

from typing import Optional
from dataclasses import dataclass, field


@dataclass
class TestCase:
    id: str
    instruction: str
    category: str
    expected_action: str
    expected_object: str
    expected_destination: Optional[str] = None
    expected_spatial: Optional[str] = None
    expected_confidence: str = "high"
    description: str = ""


TEST_CASES: list[TestCase] = [

    # ── SIMPLE ────────────────────────────────────────────────────────────────
    TestCase(
        id="S01",
        instruction="pick up the red block",
        category="simple",
        expected_action="pick",
        expected_object="red block",
        expected_confidence="high",
        description="Basic pick with colour",
    ),
    TestCase(
        id="S02",
        instruction="locate the yellow block",
        category="simple",
        expected_action="locate",
        expected_object="yellow block",
        expected_confidence="high",
        description="Basic locate",
    ),
    TestCase(
        id="S03",
        instruction="place the blue cube in the left tray",
        category="simple",
        expected_action="place",
        expected_object="blue cube",
        expected_destination="left tray",
        expected_spatial="in",
        expected_confidence="high",
        description="Place with destination and spatial",
    ),
    TestCase(
        id="S04",
        instruction="move the green block to the right tray",
        category="simple",
        expected_action="move",
        expected_object="green block",
        expected_destination="right tray",
        expected_confidence="high",
        description="Move with destination",
    ),
    TestCase(
        id="S05",
        instruction="find the blue block",
        category="simple",
        expected_action="locate",
        expected_object="blue block",
        expected_confidence="high",
        description="Find maps to locate",
    ),

    # ── SPATIAL ───────────────────────────────────────────────────────────────
    TestCase(
        id="SP01",
        instruction="move the green block to the right of the workstation",
        category="spatial",
        expected_action="move",
        expected_object="green block",
        expected_destination="workstation",
        expected_spatial="right of",
        expected_confidence="high",
        description="Right-of spatial relation",
    ),
    TestCase(
        id="SP02",
        instruction="place the red block to the left of the blue block",
        category="spatial",
        expected_action="place",
        expected_object="red block",
        expected_destination="blue block",
        expected_spatial="left of",
        expected_confidence="high",
        description="Left-of with another object as reference",
    ),
    TestCase(
        id="SP03",
        instruction="put the yellow block near the workstation",
        category="spatial",
        expected_action="place",
        expected_object="yellow block",
        expected_destination="workstation",
        expected_spatial="near",
        expected_confidence="high",
        description="Near spatial relation",
    ),
    TestCase(
        id="SP04",
        instruction="move the blue cube on top of the right tray",
        category="spatial",
        expected_action="move",
        expected_object="blue cube",
        expected_destination="right tray",
        expected_spatial="on top of",
        expected_confidence="high",
        description="On-top-of spatial relation",
    ),
    TestCase(
        id="SP05",
        instruction="place the green block next to the red block",
        category="spatial",
        expected_action="place",
        expected_object="green block",
        expected_destination="red block",
        expected_spatial="next to",
        expected_confidence="high",
        description="Next-to spatial relation",
    ),

    # ── SYNONYM ───────────────────────────────────────────────────────────────
    TestCase(
        id="SY01",
        instruction="grab the red block",
        category="synonym",
        expected_action="pick",
        expected_object="red block",
        expected_confidence="medium",
        description="Grab maps to pick",
    ),
    TestCase(
        id="SY02",
        instruction="drop the blue cube in the left tray",
        category="synonym",
        expected_action="place",
        expected_object="blue cube",
        expected_destination="left tray",
        expected_confidence="medium",
        description="Drop maps to place",
    ),
    TestCase(
        id="SY03",
        instruction="transfer the green block to workstation A",
        category="synonym",
        expected_action="move",
        expected_object="green block",
        expected_destination="workstation",
        expected_confidence="medium",
        description="Transfer maps to move",
    ),
    TestCase(
        id="SY04",
        instruction="search for the yellow block",
        category="synonym",
        expected_action="locate",
        expected_object="yellow block",
        expected_confidence="medium",
        description="Search maps to locate",
    ),
    TestCase(
        id="SY05",
        instruction="take the red block and set it down in the right tray",
        category="synonym",
        expected_action="pick",
        expected_object="red block",
        expected_destination="right tray",
        expected_confidence="medium",
        description="Take+set maps to pick+place",
    ),

    # ── MULTI-STEP ────────────────────────────────────────────────────────────
    TestCase(
        id="MS01",
        instruction="pick up the red block and place it in the left tray",
        category="multi_step",
        expected_action="pick",
        expected_object="red block",
        expected_destination="left tray",
        expected_confidence="high",
        description="Two-action instruction — parser should extract primary action",
    ),
    TestCase(
        id="MS02",
        instruction="grab the blue block then drop it near the workstation",
        category="multi_step",
        expected_action="pick",
        expected_object="blue block",
        expected_destination="workstation",
        expected_spatial="near",
        expected_confidence="medium",
        description="Then-chained two-action with synonym",
    ),
    TestCase(
        id="MS03",
        instruction="find the green block and move it to the right tray",
        category="multi_step",
        expected_action="locate",
        expected_object="green block",
        expected_destination="right tray",
        expected_confidence="high",
        description="Locate then move — primary is locate",
    ),

    # ── AMBIGUOUS ─────────────────────────────────────────────────────────────
    TestCase(
        id="AM01",
        instruction="put that thing over there",
        category="ambiguous",
        expected_action="move",
        expected_object="unknown",
        expected_destination="unknown",
        expected_confidence="low",
        description="Completely vague — no object or destination",
    ),
    TestCase(
        id="AM02",
        instruction="move it to the left",
        category="ambiguous",
        expected_action="move",
        expected_object="unknown",
        expected_spatial="left",
        expected_confidence="low",
        description="Pronoun reference — object unclear",
    ),
    TestCase(
        id="AM03",
        instruction="do something with the block",
        category="ambiguous",
        expected_action="locate",
        expected_object="block",
        expected_confidence="low",
        description="Underspecified action",
    ),

    # ── EDGE CASES ────────────────────────────────────────────────────────────
    TestCase(
        id="EC01",
        instruction="pick up the purple block",
        category="edge_case",
        expected_action="pick",
        expected_object="purple block",
        expected_confidence="low",
        description="Unknown colour not in workspace",
    ),
    TestCase(
        id="EC02",
        instruction="PICK UP THE RED BLOCK",
        category="edge_case",
        expected_action="pick",
        expected_object="red block",
        expected_confidence="high",
        description="All caps — normalisation test",
    ),
    TestCase(
        id="EC03",
        instruction="pick  up   the   red   block",
        category="edge_case",
        expected_action="pick",
        expected_object="red block",
        expected_confidence="high",
        description="Extra whitespace — normalisation test",
    ),
    TestCase(
        id="EC04",
        instruction="place the red block in workstation B",
        category="edge_case",
        expected_action="place",
        expected_object="red block",
        expected_destination="workstation B",
        expected_confidence="high",
        description="Named workstation destination",
    ),
]


def get_cases_by_category(category: str) -> list[TestCase]:
    """Return all test cases matching the given category label."""
    return [tc for tc in TEST_CASES if tc.category == category]


def get_all_categories() -> list[str]:
    """Return sorted list of unique category labels."""
    return sorted(set(tc.category for tc in TEST_CASES))


def get_case_by_id(case_id: str) -> TestCase:
    """Return a specific test case by its ID."""
    for tc in TEST_CASES:
        if tc.id == case_id:
            return tc
    raise KeyError(f"Test case '{case_id}' not found.")