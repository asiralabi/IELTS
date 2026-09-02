"""The second pass that draws the figure, and the callout repair beside it.

A practice set is generated in ONE hosted call that has to produce a passage,
a question list, an answer key, metadata and a figure. The diagram block of
that prompt runs to ~9,000 characters and the model skims it: measured over
five live reading sets on 2026-08-27, three came back usable, none had ever
used the containment (`in`) the renderer supports, and the failures were all
the same shape — a part called `pump` or `generator` drawn as a plain `box`,
nothing joined to anything, and a bare `__1__` for a callout.

That is not a prompt-wording problem. It is a division-of-attention problem,
and this module is the fix the rest of the codebase already uses for it: a
small focused call with ONE job, judged before it is kept, exactly like
`_repair_dangling_completions`, `_repair_duplicate_diagram_answers` and
`repair_self_answering_steps`.

Two entry points, both safe to call on any set:

  `redraw_diagram`               — draws the figure again, alone, with the
                                   passage and the keyed answers in front of
                                   it. Kept only if it validates AND scores
                                   better than what it replaces.
  `repair_self_answering_callouts` — the prose analogue of
                                   `blank_self_answering_labels`, needed since
                                   a callout became a clause: a callout that
                                   carries its own gap cannot simply be
                                   deleted, so it is reworded instead.
"""

from __future__ import annotations

import logging
import re
from copy import deepcopy

from app.agents._diagram import (
    _APPARATUS_FORMS,
    _LAYER_FORMS,
    # Aliased: this module's own `_MAX_LABEL_WORDS` is the cap on a FORM FIELD
    # name (5 words), which is a different thing from a callout's clause (20).
    _MAX_LABEL_WORDS as _MAX_CALLOUT_WORDS,
    _PANEL_FORMS,
    _slug,
    _text,
    DIAGRAM_GAP_RE,
    LAYERS,
    blank_gapped_part_names,
    blank_self_answering_labels,
    diagram_error,
    diagram_gaps,
    diagram_labels,
    diagram_layout,
    diagram_links,
    diagram_parts,
    is_diagram,
    labelling_numbers,
    normalize_diagram,
    self_answering_labels,
)
from app.agents._marking import norm
from app.agents._numbering import renumber
from app.agents.answerability import chart_transcriptions, dangling_completions
from app.llm.client import get_llm_client
from app.llm.prompts import (
    DIAGRAM_MERGE_CALLOUT_SYSTEM,
    DIAGRAM_RECALLOUT_SYSTEM,
    FIGURE_DRAW_SYSTEM,
    FORM_WRITER_SYSTEM,
)
from app.rag.figures import FAMILY_BY_KIND, figure_conventions

logger = logging.getLogger(__name__)

# How much of the source text the drawing call is given. A figure describes one
# stretch of a passage, not all of it, but which stretch is not known here —
# and a reading passage is ~900 words, which is affordable for a call this
# valuable. Truncated only to keep a runaway script from blowing the budget.
_MAX_SOURCE_CHARS = 7000

# Three, not two: a retry now carries the reason the last one was rejected, so
# each attempt is corrective rather than another roll of the same dice. Two
# blind attempts reproduced the same fault twice running on the live turbine.
_REDRAW_ATTEMPTS = 3
_REWRITE_ATTEMPTS = 2

# The caption printed beside a gap, and the gap itself. 165 corpus labels run
# 1-4 words with a median of 1, so one word of slack over the longest is
# generous — beyond it the model has stopped naming a field and is writing the
# rubric again, which is the thing this repair exists to remove. The gap form
# matches the corpus's inline route and GAP_MARKER, which is what makes the
# repaired question self-contained.
_MAX_LABEL_WORDS = 5
_GAP = "______"
# "3." / "3)" / "3:" written in front of a label the model was asked to give
# bare, and the punctuation it trails one with. Both stripped so the question
# reads "Preferred start date: ______" and not "3. Preferred start date:: ______".
_LABEL_PREFIX = re.compile(r"^\s*\d+\s*[.):]\s*")
_LABEL_TRAILING = re.compile(r"[\s:.…]+$")


def _vocab(forms: set[str]) -> str:
    return ", ".join(f"`{f}`" for f in sorted(forms))


def _system() -> str:
    """The drawing prompt, with the form lists filled in from the validator.

    Generated rather than written out so the prompt cannot offer a form the
    normaliser would silently replace — the drift that put `stack` and `panel`
    in one list and not the other when the vocabulary was last widened.
    """
    # Substitution, not `str.format`: the prompt prints the JSON schema the
    # model must return, and every brace in it would have to be doubled.
    out = FIGURE_DRAW_SYSTEM
    for token, forms in (
        ("{apparatus_forms}", _APPARATUS_FORMS),
        ("{layer_forms}", _LAYER_FORMS),
        ("{panel_forms}", _PANEL_FORMS),
    ):
        out = out.replace(token, _vocab(forms))
    return out


