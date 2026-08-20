import json
import random
import re
from collections import Counter
from functools import partial

from app.agents._marking import mark_answers, mark_full_test
from app.agents._numbering import renumber
from app.agents.answerability import (
    GAP_FILL_TYPES,
    canon,
    cross_section_error,
    dangling_structure_error,
    qtype,
    self_answering_error,
    word_limit_error,
)
from app.llm.client import gather_llm, get_llm_client
from app.llm.prompts import (
    HEADINGS_WRITER_SYSTEM,
    NOTGIVEN_WRITER_SYSTEM,
    PASSAGE_EXPANDER_SYSTEM,
    READING_EVALUATOR_SYSTEM,
    READING_TRAINER_SYSTEM,
)
from app.rag.retriever import retrieve_context

# Real IELTS passages are 650-900 words. qwen3:4b tends to short-generate;
# anything under this floor triggers an expansion pass so students still get
# exam-realistic length.
_MIN_PASSAGE_WORDS = 550


# Academic Reading is marked on its own conversion table — it is harder than
# Listening at the same raw score (band 7.5 needs 33 here against 32 there).
_READING_BAND_TABLE: list[tuple[int, float]] = [
    (39, 9.0),
    (37, 8.5),
    (35, 8.0),
    (33, 7.5),
    (30, 7.0),
    (27, 6.5),
    (23, 6.0),
    (19, 5.5),
    (15, 5.0),
    (13, 4.5),
    (10, 4.0),
    (8, 3.5),
    (6, 3.0),
    (4, 2.5),
]


# READING_TRAINER_SYSTEM asks for "at least 5 paragraphs", but the teacher that
# wrote the corpus never obeyed it: 26 of the 54 committed headings sets carry
# exactly 3, so enforcing the prompt's own number would reject 11.5% of the data
# the checkpoint was trained on. 3 is the floor the corpus actually observes.
_MIN_HEADINGS_BLOCK = 3

# A labelled diagram numbers several parts; Cambridge never prints one with a
# single blank, and all 5 figure-bearing corpus sets carry 3 or 4. One label
# is a figure drawn for its own sake rather than a question block.
_MIN_DIAGRAM_LABELS = 3

# Every offered heading was written for a real paragraph, so the distractors are
# simply the headings of the paragraphs left unkeyed. Two is the corpus shape:
# its blocks run (3 paragraphs, 5 headings) through (7, 9).
_HEADINGS_DISTRACTORS = 2
# Without a cap a 9-paragraph passage becomes a 9-question headings block, which
# would crowd out every other type in a set of 8-13.
_MAX_HEADINGS_BLOCK = 5
_ROMAN = ("i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii")
# "A." / "**B**" / "Paragraph C:". Punctuation after the letter is required, so a
# paragraph that merely opens "A new study..." is not mistaken for a label.
_PARAGRAPH_LABEL = re.compile(r"^\**\s*(?:Paragraph\s+)?([A-Z])\s*[.):]\s*\**\s*")
# The model sometimes numbers the heading it was asked to write bare, and the
# numeral it picks is not the one the shuffle assigns. Only the numeral form is
# stripped: a leading capital is left alone because "E. coli in water supplies"
# is a heading, not a label.
_HEADING_PREFIX = re.compile(r"^\s*[ivx]+\s*[.)]\s+", re.IGNORECASE)

_TFNG_TYPES = {canon("true_false_notgiven"), canon("yes_no_notgiven")}

# Question types whose answers are read off a printed figure.
_FIGURE_TYPES = {canon("table_completion"), canon("diagram_label_completion")}

# Every spelling of the verdict the corpus uses.
_NOTGIVEN_VERDICTS = {"NOT GIVEN", "NOTGIVEN", "NG"}

_ARTICLES = {"a", "an", "the"}


def _span_tokens(text: str) -> list[str]:
    """Words of `text` reduced to a comparable form: punctuation and casing
    dropped, "per cent"/"%" folded to one spelling, leading article stripped
    (the gap usually already supplies it).
    """
    lowered = str(text).lower().replace("per cent", "percent").replace("%", " percent ")
    words = re.sub(r"[^a-z0-9]+", " ", lowered).split()
    while words and words[0] in _ARTICLES:
        words = words[1:]
    return words


