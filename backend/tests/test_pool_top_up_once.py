"""The pool has to be fillable by something that finishes.

`PoolWarmer._run` loops until it is told to stop, which is right for a process
that stays alive and impossible where this app is deployed: a serverless
function is frozen the moment it answers and killed when it goes idle, so a
loop started at app startup never survives to finish a set. `top_up_once` is
the shape a scheduled job needs -- walk the catalog once, fill what is short,
report, exit -- and these are the properties a cron depends on.
"""

import asyncio

import pytest

from app.services import practice_pool as pool


class _Producer:
    """Stands in for the hosted model: counts calls, optionally fails."""

    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self.fail = fail

    async def produce(self, bucket) -> bool:
        self.calls.append((bucket.section, bucket.question_type))
        return not self.fail


@pytest.fixture
def counts(monkeypatch):
    """Pretend the DB reports whatever the test puts in this dict."""
    state: dict[tuple[str, str | None], int] = {}
    monkeypatch.setattr(
        pool, "count_available", lambda db, s, q: state.get((s, q), 0)
    )
    return state


def _warmer(buckets):
    return pool.PoolWarmer(buckets=buckets)


def test_it_returns_rather_than_looping(counts, monkeypatch):
    """The whole point: a scheduled run must terminate on its own."""
    buckets = (pool.Bucket("reading", None, target_size=2),)
    prod = _Producer()
    w = _warmer(buckets)
    monkeypatch.setattr(w, "_produce", prod.produce)

    report = asyncio.run(asyncio.wait_for(w.top_up_once(), timeout=5))

    assert report["produced"] == 2
    assert len(prod.calls) == 2


def test_a_full_bucket_costs_nothing(counts, monkeypatch):
    """A cron that fires every half hour is only cheap if a full pool is a
    no-op -- otherwise frequent polling burns the free model quota."""
    buckets = (pool.Bucket("reading", None, target_size=3),)
    counts[("reading", None)] = 3
    prod = _Producer()
    w = _warmer(buckets)
    monkeypatch.setattr(w, "_produce", prod.produce)

    report = asyncio.run(w.top_up_once())

    assert prod.calls == []
    assert report["produced"] == 0


def test_it_only_fills_the_gap(counts, monkeypatch):
    buckets = (pool.Bucket("listening", None, target_size=6),)
    counts[("listening", None)] = 4
    prod = _Producer()
    w = _warmer(buckets)
    monkeypatch.setattr(w, "_produce", prod.produce)

    assert asyncio.run(w.top_up_once())["produced"] == 2


def test_an_exhausted_budget_stops_it_starting_another_set(counts, monkeypatch):
    """Checked BEFORE a set, never during: abandoning a producer mid-flight
    wastes a hosted call without filling anything."""
    buckets = (pool.Bucket("reading", None, target_size=5),)
    prod = _Producer()
    w = _warmer(buckets)
    monkeypatch.setattr(w, "_produce", prod.produce)

    report = asyncio.run(w.top_up_once(budget_s=0))

    assert prod.calls == []
    assert report["skipped_budget"] == 5


def test_max_sets_caps_one_run(counts, monkeypatch):
    buckets = (
        pool.Bucket("reading", None, target_size=3),
        pool.Bucket("listening", None, target_size=3),
    )
    prod = _Producer()
    w = _warmer(buckets)
    monkeypatch.setattr(w, "_produce", prod.produce)

    report = asyncio.run(w.top_up_once(max_sets=2))

    assert report["produced"] == 2


def test_one_broken_producer_does_not_starve_the_other_buckets(counts, monkeypatch):
    """A failing bucket must cost one attempt, not the whole run -- otherwise
    a single broken section takes the pool down with it."""
    buckets = (
        pool.Bucket("reading", None, target_size=3),
        pool.Bucket("speaking", "Part 1 questions", target_size=1),
    )
    prod = _Producer()

    async def produce(bucket):
        if bucket.section == "reading":
            prod.calls.append((bucket.section, bucket.question_type))
            return False
        return await prod.produce(bucket)

    w = _warmer(buckets)
    monkeypatch.setattr(w, "_produce", produce)

    report = asyncio.run(w.top_up_once())

    # Reading gave up after one failure; speaking still got its set.
    assert report["failed"] == 1
    assert report["produced"] == 1
    assert ("speaking", "Part 1 questions") in prod.calls


def test_the_report_names_every_bucket(counts, monkeypatch):
    """CI reads this log to decide whether the run was worth anything."""
    buckets = (
        pool.Bucket("reading", None, target_size=1),
        pool.Bucket("writing", "Task 1", target_size=1),
    )
    prod = _Producer()
    w = _warmer(buckets)
    monkeypatch.setattr(w, "_produce", prod.produce)

    report = asyncio.run(w.top_up_once())

    labels = [b["bucket"] for b in report["buckets"]]
    assert labels == ["reading/*", "writing/Task 1"]
    assert all("before" in b and "target" in b for b in report["buckets"])
    assert isinstance(report["elapsed_s"], float)