# ---------------------------------------------------------------------------
# Scoring — is the redraw actually better than what it replaces?
#
# A redraw that validates is not automatically an improvement: the model can
# return a legal figure that is blander than the one it was given. So both are
# scored on the three things the live failures were made of, and the new one is
# kept only if it does not lose.
# ---------------------------------------------------------------------------


def figure_richness(visual: object) -> tuple[int, int, int]:
    """(distinct real forms, joins, callouts carrying context).

    Every term is one of the measured defects. `box` and the environment forms
    are excluded from the first: a drawing of nothing but boxes standing on
    hatching is the complaint, and counting the hatching hid it.
    """
    if not is_diagram(visual):
        return (0, 0, 0)
    parts = diagram_parts(visual)
    forms = {
        str(p.get("form"))
        for p in parts
        if str(p.get("form")) not in {"box", "ground", "liquid", ""}
    }
    joins = len(diagram_links(visual)) + sum(
        1 for p in parts if p.get("in") or p.get("attach")
    )
    context = sum(
        1
        for label in diagram_labels(visual)
        if DIAGRAM_GAP_RE.search(str(label.get("text") or ""))
        and len(DIAGRAM_GAP_RE.sub(" ", str(label.get("text") or "")).split()) >= 2
    )
    return (len(forms), joins, context)


# A callout that DEFINES its own answer, which is the shape the redraw fell
# into on 2026-08-28 once it was handed the question text to work from:
#
#   "The vertical structure that supports the turbine is the __1__"
#   "The source of artificial light that mimics sunlight for the plants is
#    the __2__"
#
# A student fills those from general knowledge without opening the passage,
# which is the opposite of what a reading question is for. Cambridge never
# writes one: it states what HAPPENS at the part ("Air bubbles result from the
# __25__ behind blades"), so the reader has to have read the text to confirm
# it. The first pass writes its QUESTION text that way — "Label 1 on the
# diagram: the vertical structure that supports the turbine" — and the redraw
# copied the wording straight across.
#
# Matched on the copula, not on the gap's position: Cambridge does end a
# callout with its blank ("Hydraulic motors drive __22__"), so position alone
# would refuse the real thing. What gives a definition away is a noun phrase
# with a relative clause resolved by "is/are the ___".
_DEFINITION_RE = re.compile(
    r"\b(?:that|which|who|used to|responsible for)\b[^.]*?\b(?:is|are)\b"
    r"\s+(?:the\s+|a\s+|an\s+)?__\d+__\s*[.)]?\s*$",
    re.I,
)

# The same thing written as a caption, which is how the model evaded the rule
# above once it was enforced:
#
#   "Draws liquid from the reservoir and delivers it to the grow trays - the __1__"
#   "Provides a spectrum tailored to photosynthesis for the plants - the __2__"
#
# A long function description, a dash, and the answer's slot. Cambridge does
# print a captioned blank — "Average distance travelled: __24__" (Cambridge 7
# Test 2) — so the punctuation alone cannot decide it. What separates them is
# length and the article: a short noun phrase naming a QUANTITY, against a
# clause describing what the part DOES and then pointing at "the ___".
_CAPTION_DEF_RE = re.compile(
    r"^(?P<lead>.{0,200}?)\s*[-‐-―:]\s*(?:the|a|an)\s+__\d+__\s*[.)]?\s*$",
    re.I,
)
_CAPTION_MAX_WORDS = 5


def _defines_its_answer(visual: object) -> list[str]:
    out: list[str] = []
    for label in diagram_labels(visual):
        text = str(label.get("text") or "")
        if _DEFINITION_RE.search(text):
            out.append(text)
            continue
        caption = _CAPTION_DEF_RE.match(text)
        if caption and len(caption.group("lead").split()) > _CAPTION_MAX_WORDS:
            out.append(text)
    return out


def _prints_an_answer(visual: object, answer_key: dict) -> bool:
    return bool(self_answering_labels(visual, answer_key))


# What a figure has to already be for the redraw to be skipped. Every hosted
# call costs 30-90s, and a set whose first pass got the figure right does not
# need a second one.
#
# Calibrated on the five live sets of 2026-08-28: they scored (1,0,0), (5,3,0),
# (4,2,0), (2,2,0) and (3,0,0), and the redraw improved every one of them. The
# bar sits above all five, because a figure rich in forms and joins can still
# carry three bare blanks — set 2 did, and that is the defect the student
# actually sees.
_ENOUGH_FORMS = 3
_ENOUGH_JOINS = 2


def already_good(visual: object) -> bool:
    """Is this figure already what the second pass would be asked to make?"""
    forms, joins, context = figure_richness(visual)
    numbered = [
        label
        for label in diagram_labels(visual)
        if DIAGRAM_GAP_RE.search(str(label.get("text") or ""))
    ]
    # Every numbered callout carries context, not merely some of them: the
    # student meets each gap on its own.
    return (
        forms >= _ENOUGH_FORMS
        and joins >= _ENOUGH_JOINS
        and bool(numbered)
        and context == len(numbered)
    )


# ---------------------------------------------------------------------------
# The redraw
# ---------------------------------------------------------------------------