def _loose_stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if len(word) > 4 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def _non_verbatim_answers(result: dict) -> list[str]:
    """Gap-fill answers that appear nowhere in the passage.

    Every completion type instructs the student to choose words FROM THE
    PASSAGE, so an answer that isn't a span of it cannot be produced or marked.
    The teacher's habitual failure is a paraphrase or a truncation — a passage
    reading "gaining attention" keyed as "more attention", or "functionality
    and community" keyed as "functionality community".
    """
    passage = _span_tokens(result.get("passage") or "")
    if not passage:
        return []
    haystack = f" {' '.join(passage)} "
    stemmed = f" {' '.join(_loose_stem(w) for w in passage)} "
    answer_key = result.get("answer_key") or {}
    missing = []
    for q in result.get("questions") or []:
        if not isinstance(q, dict) or qtype(q) not in GAP_FILL_TYPES:
            continue
        # A question carrying its own word box is answered from the box.
        if isinstance(q.get("options"), list) and q["options"]:
            continue
        answer = answer_key.get(str(q.get("number")))
        if answer is None:
            continue
        for cand in (str(answer).split(";") if ";" in str(answer) else [str(answer)]):
            words = _span_tokens(cand)
            if not words:
                continue
            span = f" {' '.join(words)} "
            span_stemmed = f" {' '.join(_loose_stem(w) for w in words)} "
            if span not in haystack and span_stemmed not in stemmed:
                missing.append(f"Q{q.get('number')}={cand.strip()!r}")
    return missing


