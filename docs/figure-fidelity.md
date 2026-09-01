# What the exam actually prints, and what we were printing

Written 2026-08-28, after the generated figures were called "too bad" for the
third time. The complaint was right, and the reason turned out not to be the
renderer.

## How this was checked

Not from memory, and not from a blog post. The 21 Cambridge IELTS books in
`backend/books/ielts book/` are page **scans** — one image per page, no text
layer — so a figure cannot be found by parsing the PDF. It can be found by
searching the OCR text the ingester already cached in `backend/data/ocr_cache/`
and rendering that page back out of the book.

```
PYTHONIOENCODING=utf-8 python tools/cambridge_figure_atlas.py --dpi 120
```

That is `backend/tools/cambridge_figure_atlas.py`. It found **233 figure pages
across 22 books**:

| family | pages |
|---|---|
| notes | 140 |
| table | 54 |
| map | 13 |
| flow chart | 12 |
| labelled diagram | 9 |
| plan | 5 |

The output is not committed — 144MB of page scans — but it regenerates from the
books in about a minute, and `tools/_atlas/` is gitignored.

A public description of the task type agrees with what the scans show, for what
it is worth: the labels "may consist of up to three words … taken directly from
the passage", and the diagram "typically uses callout labels with arrows or
lines pointing to specific parts"
([Cambridge English task-type activity](https://www.cambridgeenglish.org/images/ielts-academic-reading-task-type-10-diagram-label-completion-activity.pdf),
[IDP India](https://ieltsidpindia.com/blog/ielts-reading-diagram-labelling-completion-practice-and-tips)).
The books are the stronger evidence, because they show the *wording*.

## What Cambridge prints in a callout

This is the finding that mattered. Transcribed from the pages themselves:

**Cambridge 9, Test 3, Reading — "An Undersea Turbine"**
> Whole tower can be raised for **23** .......... and the extraction of seaweed from the blades
> Air bubbles result from the **25** .......... behind blades. This is known as **26** ..........
> Sea life not in danger due to the fact that blades are comparatively **24** ..........

**Cambridge 11, Test 1, Reading — "How a boat is lifted on the Falkirk Wheel"**
> A pair of **20** .......... are lifted in order to shut out water from canal basin
> A range of different-sized **23** .......... ensures boat keeps upright
> Hydraulic motors drive **22** ..........

**Cambridge 7, Test 2, Listening — "The Operational Cycle"**
> Float dropped into ocean and **23** .......... by satellite
> Average distance travelled: **24** ..........

**Cambridge 8, Test 1, Reading — "How the 1670 lever-based device worked"**
> a **12** .......... which beats each **13** ..........
> escapement (resembling **9** ..........)

Three things follow, and all three were being done wrong.

1. **A callout is a clause, not a label.** They run 3 to 17 words. They state a
   fact the passage supports, with the blank inside the sentence.
2. **A callout may carry two blanks** ("the **25** .......... behind blades.
   This is known as **26** ..........").
3. **Sentence callouts appear in BOTH papers.** This is not a Reading-only
   convention.

## What we were printing, and why

`_diagram.py` capped a callout at six words, under this comment:

> A callout is a noun phrase pointing at a part, the way the exam prints one
> ("Thread guide", "Hydraulic Motors"). **A sentence in a callout means the
> model has written prose into the drawing, which no exam diagram does.**

The exam does, in both papers, on every page above. The cap was the reason the
figures carried no passage context: it forbade the only place the context could
go. The generator prompt said the same thing in so many words — "A callout is a
LABEL, not a sentence: at most 6 words" — and its worked example showed
`{"at": "handle", "text": "__6__"}`, a bare blank, which is what the model
copied.

So a live set came back looking like this:

```
callout  '__1__'
callout  '__2__'
callout  '__3__'
```

A leader line pointing at a shape, with only "1 .........." at the end of it.
The student is asked to name a rectangle from nothing. Cambridge does print a
bare blank on a leader — Cambridge 9 Test 2's "Water Heater" does — but only
where a lettered answer box supplies the options, which this task type has not
got.

The renderer was not the problem. It had callout gutters and leader lines
already; it had simply been sized for "Thread guide", so a real Cambridge
callout would have run off the page.

## What changed

**Backend — `app/agents/_diagram.py`**
- The six-word cap is now 20 (longest measured: 17), with the measurements in
  the comment so the next person does not have to re-derive them.
- New refusal: if three or more numbered callouts are bare blanks and fewer
  than half carry context, the figure is rejected. Calibrated so the thinnest
  real example — the 1670 clock, 2 of 4 with context — still passes.

**Frontend — `components/practice/diagram.tsx`**
- Callouts wrap to two or three lines, measuring a blank at the width it
  actually *prints* (`__23__` is 6 characters in the payload and about 13 on
  the page) and keeping the blank atomic so it cannot break across lines.
- Gutters widened 168 → 214px, canvas 720 → 820, and the stacking now reserves
  the whole wrapped block's height instead of one line's.
- Callout blocks are **left-aligned on both sides**, which is what the exam
  does. Right-aligning the left column staircased the text away from its leader
  and read as a caption.
- `layers` and `tree` drew wider than the gutters allow. That was always 42px
  of overlap and became 88px once the gutters grew, so a strata section printed
  its callout on top of its own bands. Both now take the extra width only when
  they carry no callouts.
- **`scene` placed every label in a free grid cell** and returned no anchors at
  all, so the gutters were never used. That was right while labels were two or
  three words — it is what the official Cambridge sample does — and it put the
  first live redraw's three clauses straight across the turbine. The split is
  now by length, not by layout: a label that fits its cell stays at the
  feature, a clause goes to the margin, and the scene gives the margins back
  when it has one. Both halves are Cambridge's own behaviour on the same page.
- A part's name printed *below* a small shape was one unwrapped line measured
  against the shape, so "Circulation pump" under a disc ran the width of two
  cells and collided with the name under the next one. It wraps to the cell
  now.
- The ground's name is ranged left instead of centred. The ground spans the
  whole drawing, so its centre sits directly under whatever is in the middle of
  the figure, and "Base" printed through the tank name above it.

**Backend — deterministic geometry, `normalize_diagram`**

The prompt said "two parts must never be given the same cell" and the renderer
believed it. Live: a `valve` sensor was dropped on top of a water tank, so
"Water tank" and "Sensor unit" printed across each other, and a `ground` part
landed inside a foundation slab so "Sea bed" was written in the middle of it.

Geometry the generator can get wrong is geometry the generator should not be
trusted with — the same bargain the floor plan and the flow chart already
strike. Collisions are now settled rather than refused (refusing costs a whole
hosted regeneration): a part that overlaps is nudged to the first free cell,
nested parts are settled against their **container's** 3x3 sub-grid so nothing
leaves its shell, and the ground drops below everything and spans the width.

**Frontend — flow chart, notes, plan**
- Flow chart boxes are square, full-width and ranged left, with the title
  centred and bold above. Rounded tinted boxes centring a clause read as UI
  buttons; Cambridge 19 Test 3 and Cambridge 9 Test 1 set their steps as
  running text inside plain rectangles the width of the column.
- One gap mark everywhere. The plan printed `11 ········` in middots while
  every other figure printed periods, so a student met two different marks on
  one paper.

**Backend — `app/agents/_figure_pass.py` (new)**

The second pass the roadmap had been carrying as "the one next move". The
one-pass prompt has to write a passage, a question list, an answer key,
metadata *and* a figure; the diagram block alone is ~9,000 characters, and the
figure is what gets skimmed. This draws the figure again in a call that does
nothing else, with the passage and the keyed answers in front of it.

It is judged before it is kept, and never leaves a set worse than it found it:

- the same gaps, exactly once each;
- passes `diagram_error`;
- prints none of the answers;
- no callout defines its own answer;
- scores no worse on (distinct forms, joins, callouts with context), and better
  on at least one.

A rejection is fed back into the next attempt, so a retry is corrective rather
than another roll of the same dice. A figure the first pass already got right
skips the call entirely.

## Two faults found on the way

**Figure calls were landing on the local fine-tune.** `get_llm_client("generator")`
resolves to `ielts-multitask-generator`, whose SFT corpus never mentions a
figure — the exact case `skip_finetune=True` exists for. The flow chart's
self-answer rewrite had been calling it without the flag, which silently made
that repair a no-op.

**A token cap was suspected of the same thing, and measured instead.**
`tools/_diag_token_cap_probe.py` runs the real rewrite prompt against
gpt-oss-120b at each cap the codebase uses:

| cap | result |
|---|---|
| 128 | **empty content** |
| 256 | OK, 1.6s |
| 512 | OK, 1.8s |
| 1024 | OK, 3.9s |
| 2048 | OK, 1.5s |
| uncapped | OK, 1.8s |

So a reasoning model does eat its budget before it writes, but on a
one-sentence reply it does not get near it. The 256-token cap stays; the figure
call is left uncapped because a whole figure has no such margin.

## Measured on the live failures

`tools/_diag_redraw_live.py` reruns the second pass over the five reading sets
saved on 2026-08-28 — the ones the complaint was about. Richness is
(distinct forms, joins, callouts carrying context).

| set | before | after |
|---|---|---|
| cross_1 | (1, 0, 0) | (6, 6, 3) |
| cross_2 | (5, 3, 0) | (6, 6, 3) |
| cross_3 | (4, 2, 0) | (7, 9, 3) |
| cross_4 | (2, 2, 0) | (6, 11, 3) |
| cross_5 | (3, 0, 0) | (5, 4, 4) |

**5 of 5**, and it took three rounds of measurement to get there:

| round | redrawn | what was wrong |
|---|---|---|
| 1 | 0 of 5 | every call landed on the local fine-tune, and a 2048-token cap starved it |
| 2 | 3 of 5 | the callouts were definitions; blind retries repeated the same fault |
| 3 | 5 of 5 | definitions refused, retries corrective, callouts required a subject |

Rejections along the way were the guards working, not failing — a figure that
would have been worse was refused and the set left exactly as it was found.
The callouts the third round produced:

> The **1** .......... holds the plant roots and receives the nutrient solution.
> The **2** .......... supplies the specific light spectra required for photosynthesis.
> The **4** .......... circulates air to maintain uniform temperature and CO₂ levels.

## The engine now holds the knowledge, not the prompt

Everything above was found by a person reading the books and then writing what
they learned into a prompt by hand. That does not scale, and it is exactly how
the six-word cap got in: one wrong sentence, written with confidence, sitting in
the code for weeks.

So the conventions are now **extracted from the corpus and retrieved at
generation time**, the same way passages are already grounded.

`backend/tools/build_figure_knowledge.py` runs in two stages:

```
python tools/build_figure_knowledge.py --extract   # one focused call per page
python tools/build_figure_knowledge.py --ingest    # -> vector store
```

`--extract` reads the OCR of all 323 pages that introduce a figure and asks the
model for a structured record of each: the rubric, the title, every numbered
item with its blank normalised, the *pattern* behind each item, what the blank
asks for (`part_name` / `process` / `material` / `measurement` / …), the fixed
labels that orient the candidate, and 2–6 rules a generator could act on. OCR
noise is the reason this is a model call and not a regex — a dot leader comes
through as `ceccccesssssee` and numbers are routinely lost.

**261 records** came back:

| family | records |
|---|---|
| notes | 148 |
| table | 51 |
| form | 20 |
| map | 14 |
| flow chart | 12 |
| diagram | 8 |
| plan | 5 |

`--ingest` writes them to the existing vector store under
`source="figure-conventions"`, one chunk per figure plus one **family summary**
per type carrying the measured aggregates.

`app/rag/figures.py` is the read side. Given a question type it finds the family
the books use, retrieves that family's summary plus a real example, and returns
a block for the prompt. Three callers use it: the reading trainer, the listening
trainer, and the second-pass figure draw. Nearest-neighbour alone was not
enough — asked for "diagram reading termite mound" the store's best match was a
summary block about archaeology, because subject words dominate the embedding
and the corpus holds 148 notes records against 8 diagrams — so the family is
filtered for rather than hoped for.

It is grounding, never content. The block says in so many words not to reuse a
subject, a title or any wording; a student never sees a Cambridge page.

### It paid for itself immediately

Two live sets had been refused with *"the notes block carries 11 gaps; a printed
block is worth showing only for 2-10"*. Was the cap wrong? The corpus answers
without guessing:

| family | records | blanks: min–max | median |
|---|---|---|---|
| notes | 63 | 3–10 | 7 |
| table | 16 | 3–10 | 5 |
| form | 7 | 5–10 | 8 |

Cambridge never prints 11. The cap was right and the model was over-generating,
so the fix went into the prompt — *"Number 4 to 8 of them, and NEVER more than
10. Measured over 63 real Cambridge notes blocks…"* — instead of into the
validator, where raising it would have shipped a figure the exam does not print.

## Three more faults the live sweep turned up

Generating one set per figure type (`tools/_diag_figure_gallery_live.py`, 20
requests across both papers) found these:

- **`MapBlock` had never been reachable.** A renderer for an outdoor map —
  features at coordinates with roads between them — has existed for months, and
  no prompt ever emitted `kind: "map"`. Every outdoor place was drawn as a grid
  of rooms sharing walls, so a live set laid an excavated Roman town out as a
  floor plan. `figure_coverage.py` reported "yes" because the *plan* half of its
  "Map / Plan" row was reachable; that row is now split so the gap is visible.
- **Two more repairs were calling the local fine-tune.** The diagram's
  duplicate-answer relabel and the listening form's field-namer both used
  `get_llm_client("generator")` without `skip_finetune`. Both are figure work,
  and the checkpoint has never seen a figure — a live canal-lock set keyed two
  gaps `gate`, the repair silently failed, and the whole set was thrown away.
- **The listening token cap was the checkpoint's, applied to everything.** 4096
  was sized to fit the fine-tune's 8192 context. A figure-bearing request skips
  the fine-tune and lands on a reasoning model that spends the same budget
  thinking before it writes; it truncated mid-JSON on a live Part 2 diagram.
  Now applied only when the checkpoint is what answers.

## The table was making the same mistake as the diagram

Cambridge 19 Test 2 prints its table cells as *"using an app or by **7**
.........."* and *"often listening to a **9** .......... of a song"* — the blank
inside a phrase, which is what tells the candidate what to write. Ours asked the
model for a bare `"__<n>__"` cell, rendered a matched one as a grey `Q7` chip
(the one figure in the app not printing the exam's mark), and printed the raw
`__7__` marker for anything else, because `BLANK_RE` was anchored.

Fixed in three places, and the renumbering with it: `renumber` matched table
cells with that same anchored regex, so a phrase cell would have kept its local
number while its question moved to global numbering in a full test — the bug
`b089b4a` fixed for the diagram, one figure over.

## Making the figure usable, not just correct

A figure is printed once and asked about five times. A student answering "Label
3 on the diagram" was hunting for a small 3 among four others with a clock
running — and on a phone the figure and the questions were on *separate tabs*,
so finding it meant leaving the question, switching tab, reading, and switching
back. Once per blank.

Two changes:

- **The blank you are answering lights up.** Focusing an answer box marks the
  figure with the question's number and the matching blank turns accent-coloured
  with a soft plate behind it. Implemented as data attributes rather than props
  — every renderer tags its blanks `data-gap`, the figure wrapper carries
  `data-active-gap`, and one CSS rule does the rest — so nothing had to be
  threaded through six renderers and a dozen call sites.
- **The figure appears with the questions on small screens.** It is also the
  more faithful place for it: the exam prints the figure inside the question
  block, not in the reading passage.

While tagging the blanks, one more inconsistency surfaced: the floor plan
printed `11 ········` in middots while every other figure printed periods, so a
student met two different marks on one paper. One mark everywhere now.

## The chart was testing transcription

A bar, line or pie chart prints every value it holds — unlike a table, whose
whole point is the cell it leaves blank. So it was fatally easy to write
*"According to the chart, the average daily water use for bathing is ______"*
and key it to the number already drawn on the bar. Live: one reading set wrote
nine of those in a row, a listening set six, a pie set three. Every one
validated clean, and none of them needed the passage at all.

`chart_transcription_error` refuses a block of them now (one read-the-figure
item is a task the exam does set; a block of them is the figure standing in for
the text), matching numerically so a bar drawn at `58.0` and an answer written
`58` are the same thing. Tables are exempt — their answers are the cells the
figure does *not* print.

## Two renderer faults the map turned up

Making `kind: "map"` generatable exposed a renderer that had never had a real
payload through it:

- **It decided which feature was the lettered one by `shape !== "point"`** —
  the exact opposite of how the payload is written, since a lettered location
  is a point and a named landmark has a footprint. Every letter drew as a 5px
  dot with a 9px caption and every landmark drew as a box with its name printed
  across it. It now reads the label: a bare "A" is the letter, whatever its
  shape.
- **It drew a graticule.** Coordinates are how the payload says where a thing
  is; they are not something the exam prints, and a ruled grid behind a park is
  what makes it read as a floor plan — the confusion this figure was added to
  end.

The table gained a duplicate title in the same pass — the figure caption and
the new spanning header row both printing it — which the screenshot caught.

## The one that is still open

The redraw's first instinct is to write a **definition** of the answer:

> The vertical structure that supports the turbine is the **1** ..........

A student fills that in from general knowledge without opening the passage,
which is the opposite of what a reading question is for. Two guards refuse it
now (the copula form, and the caption form the model moved to as soon as the
first was enforced), and the prompt carries the rule with Cambridge's own
callouts as the model to copy.

The root cause sits further upstream: **the first pass keys its gaps to generic
part names** — `{"1": "Tower", "2": "Rotor", "3": "Generator"}` — and writes
question text that defines them ("Label 1 on the diagram: the vertical
structure that supports the turbine"). Cambridge keys its gaps to terms the
passage introduces and the reader would not guess: *cavitation*, *gondolas*,
*seaweed*. While the answer is the part's own generic name, any honest callout
about that part comes close to defining it. That is a change to the first
pass's answer selection, and it is the next thing worth doing.