async def redraw_diagram(
    result: dict, source: str, *, source_label: str = "Passage"
) -> bool:
    """Draw the set's figure again in a call that does nothing else.

    Returns True if the figure was replaced. The original is kept on any
    failure — an unusable reply leaves the set exactly as it was found, which
    is the same bargain every repair in this codebase strikes.
    """
    visual = result.get("visual")
    if not is_diagram(visual):
        return False
    # Settle the figure BEFORE it is used as the thing to beat. Every reply is
    # normalised below, and listening normalises its original first, but reading
    # normalises AFTER this pass — so on that path a raw original was being
    # compared with a normalised reply and the reply won points on the
    # difference alone. Normalising here makes the comparison like-for-like
    # whoever calls, and it is idempotent, so the trainers' own calls still
    # stand.
    # Not written back: "the original is kept on any failure" is this pass's
    # standing promise, and a set that came out normalised by a redraw that
    # never replaced anything would break it.
    visual = normalize_diagram(visual) or visual

    answer_key = result.get("answer_key") or {}
    questions = result.get("questions") or []
    # What the figure MUST carry, which is what the questions ask about — not
    # what the broken drawing happens to have on it. `labelling_numbers` is
    # documented as exactly that: "the question numbers a drawn diagram has to
    # carry a gap for".
    #
    # 🔬 Live 2026-08-29: a diving suit whose four callouts wrote the blank as
    # a bare row of underscores — "The _______ on the deck" — so the figure
    # carried no gaps at all and the student saw four leader lines with no
    # numbers. Reading the numbers off the drawing gave up on the figure most
    # worth redrawing, and they were always going to come from the questions.
    #
    # 🔬 And live 2026-09-01, the half of that which reading the drawing FIRST
    # left open: a figure with SOME of its gaps — one, for four questions — is
    # broken in the same way, and a non-empty list meant the questions were
    # never consulted. So the redraw asked the model to reproduce the very
    # deficiency it had been called to fix; the model obeyed, `got != wanted`
    # passed, and `diagram_error` then refused the reply for having "1 gap(s)
    # drawn for 4 question(s)". Three attempts, all doomed before the first
    # call, and it happened three times in one 60-set sweep.
    wanted = sorted(labelling_numbers(questions), key=lambda g: int(g))
    if not wanted:
        # No labelling question to answer to: the drawing's own gaps are the
        # only statement of what it is for.
        wanted = sorted(diagram_gaps(visual), key=lambda g: int(g))
    if not wanted:
        return False
    # "Good enough to skip" means good enough AND legal. A figure can score
    # well on shapes and joins and still be refused — filler boxes holding the
    # gaps is exactly that shape — and skipping the call there throws the whole
    # set away to save one request.
    if already_good(visual) and not diagram_error(visual, questions, answer_key):
        logger.info("figure redraw skipped: the first pass drew it well enough")
        return False

    # The answers are handed over precisely so the figure can avoid printing
    # them. Without them the model reliably writes one gap's answer into
    # another gap's callout — the same failure `blank_self_answering_labels`
    # exists to clean up after the first pass.
    gaps = "\n".join(
        f"  __{g}__  is keyed to the answer: {str(answer_key.get(g) or '').strip()!r}"
        for g in wanted
    )
    asked = "\n".join(
        f"  {q.get('number')}: {str(q.get('question') or '').strip()}"
        for q in questions
        if str(q.get("number")) in set(wanted)
    )
    # What the exam's own figures of this family look like, retrieved from the
    # conventions distilled out of the books. Empty until
    # `tools/build_figure_knowledge.py --ingest` has run, so this degrades to
    # the prompt-only behaviour rather than failing.
    conventions = figure_conventions(
        FAMILY_BY_KIND.get(str(visual.get("kind")), ""),
        module="reading" if source_label == "Passage" else "listening",
        subject=str(visual.get("title") or ""),
    )
    prompt = (
        f"{source_label}:\n{str(source or '')[:_MAX_SOURCE_CHARS]}\n\n"
        f"Figure title: {str(visual.get('title') or '').strip()}\n\n"
        f"{conventions}\n"
        f"The gaps this figure must carry, and the answer each is keyed to:\n{gaps}\n\n"
        # Labelled as context, not as a template. Handed over plainly, the
        # model copied the question's wording into the callout verbatim, and a
        # question may define its answer where a callout never may.
        f"The questions that point at them. These tell you WHICH part each "
        f"gap sits on. Do NOT copy their wording into the callouts:\n{asked}\n\n"
        "Draw the figure."
    )

    before = figure_richness(visual)
    # Is the figure we are replacing already unusable? If so this call is a
    # rescue, not an improvement, and it is judged on validity alone. Without
    # this the redraw could reach a legal figure and still be discarded for not
    # being richer — and the whole set died with it.
    broken_before = bool(diagram_error(visual, questions, answer_key))
    if broken_before:
        logger.info("figure redraw is a rescue: the set will be refused as it is")

    def illegal(drawn: dict) -> str | None:
        """Why this redraw cannot SHIP, or None if it could.

        Split from the quality rules below on purpose. A redraw that is merely
        plainer than we hoped is still a figure a student can sit; one that
        drops a gap or prints an answer is not, and only the second kind may
        cost the set.

        Phrased as an instruction rather than a diagnosis, because the reason
        is fed straight back into the next attempt. Blind retries on the same
        prompt reproduced the same fault twice running: asked to redraw a
        turbine whose gaps are keyed 'Tower', 'Rotor' and 'Generator', the
        model printed those very words as its orientation names on both tries,
        having no way to learn what went wrong.
        """
        # Same gaps, exactly once each. A redraw that dropped a gap would
        # leave a question pointing at nothing, and one that invented a gap
        # would put a blank on the paper no question asks about — audit #24.
        got = sorted(diagram_gaps(drawn), key=lambda g: int(g))
        if got != wanted:
            return (
                f"the figure carried gaps {got} but must carry exactly "
                f"{wanted}, each one exactly once"
            )
        problem = diagram_error(drawn, questions, answer_key)
        if problem:
            return problem
        defined = _defines_its_answer(drawn)
        if defined:
            return (
                f"{len(defined)} callout(s) DEFINE their own answer, e.g. "
                f"{defined[0]!r}. Say what happens at the part instead, the "
                "way the exam does"
            )
        leaked = [a for _, a, _ in self_answering_labels(drawn, answer_key)]
        if leaked:
            return (
                f"the figure PRINTS the answers {leaked}, so it answers its "
                "own questions. Those words may not appear anywhere on it — "
                "not as a part's name, not in a callout. Name other parts "
                "instead, or leave those parts unnamed"
            )
        return None

    def too_plain(drawn: dict) -> str | None:
        """Why this redraw is not GOOD enough, given it is legal.

        Worth another attempt, never worth the set: `_fallback` below keeps
        the last figure that got this far, so running out of attempts on a
        quality complaint ships the plainer drawing instead of nothing.
        """
        # The context has to reach the STUDENT, and a gap moved into a part's
        # printed name carries none. Asked to redraw the turbine, the model
        # satisfied every other rule by putting all three gaps in names and
        # writing no callouts at all — a better drawing with the same empty
        # question on it, which is the defect this pass exists to remove.
        #
        # `layers` is exempt: the exam really does print the blank inside the
        # band (Cambridge 2 Test 1's airport cross-section), and there the
        # position between the water and the sand IS the context.
        if diagram_layout(drawn) != LAYERS:
            in_callouts = sum(
                len(DIAGRAM_GAP_RE.findall(str(label.get("text") or "")))
                for label in diagram_labels(drawn)
                if len(
                    DIAGRAM_GAP_RE.sub(" ", str(label.get("text") or "")).split()
                )
                >= 2
            )
            if in_callouts * 2 < len(wanted):
                return (
                    f"only {in_callouts} of {len(wanted)} gaps sit in a callout "
                    "that says anything. A gap printed as a part's name gives "
                    "the student no fact to match against the text — put most "
                    "of them in callouts that state what happens at the part"
                )
        # When the figure being replaced is itself INVALID, validity is the
        # whole bar and richness does not enter into it. Measured over three
        # live sweeps of 20 sets: the commonest single cause of a discarded set
        # was a diagram whose gaps sat on plain boxes added to hold them —
        # `diagram_error` refuses that, the redraw was reaching a legal figure,
        # and this rule threw it away for not also being richer. A plainer
        # figure that ships beats a richer one that does not exist.
        if broken_before:
            return None
        # Otherwise: not worse on any axis, better on at least one. A legal but
        # blander figure is not worth the substitution.
        after = figure_richness(drawn)
        if any(a < b for a, b in zip(after, before)) or after == before:
            return (
                f"the figure is no richer than the one it replaces "
                f"({before} -> {after}: distinct forms, joins, callouts with "
                "context). Draw more of the real parts, join them, and give "
                "each callout a clause"
            )
        return None

    def repairable(drawn: dict) -> dict | None:
        """The attempt as it would SHIP, if the free repairs make it legal.

        `blank_gapped_part_names` and `blank_self_answering_labels` run on
        whatever this pass installs, moments later, and both are deterministic
        and free. An attempt they would cure is therefore not unusable — it is
        a figure one deletion away from the paper, and discarding it costs the
        whole set.

        Judged, never assumed: the repaired copy goes back through `illegal`,
        so a fault the deletions do NOT reach still disqualifies it.

        🔬 The verification sweep of 2026-09-01 measured what this was costing.
        11 of the 20 rejected redraws were the same complaint — the figure
        printing a part's name while that part's own gap asks for it — which is
        precisely what `blank_gapped_part_names` rubs out. `r_diagram_machine`
        spent all three attempts on it and was refused still holding its
        ORIGINAL figure: the bare-underscore drawing the redraw had been called
        to replace.
        """
        trial = {
            "visual": deepcopy(drawn),
            "questions": questions,
            "answer_key": answer_key,
        }
        blank_gapped_part_names(trial)
        blank_self_answering_labels(trial)
        return None if illegal(trial["visual"]) else trial["visual"]

    prompt_now = prompt
    # The best LEGAL figure any attempt reached, kept in case the attempts run
    # out on a quality complaint.
    #
    # 🔬 2026-09-01: `r_diagram_machine_r6` died with three attempts spent and
    # a legal drawing among them, because a rejected attempt was discarded
    # whole. Rejecting is how the next attempt learns; discarding is how the
    # set is lost, and they were the same line.
    fallback: dict | None = None
    # And the best attempt that only the free repairs stand between and the
    # paper. Kept apart from `fallback` so an outright-legal figure still wins.
    rescued: dict | None = None
    for _ in range(_REDRAW_ATTEMPTS):
        try:
            # No `max_tokens` cap, so the configured 16384 applies. A
            # reasoning model thinks out of the SAME budget it writes from,
            # and this is the densest structured output in the app — a whole
            # figure, not the one sentence the flow chart's rewrite returns.
            # `tools/_diag_token_cap_probe.py` measured that a one-sentence
            # reply survives any cap from 256 up; a figure has no such margin,
            # and the failure mode is silent (empty content, read as "No JSON
            # object found in response"). See `client._chat`.
            # `skip_finetune`, for the reason `get_llm_client` documents: the
            # generator's SFT corpus never mentions a figure, so the local
            # checkpoint answers in its trained shape instead of the schema
            # this prompt asks for. A figure call that lands on the checkpoint
            # is the failure this module was written to fix, not a way to fix
            # it.
            reply = await get_llm_client(
                "generator", skip_finetune=True
            ).complete_json(
                _system(),
                [{"role": "user", "content": prompt_now}],
            )
        except Exception:
            return False

        drawn = reply.get("visual")
        if not isinstance(drawn, dict):
            # An explicit `{"visual": null}` is the model saying it cannot draw
            # this subject, which is a valid answer and not worth a retry.
            return False
        drawn.setdefault("kind", "diagram")
        drawn.setdefault("title", visual.get("title"))
        if not is_diagram(drawn):
            logger.info("figure redraw rejected: reply is not a diagram")
            continue
        drawn = normalize_diagram(drawn)

        unusable = illegal(drawn)
        verdict = unusable or too_plain(drawn)
        if verdict:
            if not unusable:
                fallback = fallback or drawn
            elif rescued is None:
                rescued = repairable(drawn)
            logger.info("figure redraw rejected: %s", verdict)
            # Fed back, so the next attempt is corrective rather than another
            # roll of the same dice.
            prompt_now = (
                f"{prompt}\n\nYour previous attempt was REJECTED because "
                f"{verdict}. Draw it again, fixing exactly that."
            )
            continue

        result["visual"] = drawn
        return True

    # Out of attempts. A plainer legal figure still beats the unusable one it
    # was drawn to replace — but only then: when the original is fine, a figure
    # rejected for being no better is exactly what should not be substituted.
    keep = fallback or rescued
    if broken_before and keep is not None:
        logger.info("figure redraw kept the %s attempt",
                    "plainest legal" if fallback else "repaired")
        result["visual"] = keep
        return True
    return False