def validate_practice(
    result: dict, *, judge_headings: bool = True, judge_notgiven: bool = True
) -> str | None:
    """Reject a practice set a student could not fairly sit.

    Returned as the `validate` hook on complete_json, so a broken set costs one
    corrective retry instead of reaching the student — or, during dataset
    export, becoming a training target that teaches the pathology.

    `judge_headings=False` and `judge_notgiven=False` are for the one caller
    that repairs those two things in code afterwards: the model's own headings
    are discarded and its missing NOT GIVEN is written by a second, narrower
    call, so a retry spent complaining about either buys nothing. Every other
    caller judges them.
    """
    cross_section = cross_section_error(result, "reading")
    if cross_section:
        return cross_section

    questions = result.get("questions") or []
    answer_key = result.get("answer_key") or {}
    if not questions or not answer_key:
        return "questions and answer_key must both be non-empty"

    numbers = []
    for q in questions:
        if not isinstance(q, dict):
            return "every entry in questions must be an object"
        if not str(q.get("question") or "").strip():
            return f"question {q.get('number')} has empty question text"
        if not qtype(q):
            return (
                f"question {q.get('number')} has no `type`; every question must "
                "declare one of the allowed types so it renders and marks correctly"
            )
        numbers.append(str(q.get("number")))
    if set(numbers) != set(map(str, answer_key)):
        return "question numbers and answer_key keys must match exactly"

    by_type: dict[str, list[dict]] = {}
    for q in questions:
        by_type.setdefault(qtype(q), []).append(q)

    headings = by_type.get(canon("matching_headings")) or []
    if headings and judge_headings:
        # A one-question block satisfies both checks below for free — it needs
        # only 3 options and is a bijection by construction — so size has to be
        # asked for first or an under-produced block ships looking valid.
        if len(headings) < _MIN_HEADINGS_BLOCK:
            return (
                f"this set has only {len(headings)} matching_headings question(s); "
                f"write at least {_MIN_HEADINGS_BLOCK}, one for each lettered "
                "paragraph of the passage, each offering the same full list of "
                "headings — or drop matching_headings and use another question "
                "type throughout"
            )
        # Ask for the headings before asking for distinct answers. With a short
        # list, distinctness is not merely unmet but unreachable, and "reassign
        # so every paragraph gets its own heading" then demands the impossible
        # — the one instruction a retry cannot act on.
        for q in headings:
            opts = q.get("options")
            if not isinstance(opts, list) or len(opts) < len(headings) + 2:
                return (
                    f"every matching_headings question needs an options list of at "
                    f"least {len(headings) + 2} headings ({len(headings)} paragraphs "
                    "+ 2 distractors)"
                )
        answers = [str(answer_key.get(str(q.get("number")))) for q in headings]
        if len(set(answers)) != len(answers):
            # A reading set is too long to echo back into the corrective retry,
            # so this string is the only handle the model has on what to change.
            repeated = sorted({a for a in answers if answers.count(a) > 1})
            clashing = ", ".join(
                str(q.get("number")) for q, a in zip(headings, answers) if a in repeated
            )
            unused = [
                str(o) for o in (headings[0].get("options") or [])
                if str(o) not in set(answers)
            ]
            return (
                "each matching_headings answer must be a different heading, but "
                f"questions {clashing} reuse {', '.join(repeated)} — reassign so "
                "every paragraph gets its own heading"
                + (f"; these are still unused: {', '.join(unused)}" if unused else "")
            )

    for name in ("multiple_choice", "matching_information", "matching_features",
                 "matching_sentence_endings"):
        block = by_type.get(canon(name)) or []
        for q in block:
            if not isinstance(q.get("options"), list) or not q["options"]:
                return f"{name} question {q.get('number')} is missing its options array"
        if len(block) >= 3:
            answers = {str(answer_key.get(str(q.get("number")))).strip().upper() for q in block}
            if len(answers) == 1:
                return (
                    f"all {len(block)} {name} answers are {answers.pop()!r}; spread the "
                    "correct choices across the options"
                )

    dangling = dangling_structure_error(
        questions, result.get("visual"),
        "Ore is crushed, then ______, then washed.",
    )
    if dangling:
        return dangling

    over_limit = word_limit_error(result)
    if over_limit:
        return over_limit

    # One stray paraphrase is teacher noise and costs a retry for little gain;
    # two in the same set is a habit that would train the model to invent
    # answers no student could find.
    unfindable = _non_verbatim_answers(result)
    if len(unfindable) >= 2:
        return (
            f"these gap-fill answers do not appear anywhere in the passage: "
            f"{', '.join(unfindable)}. Completion answers must be copied "
            "verbatim from the passage — the student is told to choose words "
            "FROM THE PASSAGE, so a paraphrase or a shortened phrase is "
            "unmarkable. Either reword the passage to contain the answer "
            "exactly, or key each gap to the exact words already written there."
        )

    tfng = [q for q in questions if qtype(q) in _TFNG_TYPES]
    if len(tfng) >= 4:
        verdicts = {str(answer_key.get(str(q.get("number")))).strip().upper() for q in tfng}
        if len(verdicts) == 1:
            return (
                f"all {len(tfng)} true/false/not-given answers are "
                f"{verdicts.pop()!r}; a real block mixes the verdicts"
            )
        # The teacher reliably writes only verifiable statements unless pushed.
        # A block with no NOT GIVEN never trains the skill the type exists for.
        if judge_notgiven and not verdicts & _NOTGIVEN_VERDICTS:
            return (
                f"none of the {len(tfng)} true/false/not-given answers is NOT GIVEN; "
                "rewrite at least one statement so it makes a plausible claim the "
                "passage never actually states"
            )

    self_answering = self_answering_error(questions)
    if self_answering:
        return self_answering

    labels = by_type.get(canon("diagram_label_completion")) or []
    if labels and len(labels) < _MIN_DIAGRAM_LABELS:
        return (
            f"the diagram carries only {len(labels)} numbered part(s); a "
            "labelled figure is worth printing only if it asks about at "
            f"least {_MIN_DIAGRAM_LABELS} of them. Number that many parts on "
            "the grid and write one question for each, or drop the diagram "
            "and use another question type."
        )
    return None


