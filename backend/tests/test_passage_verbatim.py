"""The passage expansion has to write in the wording an answer is keyed to.

A completion answer must be words the student can copy FROM THE PASSAGE, so
when the key holds a paraphrase there are two honest cures: re-key the gap to
weaker wording, or make the passage say it. This codebase chose the second —
`_expand_passage`'s `must_name`, the twin of listening's `_expand_script`
`must_say` — and this file holds it to that choice.
"""

import asyncio

import pytest

from app.agents import reading_trainer as rt


def _set(passage: str) -> dict:
    """Three table gaps, all keyed to wording the passage paraphrases.

    🔬 `r_table_r2` from the 60-set sweep of 2026-09-01, cut down: the passage
    said "administrative archives", "divinatory rituals" and "historical
    narrative"; the key read 'administrative records', 'divination' and
    'historical chronicles'.
    """
    return {
        "title": "Four early writing systems",
        "passage": passage,
        "questions": [
            {"number": n, "type": "table_completion",
             "question": f"Complete the table: purpose of the script __{n}__"}
            for n in (1, 2, 3)
        ],
        "answer_key": {
            "1": "administrative records",
            "2": "divination",
            "3": "historical chronicles",
        },
    }


PARAPHRASED = (
    "Clay tablets were dried in the sun and stored in administrative archives "
    "at Uruk and Lagash. Shang oracle bones recorded the outcomes of divinatory "
    "rituals on turtle shells. Mayan stucco panels carried a monumental "
    "historical narrative that endured the tropical climate. " * 30
)


def test_an_expansion_that_writes_none_of_them_in_is_not_kept():
    """🔬 The bug that lost `r_table_r2`: the expansion came back LONGER, wrote
    none of the keyed wording in, and was kept because the test read `longer`
    on its own. The one repair that could have saved the set reported success
    and the gate refused it for the same three answers.
    """
    calls: list[list[str] | None] = []

    async def useless(passage, title, must_name=None):
        calls.append(must_name)
        return passage + " The tropical climate was humid. " * 20   # longer, no answers

    rt._expand_passage = useless
    result = _set(PARAPHRASED)
    before = result["passage"]
    assert len(before.split()) >= rt._MIN_PASSAGE_WORDS, (
        "the fixture must be LONG, like the live passage — a short one is "
        "expanded for its length and the answer rule never gets a say")
    # Driven through the loop directly — the surrounding pass makes model calls
    # this test has no business paying for.
    asyncio.run(_run_expansion(result))
    assert result["passage"] == before, "a longer passage that fixed nothing was kept"
    assert calls, "the expansion was never asked"
    assert set(calls[0] or []) == {
        "administrative records", "divination", "historical chronicles"}


def test_it_is_asked_again_with_only_what_is_STILL_missing():
    """Corrective, not three rolls of one die — the shape `_grow_script` uses."""
    seen: list[list[str] | None] = []

    async def partial(passage, title, must_name=None):
        seen.append(sorted(must_name or []))
        # Writes in one wording per round, the way a cooperative model would.
        for want in sorted(must_name or []):
            if want not in passage:
                return passage + f" Scribes kept {want} for the temple. "
        return passage

    rt._expand_passage = partial
    result = _set(PARAPHRASED)
    asyncio.run(_run_expansion(result))
    assert len(seen) >= 2, "one attempt only; it never went round again"
    assert len(seen[1]) < len(seen[0]), "the second attempt repeated the first"
    assert rt._non_verbatim_answers(result) == [], "answers still unfindable"


def test_it_gives_up_rather_than_looping_forever():
    async def stubborn(passage, title, must_name=None):
        return passage + " More text. "

    rt._expand_passage = stubborn
    result = _set(PARAPHRASED)
    asyncio.run(_run_expansion(result))          # must return
    assert rt._non_verbatim_answers(result), "the fixture is no longer a failing one"


async def _run_expansion(result: dict) -> None:
    """The loop under test, lifted out of the pass that surrounds it."""
    for _ in range(rt._EXPAND_TRIES):
        passage = str(result.get("passage") or "")
        missing = [answer for _, answer in rt._non_verbatim_answers(result)]
        short = len(passage.split()) < rt._MIN_PASSAGE_WORDS
        if not passage or (not missing and not short):
            break
        expanded = await rt._expand_passage(
            passage, str(result.get("title") or ""), missing)
        if not expanded:
            break
        trial = {**result, "passage": expanded}
        still = len(rt._non_verbatim_answers(trial))
        longer = len(expanded.split()) > len(passage.split())
        gained_answers = still < len(missing)
        gained_length = short and longer
        if not gained_answers and not gained_length:
            break
        if still <= len(missing):
            result["passage"] = expanded


@pytest.fixture(autouse=True)
def _restore():
    original = rt._expand_passage
    yield
    rt._expand_passage = original
