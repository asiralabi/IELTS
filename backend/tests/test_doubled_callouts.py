"""Two leader lines into one shape, and the join that cures them.

🔬 `r_diagram_machine_r3`, 2026-09-02, a canal lock. Two callouts sat on
`gate` — "When the boat enters, the __2__ lowers to seal the lock" and "During
the final stage, the __8__ is lifted, allowing the boat to exit" — so the
student was asked to name one shape twice, and the whole set was thrown away.

The legal figure differs by a join: `diagram_error` has always allowed ONE
callout carrying two blanks ("the __25__ behind blades, known as __26__"), and
its refusal message has always said so. The same figure proved the model knew
the shape — `balance` carried __6__ and __7__ in one legal callout.

So the pair is folded rather than regenerated. Free where the join fits the
callout cap, and one small call where it does not: joined whole, those two
sentences run 24 words against a cap of 20 measured off Cambridge's longest.
"""

import asyncio

from app.agents import _figure_pass
from app.agents._diagram import diagram_error, diagram_labels, merge_doubled_callouts


def _lock() -> dict:
    """The refused artifact's figure, trimmed to what the repair reads."""
    return {
        "visual": {
            "kind": "diagram",
            "title": "How a canal lock raises a boat",
            "layout": "machine",
            "parts": [
                {"id": "chamber", "form": "tank", "name": "", "col": 1, "row": 1},
                {"id": "gate", "form": "frame", "name": "", "col": 1, "row": 0},
                {"id": "valve", "form": "valve", "name": "", "col": 2, "row": 1},
            ],
            "labels": [
                {"at": "chamber", "text": "The __1__ holds water during the "
                                          "filling stage."},
                {"at": "gate", "text": "When the boat enters, the __2__ lowers "
                                       "to seal the lock."},
                {"at": "valve", "text": "Air is released through the __3__ to "
                                        "equalise pressure."},
                {"at": "gate", "text": "During the final stage, the __8__ is "
                                       "lifted, allowing the boat to exit."},
            ],
        },
        "questions": [
            {"number": n, "type": "diagram_label_completion",
             "question": f"NO MORE THAN ONE WORD. Label {n} on the diagram."}
            for n in (1, 2, 3, 8)
        ],
        "answer_key": {"1": "chamber", "2": "gate", "3": "valve", "8": "lift"},
    }


def _error(r: dict) -> str:
    return diagram_error(r["visual"], r["questions"], r["answer_key"]) or ""


class _Stub:
    """Stands in for the generator client and records what it was sent."""

    is_finetune = False

    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts: list[str] = []

    async def complete_json(self, system, messages, **kwargs):
        self.prompts.append(messages[0]["content"])
        if not self.replies:
            return {"callout": ""}
        return {"callout": self.replies.pop(0)}


def _use(monkeypatch, replies):
    stub = _Stub(replies)
    monkeypatch.setattr(_figure_pass, "get_llm_client", lambda *a, **k: stub)
    return stub


def test_the_doubled_callout_is_what_refused_the_set():
    assert "carries two numbered callouts" in _error(_lock())


def test_a_short_pair_is_folded_for_nothing():
    r = _lock()
    r["visual"]["labels"][1]["text"] = "The __2__ seals the lock."
    r["visual"]["labels"][3]["text"] = "The __8__ raises it."
    assert merge_doubled_callouts(r) == [("gate", ["2", "8"])]
    texts = [lb["text"] for lb in diagram_labels(r["visual"])]
    assert "The __2__ seals the lock. The __8__ raises it." in texts
    # One leader line where there were two, and both gaps still on the figure.
    assert len(texts) == 3
    assert _error(r) == ""


def test_a_join_over_the_cap_is_left_for_the_call():
    """A 24-word join swaps one refusal for another. The set is lost either
    way, and 'the callout runs too long' is the worse sentence to diagnose it
    by — it describes the repair, not the fault."""
    r = _lock()
    assert merge_doubled_callouts(r) == []
    assert "carries two numbered callouts" in _error(r)