def _paragraph_bodies(passage: str) -> list[str]:
    """The passage's paragraphs, with any A./B. label they already carry removed.

    Labels win over blank lines when the passage carries a run of them starting
    at A, because that is the author's own paragraph division; 74% of the
    headings corpus letters its paragraphs and the checkpoint did so in 3 of 3
    live generations. Otherwise every non-empty line is a paragraph.
    """
    lines = [ln.strip() for ln in passage.splitlines() if ln.strip()]
    marked = [(i, m) for i, ln in enumerate(lines) if (m := _PARAGRAPH_LABEL.match(ln))]
    letters = [m.group(1) for _, m in marked]
    if len(letters) < _MIN_HEADINGS_BLOCK or letters != [chr(65 + i) for i in range(len(letters))]:
        return lines
    starts = [i for i, _ in marked] + [len(lines)]
    return [
        " ".join([_PARAGRAPH_LABEL.sub("", lines[starts[k]])] + lines[starts[k] + 1:starts[k + 1]])
        for k in range(len(marked))
    ]


def _headings_questions(keyed: list[str], headings: dict[str, str]) -> list[dict]:
    """The block itself, assembled from a heading-per-paragraph mapping.

    Which paragraph a heading was written for is the answer, so the key is a
    property of the assembly rather than something anyone had to work out.
    """
    spare = [letter for letter in headings if letter not in keyed]
    random.shuffle(spare)
    offered = keyed + spare[:_HEADINGS_DISTRACTORS]
    random.shuffle(offered)
    labelled = {letter: f"{_ROMAN[i]}. {headings[letter]}"
                for i, letter in enumerate(offered)}
    options = [labelled[letter] for letter in offered]
    return [
        {
            "number": 0,
            "type": "matching_headings",
            "question": f"Choose the correct heading for Paragraph {letter}.",
            # The frontend renders no `headings` field, so the full list has to
            # ride on every question. A fresh copy per question — a shared list
            # would serialise fine but alias if anything downstream edits one.
            "options": list(options),
            # The whole option, not the bare numeral the system prompt asks the
            # model for. question-list.tsx labels options A, B, C by position and
            # submits that letter, which _marking.resolve_choice turns back into
            # the option text; a numeral-only key never equals it, so every
            # headings question would fall through to the evaluator to be judged
            # as "iii. Soil erosion" against "iii".
            "_answer": labelled[letter],
        }
        for letter in keyed
    ]


async def _write_headings(letters: list[str], bodies: list[str]) -> dict[str, str] | None:
    """Ask the model only to summarise — the half of the task it is good at.

    Measured on 8 gold sets, this checkpoint agrees with the teacher's heading
    key 53% of the time, so anything that asks it to *match* ships a confident
    wrong answer. Writing a heading for a paragraph it can see is a different
    task, and the answer key falls out of the request rather than the reply.

    The reply is a few hundred characters, so unlike a whole practice set it
    fits under the echo cap — a corrective retry can actually see what it wrote.
    """
    numbered = "\n\n".join(f"{letter}. {body}" for letter, body in zip(letters, bodies))

    def check(reply: dict) -> str | None:
        written = reply.get("headings")
        if not isinstance(written, dict):
            return "`headings` must be an object with one paragraph letter per key"
        blank = [x for x in letters if not str(written.get(x) or "").strip()]
        if blank:
            return (
                f"no heading was written for paragraph {', '.join(blank)}; write "
                "one for every letter in the passage"
            )
        # Compared after the numeral is stripped, since that is the form the
        # student reads: "i. Water reuse" and "ii. Water reuse" are two labels
        # for one heading, and would put the same text twice on screen.
        texts = [_HEADING_PREFIX.sub("", str(written[x]).strip()).lower() for x in letters]
        if len(set(texts)) != len(texts):
            return (
                "two paragraphs were given the same heading; each heading must "
                "name what makes its own paragraph different from the others"
            )
        return None

    try:
        reply = await get_llm_client("generator").complete_json(
            HEADINGS_WRITER_SYSTEM,
            [{"role": "user", "content":
              f"Write a heading for each of these {len(letters)} paragraphs.\n\n{numbered}"}],
            required_keys=("headings",),
            validate=check,
            max_tokens=1024,
        )
    except Exception:
        return None
    return {x: _HEADING_PREFIX.sub("", str(reply["headings"][x]).strip()) for x in letters}