# ---------------------------------------------------------------------------
# Self-answering callouts
# ---------------------------------------------------------------------------


async def _rewrite_callout(
    text: str, banned: list[str], title: str, answer_key: dict
) -> str | None:
    """Reword one callout so it stops printing another gap's answer.

    The gap is filled in with its own keyed answer before the call and blanked
    again afterwards, for the reason `_flow._rewrite_step` documents at length:
    shown a `__4__`, the model answers it instead of copying it through. It is
    completing a sentence whose missing word the context makes obvious, and no
    wording stops that.
    """
    filled = text
    restore: list[tuple[str, str]] = []
    for gap in DIAGRAM_GAP_RE.findall(text):
        answer = str((answer_key or {}).get(gap) or "").strip()
        # A gap whose OWN answer is the word being removed cannot be filled in:
        # both copies would read alike and the rewrite would take them both.
        if not answer or any(norm(b) in norm(answer) for b in banned):
            continue
        filled = filled.replace(f"__{gap}__", answer, 1)
        restore.append((gap, answer))

    forbidden = "; ".join(sorted({b.strip() for b in banned if b.strip()}))
    prompt = (
        f"Figure title: {title}\n\n"
        f"The callout to rewrite:\n{filled}\n\n"
        f"Words this callout must NOT contain: {forbidden}\n\n"
        "Rewrite that one callout."
    )
    try:
        # Hosted for the same reason the redraw is: this is figure text, and
        # the checkpoint has never been trained on any.
        reply = await get_llm_client(
            "generator", skip_finetune=True
        ).complete_json(
            DIAGRAM_RECALLOUT_SYSTEM,
            [{"role": "user", "content": prompt}],
            required_keys=("callout",),
        )
    except Exception:
        return None
    out = str(reply.get("callout") or "").strip()
    if not out:
        return None

    # Put each gap back where its answer now sits — exactly one occurrence, or
    # the blank would land on the wrong words.
    for gap, answer in restore:
        lowered = out.lower()
        needle = answer.lower()
        if lowered.count(needle) != 1:
            return None
        at = lowered.index(needle)
        out = out[:at] + f"__{gap}__" + out[at + len(answer) :]
    return out


