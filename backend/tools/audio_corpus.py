"""Generate a corpus of IELTS-style Listening parts — script, questions, figure, audio.

Everything a student hears is written fresh by the generator and voiced by the
neural TTS. Nothing is lifted from the Cambridge books: they ground the FIGURE
conventions through the knowledge base and nothing else, which is the same
bargain `project_north_star` states for the whole engine.

The topics come off the open web rather than out of the books. Harvested
2026-08-29:

  * UNC's ENEC undergraduate catalogue (catalog.unc.edu/courses/enec), for 25
    real lecture subjects — estuarine processes, coral reef management,
    restoration ecology, hydrologic science.
  * Yale, Tufts and Oregon environmental-studies listings, for the shape of a
    2026 syllabus.
  * simplyielts.com's May 2026 listening report, which says the live exam has
    swung hard towards environment, community and sustainability — a Part 1 on
    a "Sustainable Farm Stay" is the example it gives.

Those seeds are crossed with the four parts' own registers to make the bank:
Part 1 an everyday transaction, Part 2 a talk about a place or a device, Part 3
a tutorial discussion, Part 4 a lecture. The cross-product is far larger than
any run will use, and `--seed` picks a different slice of it each time.

Needs the qdrant lock, so stop the backend first.

Usage:
  PYTHONIOENCODING=utf-8 python tools/audio_corpus.py --count 24
  PYTHONIOENCODING=utf-8 python tools/audio_corpus.py --count 2000 --concurrency 6
  PYTHONIOENCODING=utf-8 python tools/audio_corpus.py --count 50 --no-audio
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents import listening_trainer as lt
from app.services import tts

OUT = Path("data/audio_corpus")
MANIFEST = OUT / "manifest.jsonl"

# ---------------------------------------------------------------------------
# The topic bank.
#
# Written as parts rather than whole topics so the cross-product is big: an
# exam that asked about the same forty subjects would train a student to
# recognise them, which is the opposite of what a practice corpus is for.
# ---------------------------------------------------------------------------

# Part 4 — a lecture. These are real course subjects, taken off the catalogues
# named above, not invented.
LECTURES = [
    "estuarine processes and the human impact on them",
    "coastal marine science and nutrient cycling",
    "coral reef ecology and how reefs are managed",
    "restoration ecology and how a damaged ecosystem recovers",
    "hydrologic science and the water cycle",
    "freshwater resources and the problems they face",
    "mountain biodiversity and its conservation",
    "atmospheric processes behind urban air quality",
    "food systems, agriculture and sustainability",
    "environmental history and how societies used land",
    "how early civilisations collapsed during abrupt climate change",
    "the spread of farming and what it did to past communities",
    "fungal biology and its sustainable applications",
    "the archaeology of everyday objects",
    "how a city's transport network shapes where people live",
    "the economics of recycling and waste",
    "why some languages disappear and others spread",
    "sleep research and what it tells us about memory",
    "the history of public libraries",
    "how museums decide what to collect",
    "materials science and the search for stronger cement",
    "animal migration and the technology that tracks it",
    "volcanic ash layers as a record of climate",
    "the biology of pollination and what threatens it",
    "how satellites measure deforestation",
    "the acoustics of concert halls",
    "how tidal energy is captured and why it is hard",
    "the history of standardised time",
    "urban heat islands and how cities cool themselves",
    "what tree rings record about drought",
    "the design of bridges and why some fail",
    "how vaccines are distributed in remote regions",
    "the economics of public transport fares",
    "why coastlines erode and what slows it",
    "the domestication of the horse",
    "how paper is made and recycled",
    "birdsong dialects and how they spread",
    "the archaeology of shipwrecks",
    "how noise affects wildlife near roads",
    "the chemistry of food preservation",
    "how flood defences are planned",
    "the spread of invasive plant species",
    "what ice cores tell us about past atmospheres",
    "how children acquire a second language",
    "the logistics of feeding a large city",
]

# Part 2 — a talk about a place, or a walk through a device. The two registers
# `_PART_SPECS` and `_PART2_DIAGRAM` ask for.
PLACES = [
    "community arts centre", "botanic garden", "city farm", "harbour museum",
    "nature reserve", "science discovery centre", "restored watermill",
    "public library and its new wing", "sports and leisure complex",
    "heritage railway", "wildlife hospital", "observatory and planetarium",
    "outdoor activity centre", "craft workshop and studios",
    "aquarium and its conservation work", "open-air folk museum",
    "recycling and reuse centre", "canal-side visitor centre",
    "beekeeping centre", "youth theatre and rehearsal rooms",
    "tidal mill and its museum", "urban orchard and cider press",
    "mountain rescue base", "seed bank and its cold store",
    "lighthouse and keeper's cottage", "textile mill turned gallery",
    "peat bog boardwalk and hide", "shipyard heritage centre",
    "dark sky reserve visitor hut", "bird ringing station",
    "community bakery and mill", "climbing wall and training centre",
    "forest school and its woodland site", "salt marsh field station",
    "printing museum with working presses", "reservoir and its water gardens",
    "puppetry workshop and theatre", "fossil coast discovery point",
]
PLACE_ANGLES = [
    "an orientation talk for new visitors",
    "a guided tour of the building",
    "a talk about the week's events programme",
    "an induction for new volunteers",
    "a radio segment about the site's reopening",
    "a talk on how the site was restored",
]
DEVICES = [
    "an automatic espresso machine", "a hand-operated coffee grinder",
    "a domestic heat pump", "a solar water heater", "a bicycle repair stand",
    "a home 3D printer", "a rainwater harvesting tank",
    "a wood-fired bread oven", "a small wind turbine",
    "a beekeeper's smoker and hive tools", "a kiln for firing pottery",
    "a diving regulator and air supply", "a weather station",
    "a hydroponic growing rack", "a hand loom",
    "a composting digester", "a boat's winch and mooring gear",
    "a telescope mount", "a milling machine in a workshop",
    "a water filtration unit for a field camp",
    "a tide gauge on a harbour wall", "a seed drill on a small farm",
    "a cargo bike and its electric assist", "a village water pump",
    "a sound recording rig for wildlife", "a greenhouse ventilation system",
    "a canal lock and its paddles", "a hand press for printing",
    "a solar cooker", "a drone used for surveying",
    "a bee hive and its supers", "a bread proving cabinet",
    "a portable weather balloon launcher", "a wheelchair lift on a bus",
    "a rainwater filter for a school roof", "a fish ladder on a river",
    "a wind vane and anemometer", "a soil moisture probe",
]

# Part 3 — two or three speakers working through a piece of coursework.
DISCIPLINES = [
    "marine biology", "urban planning", "archaeology", "environmental policy",
    "civil engineering", "public health", "linguistics", "geography",
    "materials science", "agricultural science", "museum studies",
    "hydrology", "conservation biology", "transport studies",
    "food science", "climate science", "architecture", "sports science",
    "acoustics", "forestry", "epidemiology", "industrial design",
    "soil science", "renewable energy engineering", "heritage conservation",
    "ecotoxicology", "cartography", "veterinary science",
]
TUTORIALS = [
    "planning the fieldwork for a term project on {d}",
    "reviewing a draft literature review in {d}",
    "choosing between two research methods for a {d} assignment",
    "working out why a {d} experiment gave odd results",
    "dividing up a group presentation on {d}",
    "preparing a poster for a {d} conference",
]

# Part 1 — an everyday transaction, the register the exam opens with.
SERVICES = [
    "booking a place on a weekend field course",
    "enquiring about renting a workshop space",
    "joining a community garden scheme",
    "registering for a sustainable farm stay",
    "hiring equipment for a school trip",
    "signing up for a evening pottery class",
    "arranging a home energy assessment",
    "booking a table and catering for a club dinner",
    "reporting a lost bag to a bus company",
    "applying for a library membership and study room",
    "arranging a bike delivery and service",
    "booking accommodation for a conference",
    "enrolling a child in a holiday activity club",
    "ordering a repair for a household appliance",
    "asking about a volunteering placement",
    "arranging a guided walk for a walking group",
]


# A second axis on each part, so the bank is thousands of distinct subjects
# rather than a few hundred.
#
# 🔬 Composed only where it actually composes. A blind cross-product produced
# "reporting a lost bag to a bus company and checking what equipment is
# provided" and "a harbour museum on a university campus" — briefs that
# contradict themselves. The model is being asked to write a realistic
# recording from these, and a confused brief is how you get a confused script
# and another refusal. So the errands below fit ANY transaction, the settings
# axis was dropped entirely, and the device axis asks about the same object in
# three different registers instead of moving it somewhere it cannot be.
ERRANDS = [
    "and the booking details",
    "and what it costs",
    "and what to bring",
    "and how to get there",
    "and who to contact about it",
]
DEVICE_ANGLES = [
    "how {d} works, part by part",
    "how {d} is maintained and what goes wrong with it",
    "how {d} is set up safely for the first time",
]
LECTURE_ANGLES = [
    "and how it is measured",
    "and how the field's thinking has changed",
    "built around one case study",
    "and the misconceptions students usually bring to it",
    "and what recent findings have overturned",
]
STAGES = [
    "at their first supervision meeting",
    "after the pilot study came back",
    "a week before the submission deadline",
]


_A_BEFORE_VOWEL = re.compile(r"\ba (?=[aeiou])", re.I)


def articles(topic: str) -> str:
    """Fix "a aquarium" in a composed topic.

    🔬 Applied to the FINISHED string, not injected into the templates: the
    templates already carry their own article in three of six cases, and
    injecting one there produced "a a museum studies experiment". The model is
    being asked to write from these, and a brief that reads as a typo is not
    the brief anyone meant to give it."""
    return _A_BEFORE_VOWEL.sub("an ", topic)


def topic_bank(seed: int) -> list[tuple[int, str]]:
    """(part number, topic) pairs, shuffled, far more than any run will use."""
    bank: list[tuple[int, str]] = []
    bank += [(1, f"{s} {e}") for s in SERVICES for e in ERRANDS]
    bank += [(2, f"{a} at a {p}") for p in PLACES for a in PLACE_ANGLES]
    bank += [(2, a.format(d=d)) for d in DEVICES for a in DEVICE_ANGLES]
    bank += [(3, f"{t.format(d=d)} {s}")
             for d in DISCIPLINES for t in TUTORIALS for s in STAGES]
    bank += [(4, f"a lecture on {t} {a}") for t in LECTURES for a in LECTURE_ANGLES]
    bank = [(n, articles(topic)) for n, topic in bank]
    rng = random.Random(seed)
    rng.shuffle(bank)
    return bank


def slug(text: str, limit: int = 48) -> str:
    keep = "".join(c if c.isalnum() else "-" for c in text.lower())
    return "-".join(w for w in keep.split("-") if w)[:limit]


async def one(index: int, part: int, topic: str, want_audio: bool) -> dict:
    """Generate one part, voice it, and write both. Never raises."""
    # 🔬 Named for the TOPIC, never for the run index. The index restarts at 0
    # every batch, so a topic regenerated after a stopped run wrote a SECOND
    # file rather than overwriting the first: 374 files on disk covering 229
    # topics, 88 of them written up to four times over, and 99 carrying no
    # audio at all because the run was stopped between the json and the mp3.
    # A stable name makes a re-run idempotent.
    name = f"p{part}_{slug(topic, 72)}"
    started = time.time()
    # 🔬 Stamped, because without it the manifest cannot say WHEN anything
    # happened — and when 99 scripts turned up without audio there was no way
    # to tell a run stopped mid-TTS from a TTS call that failed on its own.
    row: dict = {"index": index, "part": part, "topic": topic, "name": name,
                 "started": time.strftime("%Y-%m-%dT%H:%M:%S")}
    try:
        result = await lt.create_part(part, topic=topic)
    except Exception as exc:
        row |= {"ok": False, "stage": "generate", "error": str(exc)[:200],
                "seconds": round(time.time() - started, 1)}
        return row

    script = str(result.get("audio_script") or "")
    row |= {
        "title": result.get("title"),
        "words": len(script.split()),
        "questions": len(result.get("questions") or []),
        "figure": (result.get("visual") or {}).get("kind"),
    }
    (OUT / f"{name}.json").write_text(
        json.dumps(result, ensure_ascii=False), encoding="utf-8"
    )

    if want_audio:
        try:
            audio = await tts.synthesize_script(script, result.get("speakers"))
        except Exception as exc:
            row |= {"ok": False, "stage": "tts", "error": str(exc)[:200],
                    "seconds": round(time.time() - started, 1)}
            return row
        (OUT / f"{name}.mp3").write_bytes(audio)
        row["mb"] = round(len(audio) / 1e6, 2)

    row |= {"ok": True, "seconds": round(time.time() - started, 1)}
    return row


def already_done() -> set[str]:
    """Topics already finished, so a re-run continues instead of repeating.

    Read off the FILES rather than the manifest. A run stopped between writing
    the json and writing the mp3 never appends its manifest row, so a
    manifest-only check regenerated the whole part — which is how 99 orphaned
    scripts accumulated. A part is done when both halves are on disk.
    """
    done = set()
    for js in OUT.glob("*.json"):
        if js.with_suffix(".mp3").exists():
            done.add(js.stem)
    return done


async def voice_orphans(concurrency: int) -> int:
    """Voice every script on disk that has no audio beside it.

    🔬 A part costs a hosted generation and a validator chain to write; the
    audio costs one TTS call. Stopping a run between the two throws the
    expensive half away, and 29 fully-valid scripts of 1300-2250 words were
    sitting there unvoiced. Recovering them is a minute of TTS, so this runs
    before every batch: whatever the last run dropped, the next one picks up.

    Idempotent, and safe to run against a batch already in flight — the TTS
    cache is keyed by the script, so voicing the same part twice writes the
    same bytes.
    """
    orphans = [f for f in sorted(OUT.glob("*.json"))
               if not f.with_suffix(".mp3").exists()]
    if not orphans:
        return 0
    print(f"voicing {len(orphans)} script(s) left without audio", flush=True)
    gate = asyncio.Semaphore(concurrency)
    healed = 0

    async def voice(path: Path) -> None:
        nonlocal healed
        async with gate:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                audio = await tts.synthesize_script(
                    str(data.get("audio_script") or ""), data.get("speakers")
                )
            except Exception as exc:
                print(f"  !! {path.stem[:60]}: {str(exc)[:80]}", flush=True)
                return
            path.with_suffix(".mp3").write_bytes(audio)
            healed += 1
            print(f"  voiced {healed}/{len(orphans)}  {path.stem[:58]} "
                  f"({len(audio) / 1e6:.1f} MB)", flush=True)

    await asyncio.gather(*(voice(f) for f in orphans))
    return healed


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=24)
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--voice-only", action="store_true",
                    help="only voice scripts already on disk, generate nothing")
    ap.add_argument("--parts", default="", help="e.g. 2,4 to restrict to those parts")
    args = ap.parse_args()

    logging.basicConfig(level=logging.ERROR)
    OUT.mkdir(parents=True, exist_ok=True)

    # First, salvage whatever the last run left half-written.
    if not args.no_audio:
        healed = await voice_orphans(args.concurrency)
        if args.voice_only:
            print(f"voiced {healed} script(s)", flush=True)
            return 0

    wanted = {int(p) for p in args.parts.split(",") if p.strip()}
    bank = [pt for pt in topic_bank(args.seed) if not wanted or pt[0] in wanted]
    done = already_done()
    todo = [pt for pt in bank if f"p{pt[0]}_{slug(pt[1], 72)}" not in done]
    if len(todo) < args.count:
        # The bank is a cross-product, not a list: cycle it with the index in
        # the name so a long run keeps going rather than stopping at its size.
        todo = (todo * (args.count // max(1, len(todo)) + 1))[: args.count]
    todo = todo[: args.count]

    print(f"{len(bank)} topics in the bank, {len(done)} already done, "
          f"{len(todo)} to generate at concurrency {args.concurrency}"
          f"{' (no audio)' if args.no_audio else ''}", flush=True)

    gate = asyncio.Semaphore(args.concurrency)
    started = time.time()
    counts = {"ok": 0, "generate": 0, "tts": 0}
    words = mb = 0.0

    async def run(i: int, part: int, topic: str) -> None:
        nonlocal words, mb
        async with gate:
            row = await one(i, part, topic, not args.no_audio)
        with MANIFEST.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        if row.get("ok"):
            counts["ok"] += 1
            words += row.get("words") or 0
            mb += row.get("mb") or 0
        else:
            counts[row.get("stage", "generate")] += 1
        seen = sum(counts.values())
        rate = seen / max(1e-9, (time.time() - started) / 3600)
        left = (len(todo) - seen) / max(1e-9, rate)
        mark = "ok  " if row.get("ok") else "FAIL"
        print(f"  {mark} {seen:5}/{len(todo)}  {row['name'][:52]:54} "
              f"{row.get('seconds', 0):6.1f}s  {rate:5.0f}/h  ETA {left:4.1f}h"
              + ("" if row.get("ok") else f"  {row.get('error', '')[:70]}"),
              flush=True)

    await asyncio.gather(*(run(i, p, t) for i, (p, t) in enumerate(todo)))

    mins = (time.time() - started) / 60
    print(f"\n{counts['ok']} of {len(todo)} generated in {mins:.1f} min "
          f"({counts['ok'] / max(1e-9, mins / 60):.0f}/hour)")
    print(f"  refused at generation: {counts['generate']}   tts failed: {counts['tts']}")
    if counts["ok"]:
        print(f"  {words / counts['ok']:.0f} words and {mb / counts['ok']:.1f} MB "
              f"per part; {mb:.0f} MB written to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
