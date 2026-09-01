"""A letter the student must find, with the answer printed underneath it.

Map labelling asks "which letter marks the cafe?" — so a feature carrying the
NAME at the same coordinates as the letter hands the answer over. One deletion
cures it, which is the bargain `blank_self_answering_labels` strikes on the
diagram: blanking costs one orientation label, leaving it costs the question.
"""

from app.agents import listening_trainer as lt
from app.agents.answerability import drop_letter_clash_names, unlettered_map_error


def _map() -> dict:
    """🔬 `l_map_r2`, 2026-09-01 — refused on the way in, one corrective retry
    spent, the retry failed the same way and the whole set died."""
    return {
        "visual": {
            "kind": "map",
            "title": "Country park",
            "features": [
                {"label": "A", "x": 2.0, "y": 3.0},
                {"label": "Main trail", "x": 2.0, "y": 3.0},
                {"label": "B", "x": 5.0, "y": 1.0},
                {"label": "Lake", "x": 8.0, "y": 8.0},
            ],
        },
        "questions": [
            {"number": n, "type": "map_labelling",
             "question": f"Which letter marks the place described in {n}?"}
            for n in (1, 2)
        ],
        "answer_key": {"1": "A", "2": "B"},
    }


def test_the_name_printed_on_a_letter_is_deleted_not_refused():
    r = _map()
    assert drop_letter_clash_names(r) == ["Main trail"]
    labels = [f["label"] for f in r["visual"]["features"]]
    # The letter stays, its giveaway goes, and a name that clashes with nothing
    # is left to orient the student.
    assert labels == ["A", "B", "Lake"]


def test_a_map_with_no_clash_is_untouched():
    r = _map()
    r["visual"]["features"][1]["x"] = 9.0
    assert drop_letter_clash_names(r) == []
    assert len(r["visual"]["features"]) == 4


def test_the_clash_costs_no_retry_on_the_way_in():
    """The repair runs during normalisation, which is AFTER the way-in hook.
    Judged there, a repairable fault buys a retry of the whole set that has
    never rescued one."""
    r = _map()
    v, qs, key = r["visual"], r["questions"], r["answer_key"]
    assert "sits on 'Main trail'" in (unlettered_map_error(qs, v, key) or "")
    assert unlettered_map_error(qs, v, key, after_repairs=False) is None
    # ...and the way-in gate asks it the second way.
    assert lt.validate_part(r, judge_map=False) is None


def test_a_letter_keyed_but_never_drawn_is_still_refused_either_way():
    """No repair can invent a letter the figure does not have."""
    r = _map()
    r["answer_key"]["2"] = "F"
    v, qs, key = r["visual"], r["questions"], r["answer_key"]
    assert unlettered_map_error(qs, v, key, after_repairs=False)
    assert unlettered_map_error(qs, v, key)


def test_normalisation_runs_the_repair():
    r = _map()
    lt._normalize_figure(r)
    assert [f["label"] for f in r["visual"]["features"]] == ["A", "B", "Lake"]