async def repair_self_answering_callouts(
    result: dict,
) -> list[tuple[str, str]]:
    """Reword a callout that prints the answer another gap asks for.

    `blank_self_answering_labels` deletes the offending text, which was right
    while a callout was a bare noun phrase — there was nothing in it to reword,
    and losing it cost the student one orientation label. Now that a callout
    carries a clause from the passage, deleting it takes the student's context
    with it, and a callout holding its OWN gap cannot be deleted at all without
    orphaning a question. So those are reworded, exactly as a flow chart's box
    is. Returns the (before, after) pairs the caller can log.
    """
    visual = result.get("visual")
    if not is_diagram(visual):
        return []
    answer_key = result.get("answer_key") or {}
    hits = [
        (answer, text)
        for _, answer, text in self_answering_labels(visual, answer_key)
        if DIAGRAM_GAP_RE.search(text)
    ]
    if not hits:
        return []

    title = str(visual.get("title") or "")
    changed: list[tuple[str, str]] = []

    # One call per offending callout, not per clash: a single callout can print
    # two different gaps' answers, and rewriting it twice would undo the first.
    by_text: dict[str, list[str]] = {}
    for answer, text in hits:
        by_text.setdefault(text, []).append(answer)

    for text, banned in by_text.items():
        for _ in range(_REWRITE_ATTEMPTS):
            rewritten = await _rewrite_callout(text, banned, title, answer_key)
            if not rewritten:
                continue
            # The gaps are the figure's coupling to the questions. The model
            # habitually answers one instead of copying it through, which is
            # why every rewrite is judged rather than trusted.
            if DIAGRAM_GAP_RE.findall(text) != DIAGRAM_GAP_RE.findall(rewritten):
                continue
            trial = {
                **visual,
                "labels": [
                    {**lb, "text": rewritten}
                    if str(lb.get("text")) == text
                    else lb
                    for lb in diagram_labels(visual)
                ],
            }
            # Either the word survived the rewrite, or the new wording printed
            # some other gap's answer. Both leave the figure no better.
            if any(
                t == rewritten for _, _, t in self_answering_labels(trial, answer_key)
            ):
                continue
            visual["labels"] = trial["labels"]
            changed.append((text, rewritten))
            break

    return changed