def test_the_long_pair_is_written_as_one_line(monkeypatch):
    r = _lock()
    _use(monkeypatch, ["The __2__ seals the lock and the __8__ raises the boat "
                       "to the upper level."])
    assert asyncio.run(_figure_pass.condense_doubled_callouts(r)) == [
        ("gate", "The __2__ seals the lock and the __8__ raises the boat to "
                 "the upper level.")
    ]
    assert len(diagram_labels(r["visual"])) == 3
    assert _error(r) == ""


def test_both_callouts_are_sent_and_neither_answer_is(monkeypatch):
    """The gaps go over as they stand. `_rewrite_callout` fills its gap in
    before the call, because it needs the model to read around a blank; this
    one needs both blanks copied through, and handing over 'gate' and 'lift'
    invites the figure to print what its own questions ask for."""
    r = _lock()
    stub = _use(monkeypatch, ["The __2__ seals the lock as the __8__ begins."])
    asyncio.run(_figure_pass.condense_doubled_callouts(r))
    sent = stub.prompts[0]
    # Both callouts go over whole, blanks and all...
    assert "the __2__ lowers to seal the lock" in sent
    assert "the __8__ is lifted" in sent
    # ...and neither blank arrives already filled in, which is the form
    # `_rewrite_callout` deliberately sends and this repair must not.
    assert "the gate lowers" not in sent
    assert "the lift is" not in sent


def test_a_reply_that_answers_a_gap_is_refused(monkeypatch):
    """The gaps are the figure's only coupling to the questions: a reply that
    writes the answer in leaves a question nobody can mark."""
    r = _lock()
    _use(monkeypatch, ["The gate seals the lock and the __8__ raises the boat.",
                       "The gate seals the lock and the __8__ raises the boat."])
    assert asyncio.run(_figure_pass.condense_doubled_callouts(r)) == []
    # Untouched, so the gate refuses it for the fault it actually has.
    assert len(diagram_labels(r["visual"])) == 4
    assert "carries two numbered callouts" in _error(r)


def test_a_reply_still_over_the_cap_is_refused(monkeypatch):
    r = _lock()
    long_reply = ("When the boat first enters the lock chamber the __2__ "
                  "lowers to seal it, and at the very end of the cycle the "
                  "__8__ is raised so the boat may leave.")
    _use(monkeypatch, [long_reply, long_reply])
    assert asyncio.run(_figure_pass.condense_doubled_callouts(r)) == []
    assert len(diagram_labels(r["visual"])) == 4


def test_a_failed_call_leaves_the_figure_alone(monkeypatch):
    r = _lock()
    _use(monkeypatch, [])
    assert asyncio.run(_figure_pass.condense_doubled_callouts(r)) == []
    assert [lb["text"] for lb in diagram_labels(r["visual"])] == [
        lb["text"] for lb in diagram_labels(_lock()["visual"])
    ]


def test_a_figure_with_one_callout_per_part_is_untouched(monkeypatch):
    r = _lock()
    r["visual"]["labels"] = r["visual"]["labels"][:3]
    r["questions"] = r["questions"][:3]
    del r["answer_key"]["8"]
    before = [dict(lb) for lb in diagram_labels(r["visual"])]
    stub = _use(monkeypatch, ["should not be called"])
    assert merge_doubled_callouts(r) == []
    assert asyncio.run(_figure_pass.condense_doubled_callouts(r)) == []
    assert stub.prompts == []
    assert diagram_labels(r["visual"]) == before


def test_the_callout_that_survives_keeps_its_part(monkeypatch):
    """A merged callout still hangs off the shape both halves described. Point
    it anywhere else and the leader line lies about what it names."""
    r = _lock()
    _use(monkeypatch, ["The __2__ seals the lock as the __8__ begins."])
    asyncio.run(_figure_pass.condense_doubled_callouts(r))
    merged = [lb for lb in diagram_labels(r["visual"]) if "__8__" in lb["text"]]
    assert len(merged) == 1
    assert merged[0]["at"] == "gate"