def _replace_block(result: dict, old: list[dict], new: list[dict]) -> None:
    """Swap one block of questions for another and renumber the whole set."""
    questions = result.get("questions") or []
    dropped = {id(q) for q in old}
    # By identity, not equality: two questions can compare equal, and `index`
    # would then put the new block wherever the first look-alike happens to sit.
    at = next((i for i, q in enumerate(questions) if id(q) in dropped), len(questions))
    kept = [q for q in questions if id(q) not in dropped]
    merged = kept[:at] + new + kept[at:]

    was_keyed = result.get("answer_key") or {}
    answer_key: dict[str, object] = {}
    renumbered: dict[str, str] = {}
    for number, q in enumerate(merged, start=1):
        before = str(q.get("number"))
        q["number"] = number
        if "_answer" in q:
            answer_key[str(number)] = q.pop("_answer")
        else:
            renumbered[before] = str(number)
            answer_key[str(number)] = was_keyed.get(before)
    result["questions"] = merged
    result["answer_key"] = answer_key

    # A table_completion cell addresses its question by number, so renumbering
    # without this silently unhooks the gap from the question it fills.
    visual = result.get("visual")
    if visual:
        result["visual"] = json.loads(re.sub(
            r"__(\d+)__",
            lambda m: f"__{renumbered.get(m.group(1), m.group(1))}__",
            json.dumps(visual, ensure_ascii=False),
        ))


async def _rebuild_headings(result: dict) -> None:
    """Replace whatever matching_headings the model wrote with a built block.

    Rebuilding unconditionally, rather than only when the model's block looks
    broken, is the point: a block can satisfy every structural rule and still
    carry a wrong key, and nothing downstream can tell. Building it means the
    key is never inferred.

    If the passage cannot support a block the questions are dropped instead. A
    set one question short is still sittable; a headings block keyed by
    guesswork is not.
    """
    questions = result.get("questions") or []
    old = [q for q in questions if qtype(q) == canon("matching_headings")]
    if not old:
        return

    bodies = _paragraph_bodies(str(result.get("passage") or ""))
    keyed = min(len(bodies) - _HEADINGS_DISTRACTORS, _MAX_HEADINGS_BLOCK)
    new: list[dict] = []
    if keyed >= _MIN_HEADINGS_BLOCK:
        letters = [chr(65 + i) for i in range(len(bodies))]
        headings = await _write_headings(letters, bodies)
        if headings:
            # Written back so the letters the questions name are the letters the
            # student can actually see, whether or not the model labelled them.
            result["passage"] = "\n\n".join(
                f"{letter}. {body}" for letter, body in zip(letters, bodies))
            new = _headings_questions(letters[:keyed], headings)
    _replace_block(result, old, new)


async def _write_notgiven(passage: str, used: list[str]) -> str | None:
    """One short call for one statement the passage never makes."""
    prompt = (
        f"Passage:\n{passage}\n\n"
        "Statements already used in this block — do not reuse or negate any "
        "of them:\n" + "\n".join(f"- {s}" for s in used)
    )

    def check(reply: dict) -> str | None:
        """The writer's own prompt explains NOT GIVEN as what the passage
        "neither confirms nor contradicts", and that wording has come back
        inside the statement. A 256-token retry is the cheapest place to
        catch it."""
        return self_answering_error([{
            "number": "the statement", "type": "true_false_notgiven",
            "question": str(reply.get("statement") or ""),
        }])

    try:
        reply = await get_llm_client("generator").complete_json(
            NOTGIVEN_WRITER_SYSTEM,
            [{"role": "user", "content": prompt}],
            required_keys=("statement",),
            validate=check,
            max_tokens=256,
        )
    except Exception:
        return None
    return str(reply.get("statement") or "").strip() or None