async def condense_doubled_callouts(result: dict) -> list[tuple[str, str]]:
    """Write two callouts on one part as the single one the exam prints.

    `merge_doubled_callouts` folds the pair whenever the join is short enough
    to print, and stops where the join would overrun the callout word cap — which
    is where this call takes over. It is the same bargain
    `repair_self_answering_callouts` strikes: a few hundred tokens against a
    ~4k-token regeneration of a set whose only fault is a join.

    🔬 Live 2026-09-02, `r_diagram_machine_r3`. Two callouts sat on `gate` —
    "When the boat enters, the __2__ lowers to seal the lock" and "During the
    final stage, the __8__ is lifted, allowing the boat to exit" — 24 words
    joined, four over the cap. The same figure carried __6__ and __7__ in ONE
    legal callout on `balance`, so the model had already shown it knew the
    shape; it simply did not apply it twice.

    Judged rather than trusted, on exactly what makes the reply usable: both
    gaps still there, spelled the same, printed once each, and inside the cap.
    Anything else leaves the pair alone for the gate to refuse, which is what
    would have happened anyway.
    """
    visual = result.get("visual")
    if not is_diagram(visual):
        return []
    doubled: dict[str, list[dict]] = {}
    for label in diagram_labels(visual):
        if not DIAGRAM_GAP_RE.search(_text(label.get("text"))):
            continue
        at = _slug(label.get("at") or label.get("target") or label.get("part"), "")
        doubled.setdefault(at, []).append(label)

    title = str(visual.get("title") or "")
    changed: list[tuple[str, str]] = []
    for at, group in doubled.items():
        if len(group) < 2:
            continue
        texts = [_text(lb.get("text")) for lb in group]
        wanted = [gap for text in texts for gap in DIAGRAM_GAP_RE.findall(text)]
        for _ in range(_REWRITE_ATTEMPTS):
            merged = await _merge_callouts(texts, title)
            if not merged:
                continue
            # The gaps are the figure's only coupling to the questions. The
            # model habitually answers one instead of copying it through, which
            # is why every reply in this module is judged.
            if DIAGRAM_GAP_RE.findall(merged) != wanted:
                continue
            if len(merged.split()) > _MAX_CALLOUT_WORDS:
                continue
            group[0]["text"] = merged
            visual["labels"] = [
                lb for lb in diagram_labels(visual)
                if not any(lb is dropped for dropped in group[1:])
            ]
            changed.append((at, merged))
            break
    return changed


