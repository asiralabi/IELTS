"""Warm pool of pre-generated practice sets.

Students pop rows from this pool for near-instant practice; a background
warmer keeps each (section, question_type) bucket topped up. When a bucket
is empty the caller can fall back to synchronous generation.

Buckets ignore `topic` and custom `question_types` — those go straight to
synchronous generation. The default no-filter flow (which is what 95%+ of
students click) always hits the pool.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import PreGeneratedPractice

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Bucket catalog — what to keep warm

@dataclass(frozen=True)
class Bucket:
    section: str
    question_type: str | None
    target_size: int

    def key(self) -> tuple[str, str | None]:
        return (self.section, self.question_type)


# One bucket per common student flow. Keep small — every extra bucket costs
# CPU-minutes on qwen3:4b.
BUCKETS: tuple[Bucket, ...] = (
    # Reading/listening are the highest-traffic buckets — students pop these
    # far more often than writing/speaking, and cold generation takes ~2 min
    # on qwen3:4b. Keep 6 warm to survive concurrent-user bursts.
    Bucket("reading", None, target_size=6),
    Bucket("listening", None, target_size=6),
    Bucket("writing", "Task 1", target_size=2),
    Bucket("writing", "Task 2 essay", target_size=2),
    Bucket("speaking", "Part 1 questions", target_size=2),
    Bucket("speaking", "Part 2 cue card", target_size=2),
    Bucket("speaking", "Part 3 discussion questions", target_size=2),
)


# Map friendly frontend keys to the canonical pool bucket labels above.
# The canonical labels are also what mock-exam and the LLM prompt see, so
# they read naturally in generated content.
_BUCKET_ALIASES: dict[tuple[str, str], str] = {
    ("writing", "task1"): "Task 1",
    ("writing", "task2"): "Task 2 essay",
    ("writing", "Task 1"): "Task 1",
    ("writing", "Task 2 essay"): "Task 2 essay",
    ("speaking", "part1"): "Part 1 questions",
    ("speaking", "part2"): "Part 2 cue card",
    ("speaking", "part3"): "Part 3 discussion questions",
    ("speaking", "Part 1 questions"): "Part 1 questions",
    ("speaking", "Part 2 cue card"): "Part 2 cue card",
    ("speaking", "Part 3 discussion questions"): "Part 3 discussion questions",
}


def canonical_bucket(section: str, question_type: str | None) -> str | None:
    """Translate an inbound question_type into the pool's canonical label.

    Returns None when the section has bucket_key=None (reading/listening) or
    when the (section, question_type) pair isn't one of the warmed buckets.
    """
    if question_type is None:
        return None
    return _BUCKET_ALIASES.get((section, question_type))


# ---------------------------------------------------------------------------
# Pool queries

def _available_query(session: str, question_type: str | None):
    conds = [
        PreGeneratedPractice.section == session,
        PreGeneratedPractice.consumed_at.is_(None),
    ]
    if question_type is None:
        conds.append(PreGeneratedPractice.question_type.is_(None))
    else:
        conds.append(PreGeneratedPractice.question_type == question_type)
    return and_(*conds)


def count_available(db: Session, section: str, question_type: str | None) -> int:
    stmt = select(func.count()).select_from(PreGeneratedPractice).where(
        _available_query(section, question_type)
    )
    return int(db.execute(stmt).scalar_one())


def pop(
    db: Session, section: str, question_type: str | None = None
) -> dict[str, Any] | None:
    """Atomically claim the oldest unclaimed row for this bucket.

    Returns the payload dict, or None when the bucket is empty. Uses a
    transactional SELECT + UPDATE — safe under SQLite's default serialised
    write locking. If another worker beat us to the row, we simply retry.
    """
    for _ in range(3):
        row = db.execute(
            select(PreGeneratedPractice)
            .where(_available_query(section, question_type))
            .order_by(PreGeneratedPractice.created_at.asc())
            .limit(1)
        ).scalar_one_or_none()
        if row is None:
            return None
        # Claim under SQLite's serialised write lock; the extra AND on
        # consumed_at guards the rare case where another worker beat us.
        stamp = datetime.now(timezone.utc)
        updated = db.execute(
            PreGeneratedPractice.__table__.update()
            .where(PreGeneratedPractice.id == row.id)
            .where(PreGeneratedPractice.consumed_at.is_(None))
            .values(consumed_at=stamp)
        ).rowcount
        if not updated:
            db.rollback()
            continue
        db.commit()
        return row.payload
    return None


def insert(
    db: Session, section: str, question_type: str | None, payload: dict[str, Any]
) -> None:
    db.add(
        PreGeneratedPractice(
            section=section,
            question_type=question_type,
            payload=payload,
        )
    )
    db.commit()


# ---------------------------------------------------------------------------
# Producer registry — how to generate for each bucket


ProducerFn = Callable[[Bucket], Awaitable[dict[str, Any]]]


async def _reading(_bucket: Bucket) -> dict[str, Any]:
    from app.agents import reading_trainer

    return await reading_trainer.create_practice()


async def _listening(_bucket: Bucket) -> dict[str, Any]:
    from app.agents import listening_trainer

    return await listening_trainer.create_practice()


async def _writing(bucket: Bucket) -> dict[str, Any]:
    from app.agents import question_generator

    return await question_generator.generate("writing", bucket.question_type)


async def _speaking(bucket: Bucket) -> dict[str, Any]:
    from app.agents import question_generator

    return await question_generator.generate("speaking", bucket.question_type)


_PRODUCERS: dict[str, ProducerFn] = {
    "reading": _reading,
    "listening": _listening,
    "writing": _writing,
    "speaking": _speaking,
}


# ---------------------------------------------------------------------------
# Background warmer

class PoolWarmer:
    """Async loop that keeps each Bucket topped up to target_size.

    One producer runs at a time (semaphore = 1) so local qwen3:4b isn't
    swamped. Between iterations we sleep briefly when everything is full so
    the loop doesn't busy-spin.
    """

    def __init__(self, buckets: tuple[Bucket, ...] = BUCKETS, idle_sleep_s: float = 30.0) -> None:
        self._buckets = buckets
        self._idle_sleep_s = idle_sleep_s
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        # Per-bucket locks — a fast outer loop under load would otherwise
        # kick off a second production for the same bucket while the first
        # is still in flight. Locks are cheap; double-production is not.
        self._bucket_locks: dict[tuple[str, str | None], asyncio.Lock] = {
            b.key(): asyncio.Lock() for b in buckets
        }

    def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="practice-pool-warmer")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    async def _run(self) -> None:
        logger.info("practice pool warmer started")
        while not self._stop.is_set():
            produced_any = False
            # Keep producing until every bucket is at target — previously we
            # broke after ONE successful generation per iteration, which under
            # concurrent pop meant most buckets never refilled in time.
            for bucket in self._buckets:
                if self._stop.is_set():
                    break
                if not self._needs_topup(bucket):
                    continue
                ok = await self._produce(bucket)
                if ok:
                    produced_any = True
                # On failure, fall through to the next bucket so one broken
                # producer never starves the others.
            if not produced_any:
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self._idle_sleep_s)
                except asyncio.TimeoutError:
                    pass
        logger.info("practice pool warmer stopped")

    def _needs_topup(self, bucket: Bucket) -> bool:
        with SessionLocal() as db:
            n = count_available(db, bucket.section, bucket.question_type)
        return n < bucket.target_size

    async def _produce(self, bucket: Bucket) -> bool:
        producer = _PRODUCERS.get(bucket.section)
        if producer is None:
            logger.warning("no producer for section=%s", bucket.section)
            return False
        lock = self._bucket_locks.setdefault(bucket.key(), asyncio.Lock())
        # If a production for this bucket is already in flight, skip — the
        # in-flight one will refill it. Prevents double-production when the
        # loop is fast relative to producer latency.
        if lock.locked():
            return False
        async with lock:
            # Re-check inside the lock: another pass may have topped it up.
            if not self._needs_topup(bucket):
                return False
            logger.info(
                "pool warmer producing %s/%s",
                bucket.section,
                bucket.question_type or "*",
            )
            try:
                payload = await producer(bucket)
            except Exception as exc:  # noqa: BLE001 — log and try next bucket
                logger.warning(
                    "pool producer failed for %s/%s: %s",
                    bucket.section,
                    bucket.question_type or "*",
                    exc,
                )
                return False
            try:
                with SessionLocal() as db:
                    insert(db, bucket.section, bucket.question_type, payload)
            except Exception as exc:  # noqa: BLE001
                logger.warning("pool insert failed: %s", exc)
                return False
            return True


_warmer: PoolWarmer | None = None


def get_warmer() -> PoolWarmer:
    global _warmer
    if _warmer is None:
        _warmer = PoolWarmer()
    return _warmer