async def _repair_missing_notgiven(result: dict) -> None:
    """Give a NOT-GIVEN-less true/false block a real NOT GIVEN.

    All 68 blocks of four or more in the corpus carry one, so the rule this
    satisfies is not off-distribution — the checkpoint simply draws a block of
    wholly verifiable statements often enough to fail twice running, and the
    corrective retry rewrites the entire passage rather than the one statement
    at fault. Asking for a single statement is a sub-task a 3B can do, and
    costs one short call instead of another 4096-token set.

    Whether the statement really is unstated is the model's judgement and
    nothing here can confirm it; what is guaranteed is that the block now
    trains the choice the question type exists to test.
    """
    tfng = [q for q in result.get("questions") or [] if qtype(q) in _TFNG_TYPES]
    if len(tfng) < 4:
        return
    answer_key = result.get("answer_key") or {}

    def verdict(q: dict) -> str:
        return str(answer_key.get(str(q.get("number")))).strip().upper()

    verdicts = [verdict(q) for q in tfng]
    if set(verdicts) & _NOTGIVEN_VERDICTS:
        return

    # Convert one of the majority verdict's statements, so the block does not
    # lose whichever verdict it only had once.
    majority = Counter(verdicts).most_common(1)[0][0]
    victim = [q for q in tfng if verdict(q) == majority][-1]

    statement = await _write_notgiven(
        str(result.get("passage") or ""),
        [str(q.get("question") or "") for q in tfng],
    )
    if not statement:
        return
    victim["question"] = statement
    answer_key[str(victim.get("number"))] = "NOT GIVEN"
    result["answer_key"] = answer_key


async def create_practice(
    question_types: list[str] | None = None,
    difficulty: str | None = None,
    topic: str | None = None,
) -> dict:
    parts = ["Generate an IELTS Academic Reading practice set."]
    if question_types:
        parts.append("Question types: " + ", ".join(question_types) + ".")
    if difficulty:
        parts.append(f"Difficulty: {difficulty}.")
    if topic:
        parts.append(f"Topic: {topic}.")

    # Same reason as listening's _FIGURE_PARTS: a set built around a printed
    # figure has to come from the general model, because the checkpoint's corpus
    # never described one.
    client = get_llm_client(
        "generator",
        skip_finetune=bool(
            _FIGURE_TYPES.intersection(canon(t) for t in question_types or ())
        ),
    )
    # The SFT user turn is topic/difficulty/types only, so grounding a
    # fine-tune puts it off-distribution: it read the exemplar as content to
    # continue and emitted the exemplar's own questions against its new
    # passage. The checkpoint was distilled from grounded teacher output, so
    # the Cambridge style is already in the weights.
    if not client.is_finetune:
        query = "IELTS Academic Reading passage " + (topic or "") + " " + (
            " ".join(question_types) if question_types else "True False Not Given matching headings"
        )
        # top_k=1 keeps the exemplar tight — extra chunks cost ~800 input tokens
        # each on a CPU-bound model without visibly improving output style.
        context = retrieve_context(query.strip(), top_k=1)
        if context:
            parts.append(
                "\nReal Cambridge IELTS Reading exemplar — match this style, tone, "
                "structure and question difficulty. Do NOT copy its phrasing, "
                "topic, or specific facts; use it as stylistic reference only.\n\n"
                + context
            )

    result = await client.complete_json(
        READING_TRAINER_SYSTEM,
        [{"role": "user", "content": "\n".join(parts)}],
        required_keys=("title", "passage", "questions", "answer_key"),
        validate=partial(
            validate_practice, judge_headings=False, judge_notgiven=False
        ),
        # A ~1200-word passage plus 8-13 questions carrying full options lists
        # is a 3.5-5k-token JSON object; LLM_MAX_TOKENS is 2048 locally. A
        # truncation is expensive twice over — the corrective retry replays the
        # truncated text as context, so it has even less room than the first
        # attempt. Buy the headroom.
        max_tokens=6144,
    )

    passage = str(result.get("passage") or "")
    if len(passage.split()) < _MIN_PASSAGE_WORDS:
        expanded = await _expand_passage(passage, str(result.get("title") or ""))
        if expanded and len(expanded.split()) > len(passage.split()):
            result["passage"] = expanded

    # After the expansion, so the headings describe the paragraphs the student
    # is given rather than the shorter ones they were written from.
    await _rebuild_headings(result)
    # After the rebuild, so a statement is not written against a question the
    # rebuild is about to replace.
    await _repair_missing_notgiven(result)
    # Both rules were skipped on the way in on the promise that they would be
    # satisfied here. Nothing else can fail this, so a complaint means a repair
    # did not take and the set must not reach a student.
    problem = validate_practice(result)
    if problem:
        raise ValueError(f"the repaired reading set is invalid: {problem}")

    return result