async def _merge_callouts(texts: list[str], title: str) -> str | None:
    """Ask for two callouts as one. Returns None on anything unusable.

    The gaps are sent as they stand rather than filled in with their answers,
    which is the opposite of `_rewrite_callout`'s bargain and deliberate: that
    repair needs the model to read around a blank it must not reproduce, where
    this one needs both blanks copied through untouched. Handing over the
    answers here would invite the model to write them into the line it returns,
    and the figure would then print what its own questions ask for.
    """
    listed = "\n\n".join(f"Callout {i}: {t}" for i, t in enumerate(texts, start=1))
    try:
        # Hosted, like every other call in this module: this is figure text,
        # and the checkpoint was never trained on any.
        reply = await get_llm_client("generator", skip_finetune=True).complete_json(
            DIAGRAM_MERGE_CALLOUT_SYSTEM,
            [{"role": "user", "content":
              f"Figure title: {title}\n\n{listed}\n\nWrite them as one callout."}],
            required_keys=("callout",),
            max_tokens=256,
        )
    except Exception:
        return None
    return str(reply.get("callout") or "").strip() or None


# The fewest questions a set may be left holding after a deletion. The reading
# corpus writes 8 at the mode and ranges 6-15, so six is the bottom of what the
# corpus itself calls a set; below it the student has been handed a fragment.
_MIN_KEPT_QUESTIONS = 6


def drop_chart_transcriptions(result: dict) -> list[str]:
    """Delete the chart questions a student can answer with the source covered.

    A chart prints every value it holds, so "The number of visitors in March
    was ______" keyed 150000 is answered off the drawing —
    `chart_transcription_error` refuses a set carrying two or more, and
    tolerates one, because reading a value off a figure is a task the exam does
    set. This deletes the surplus and leaves that one.

    🔬 Live 2026-09-02, `l_chart_r3`: nine questions, seven of them good — the
    reason for the July dip, the category behind the August rise, the increase
    expected next year, none answerable without the recording — and two that
    simply read March and September off the line. The corrective retry came
    back with the same fault and the whole part died: a 521-word script, its
    audio, a chart and seven working questions, for two that tested nothing.

    Deleting rather than rewriting, and deterministically: a replacement
    question has to be answerable from the script, which is a model call that
    can fail, where a question testing nothing is no loss to remove. The set
    keeps contiguous numbering — `renumber` moves the key and the per-answer
    metadata with it.

    Practice only, and only while enough of the set survives. A full-test part
    needs exactly ten questions, so there a deletion trades one refusal for
    another and the part is regenerated instead.
    """
    flagged = chart_transcriptions(result)
    # One is legal, so only the surplus goes — and the FIRST is kept, which is
    # the one the student meets earliest in a block that ascends.
    doomed = set(flagged[1:])
    if not doomed:
        return []
    # 🔬 Live 2026-09-02, on the first sweep run after this repair was written:
    # a chart part came back with SIX of its questions read off the figure, so
    # the deletion would have shipped a four-question set. That is not the
    # fault this repair is for — the rule's own words are "one such question is
    # a task the exam sets, a block of them is a figure standing in for the
    # passage" — and a set that is mostly transcription has to be written
    # again, not trimmed. So the deletion stops where the set stops being one:
    # the reading corpus writes 8 questions at the mode and ranges 6-15
    # (`_numbering`), so a repaired set that keeps six is still inside what the
    # corpus itself produces, and one that cannot is left for the retry.
    if len(result.get("questions") or []) - len(doomed) < _MIN_KEPT_QUESTIONS:
        return []

    result["questions"] = [
        q for q in (result.get("questions") or [])
        if not (isinstance(q, dict) and str(q.get("number")) in doomed)
    ]
    # Before the renumbering, not after: `renumber` maps the numbers that
    # SURVIVE, so a stale entry left under a dropped number would collide with
    # whichever question renumbers onto it and one of the two would be lost.
    for field in ("answer_key", "accepted_variants", "answer_positions"):
        held = result.get(field)
        if isinstance(held, dict):
            result[field] = {
                k: v for k, v in held.items() if str(k) not in doomed
            }
    renumber(result, 0)
    return sorted(doomed, key=int)


# ---------------------------------------------------------------------------
# The dangling completion repair.
#
# A completion question that shows no gap and names no slot on the figure —
# "Complete the membership details below." carried as the question itself —
# points at a block the student never sees. `dangling_structure_error` refuses
# it, and refusing is the wrong answer: measured live, the corrective retry
# does NOT rescue one. Both attempts of both listening e2e runs failed on it,
# and on 2026-09-01 the same fault cost two of the three refusals in a 36-set
# reading sweep (`r_diagram_apparatus_r3`, `r_diagram_cycle_r5`), where there
# was no repair at all — only the gate.
#
# So the question is given a gap of its own instead. Naming the field one
# answer belongs to is a small task the model does reliably, and it costs a
# few hundred tokens against a ~4k regeneration that historically fails twice.
# Shared, because reading and listening were never different here: only
# listening had the repair.
# ---------------------------------------------------------------------------


def _clean_label(value: object) -> str:
    return _LABEL_TRAILING.sub("", _LABEL_PREFIX.sub("", str(value).strip()))


