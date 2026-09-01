"""Every question type the exam prints is reachable in a generated paper.

The two lists are the official ones — ten for Listening, eleven for Reading.
A type can be documented in the system prompt, known to a validator and marked
correctly, and still never be ASKED FOR by anything the student can reach. That
is a silent gap: the set validates, the paper looks complete, and the candidate
simply never meets the type.

Reading was in exactly that state until 2026-09-02. `_passage_types` steered
only the passage carrying the figure and left the other two to the default mix,
which names nine types — so matching_sentence_endings, short_answer and
table_completion could not appear in a paper at all.
"""

from app.agents import listening_trainer as lt
from app.agents import reading_trainer as rt
from app.agents.answerability import canon

# The ten Listening prints. `map_labelling` and `diagram_label_completion` are
# one row on the official list ("Plan / Map / Diagram Labelling"); both are kept
# here because the engine draws them from different figure objects.
LISTENING_TYPES = (
    "multiple_choice",
    "matching",
    "map_labelling",
    "diagram_label_completion",
    "form_completion",
    "note_completion",
    "table_completion",
    "flow_chart_completion",
    "summary_completion",
    "sentence_completion",
    "short_answer",
)

# The eleven Reading prints. The official list groups summary/note/table/flow
# chart as one row; they are separate types to the generator, and covering the
# family is what matters, so the assertion below treats them as a group.
READING_TYPES = (
    "multiple_choice",
    "true_false_notgiven",
    "yes_no_notgiven",
    "matching_information",
    "matching_headings",
    "matching_features",
    "matching_sentence_endings",
    "sentence_completion",
    "diagram_label_completion",
    "short_answer",
)
READING_COMPLETION_FAMILY = (
    "summary_completion", "note_completion", "table_completion",
    "flow_chart_completion",
)


def _reading_steered() -> set[str]:
    """Every type a full paper can ask for, over enough papers to see the
    randomised slots."""
    return {
        canon(t)
        for _ in range(200)
        for types in rt._passage_types().values()
        for t in types
    }


def _listening_steered() -> set[str]:
    """Every type the four part specs name, including part 2's alternative."""
    specs = list(lt._PART_SPECS.values()) + [lt._PART2_DIAGRAM]
    return {
        canon(t.strip())
        for spec in specs
        for t in str(spec.get("types") or "").split(",")
        if t.strip()
    }


def test_a_reading_paper_can_ask_for_every_type_the_exam_prints():
    steered = _reading_steered()
    missing = [t for t in READING_TYPES if canon(t) not in steered]
    assert not missing, f"a generated paper can never ask for: {missing}"


def test_a_reading_paper_carries_a_completion_block():
    """The official list groups summary / note / table / flow chart as one row,
    so covering the family is the requirement, not all four in one paper."""
    steered = _reading_steered()
    assert [t for t in READING_COMPLETION_FAMILY if canon(t) in steered], (
        "no passage is steered to any completion block")


def test_a_listening_paper_can_ask_for_every_type_the_exam_prints():
    steered = _listening_steered()
    missing = [t for t in LISTENING_TYPES if canon(t) not in steered]
    assert not missing, f"no part spec ever asks for: {missing}"


def test_the_reading_default_mix_is_not_the_only_route_to_a_type():
    """Whatever the unsteered mix happens to name, the steer must not depend on
    it: a student sitting a full paper gets `_passage_types`, and the mix only
    ever fires for a single-passage practice with no types requested."""
    steered = _reading_steered()
    for scarce in ("matching_sentence_endings", "short_answer"):
        assert canon(scarce) in steered, (
            f"{scarce} is reachable only through the default mix, which a full "
            "paper never uses")