async def _expand_passage(passage: str, title: str) -> str | None:
    """Single-call expansion — asks the model to lengthen without changing meaning.

    Returns the raw expanded string or None if the call didn't produce
    something usably longer. Errors are swallowed so a failed expansion
    doesn't kill the whole practice generation.
    """
    if not passage.strip():
        return None
    prompt = (
        f"Title: {title}\n\nPassage to expand:\n{passage}\n\n"
        "Expand this passage to at least 700 words. Keep the same facts, "
        "claims, and paragraph labels; add supporting detail, examples, "
        "and elaboration. Return ONLY the expanded passage prose — no JSON, "
        "no title, no commentary."
    )
    try:
        expanded = await get_llm_client().complete(
            PASSAGE_EXPANDER_SYSTEM,
            [{"role": "user", "content": prompt}],
        )
    except Exception:
        return None
    expanded = expanded.strip()
    return expanded or None


async def check_answers(practice: dict, answers: dict) -> dict:
    """Mark a Reading passage answer-by-answer with the fine-tuned evaluator."""
    return await mark_answers(
        practice, answers, READING_EVALUATOR_SYSTEM, _READING_BAND_TABLE
    )


# The real paper is 3 passages / 40 questions, but the corpus writes 8 questions
# at the mode — 158 of 227 sets, mean 8.1, never more than 15. Demanding the
# exam's 13-14 per passage is far enough off-distribution that a set would fail
# validation and be retried rather than come back longer. Three passages at the
# count the checkpoint actually writes is the honest structure, and
# `band_from_40` already scales a short paper onto the /40 table, so the band
# the student is shown is the one they earned.
_FULL_TEST_PASSAGES = 3

# A real paper's passages get harder as it runs. `difficulty` is part of the SFT
# user turn, so varying it per passage is a shape the checkpoint was trained on.
_DIFFICULTY_RAMP = ("easy", "medium", "hard")

# A Cambridge paper prints a figure on roughly one passage, and the default type
# mix never reaches for one, so a paper generated without a steer carries none.
# Asking passage 2 for a labelled diagram is where the real papers put theirs.
_PASSAGE_TYPES: dict[int, list[str]] = {
    1: ["diagram_label_completion", "true_false_notgiven", "multiple_choice"],
}


async def create_full_test(difficulty: str | None = None) -> dict:
    """Assemble a complete 3-passage IELTS Academic Reading test."""
    passages = await gather_llm(
        "generator",
        [
            create_practice(
                question_types=_PASSAGE_TYPES.get(i),
                difficulty=difficulty or _DIFFICULTY_RAMP[i],
            )
            for i in range(_FULL_TEST_PASSAGES)
        ],
    )

    # Sequential, and only once every passage is back. Listening can compute its
    # offsets up front because a part is always ten questions; a reading passage
    # returns whatever count it wrote, so passage 2's offset is unknown until
    # passage 1 has said how long it is.
    offset = 0
    for number, passage in enumerate(passages, start=1):
        renumber(passage, offset)
        offset += len(passage.get("questions") or [])
        passage["passage_number"] = number

    return {
        "title": "IELTS Academic Reading Practice Test",
        "kind": "full_reading_test",
        "passages": passages,
    }


async def check_full_test(test_payload: dict, answers: dict) -> dict:
    """Mark the whole paper passage by passage, then aggregate onto one band."""
    return await mark_full_test(
        test_payload.get("passages") or [],
        answers,
        check_answers,
        _READING_BAND_TABLE,
        "passage_number",
        "passages",
    )