def _contains_words(haystack: str, needle: str) -> bool:
    """Is `needle` a run of whole words inside `haystack`?

    Whole words, not a substring: the answer 'ice' does not leak through a
    label reading 'device', and matching on the raw substring said it did.
    """
    hay = norm(haystack).split()
    want = norm(needle).split()
    if not want or not hay:
        return False
    return any(hay[i:i + len(want)] == want for i in range(len(hay) - len(want) + 1))


async def write_field_labels(
    source: str, gaps: list[tuple[str, str]]
) -> dict[str, str] | None:
    """Ask the model only to name each gap's field — the half it does not drop.

    Measured over 11 live artifacts: where the checkpoint emitted a `visual` at
    all it coupled every cell to its question correctly, 24 of 24. What it
    drops is the form itself, leaving the block's shared rubric behind as the
    question ("Complete the membership details below."). Naming the field one
    answer belongs to is a different task from writing the question and the
    form as one coupled object, and the gap is then placed here rather than
    asked for.

    The reply is a few hundred characters, so unlike a whole part it fits under
    the echo cap — a corrective retry can actually see what it wrote.
    """
    numbers = [number for number, _ in gaps]
    listed = "\n".join(f"{number}. {answer}" for number, answer in gaps)

    def check(reply: dict) -> str | None:
        labels = reply.get("labels")
        if not isinstance(labels, dict):
            return "`labels` must be an object with one gap number per key"
        blank = [n for n in numbers if not str(labels.get(n) or "").strip()]
        if blank:
            return (
                f"no label was written for gap {', '.join(blank)}; write one "
                "for every number you were given"
            )
        cleaned = [_clean_label(labels[n]) for n in numbers]
        overlong = [n for n, text in zip(numbers, cleaned)
                    if len(text.split()) > _MAX_LABEL_WORDS]
        if overlong:
            return (
                f"the label for gap {', '.join(overlong)} is too long to print "
                f"beside a gap; name the field in at most {_MAX_LABEL_WORDS} "
                "words"
            )
        # A form repeats a column heading down its rows and the row tells the
        # two apart, which is why 44.8% of corpus forms carry a duplicate. An
        # inline gap has no row, so here a repeat leaves two questions reading
        # identically and the student cannot tell which answer goes where.
        lowered = [text.lower() for text in cleaned]
        if len(set(lowered)) != len(lowered):
            return (
                "two gaps were given the same label; each label must name what "
                "makes its own gap different from the others"
            )
        # 🔬 2026-09-01: a label that PRINTS its own answer turns the repaired
        # question into "Firn zone: ______" keyed 'firn zone'. The listening
        # copy never hit this because a form field names a category and the
        # answer fills it; a diagram gap is keyed to the part's own name often
        # enough that the model reaches for it.
        keyed = dict(gaps)
        leaking = [n for n, text in zip(numbers, cleaned)
                   if _contains_words(text, keyed[n])]
        if leaking:
            return (
                f"the label for gap {', '.join(leaking)} contains that gap's "
                "own answer, so it answers its own question. Name the field "
                "without using the answer's words"
            )
        return None

    try:
        # Hosted: naming the fields of a printed form is figure work, and the
        # checkpoint's corpus never described a figure. Same routing fault as
        # the diagram relabel and the flow chart's rewrite, found together on
        # 2026-08-28.
        reply = await get_llm_client(
            "generator", skip_finetune=True
        ).complete_json(
            FORM_WRITER_SYSTEM,
            [{"role": "user", "content":
              f"Source:\n{str(source or '')[:_MAX_SOURCE_CHARS]}\n\nName the "
              f"field each of these {len(gaps)} answers fills.\n\n{listed}"}],
            required_keys=("labels",),
            validate=check,
            max_tokens=512,
        )
        # Read inside the try on purpose. `check` guarantees the shape only for
        # a client that honours the validate hook, and the caller's fallback
        # needs a None here rather than an exception thrown through it.
        return {n: _clean_label(reply["labels"][n]) for n in numbers}
    except Exception:
        return None


async def repair_dangling_completions(result: dict, source: str) -> None:
    """Give every completion question that shows no gap one of its own.

    The set keeps whatever `visual` it already has: rebuilding the form would
    reproduce the two-artifact coupling that is what the checkpoint drops, and
    a set whose visual is a map has no room for a second object anyway. The
    corpus's other route is single-artifact — 8% of listening completion items
    and 93.4% of reading's — so the question is moved onto that one, where
    there is no second half left to lose.

    Left alone if the labels cannot be written. The caller re-validates, so a
    question still pointing at nothing fails loudly rather than reaching a
    student.
    """
    questions = result.get("questions") or []
    dangling = dangling_completions(questions, result.get("visual"))
    if not dangling:
        return

    answer_key = result.get("answer_key") or {}
    gaps = [
        (str(q.get("number")), str(answer_key[str(q.get("number"))]))
        for q in dangling
        if str(q.get("number")) in answer_key
    ]
    if not gaps:
        return

    labels = await write_field_labels(source, gaps)
    if not labels:
        return
    for q in dangling:
        label = labels.get(str(q.get("number")))
        if label:
            q["question"] = f"{label}: {_GAP}"
