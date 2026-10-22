"""The AI call log (``ai_calls``, migration 0013): every call that was sent, with its
real token usage and cost. Blocked calls are not rows: nothing left the machine."""

import time
from datetime import datetime

from sqlalchemy import Engine, func, insert, select

from dam.db.engine import write_tx
from dam.db.tables import ai_calls

# "fake": the DAM_AI_FAKE=1 demo provider answered (nothing was sent, costs nothing)
OUTCOMES = ("ok", "cached", "error", "fake")


def record(
    engine: Engine,
    *,
    task: str,
    model: str,
    files: list[str],
    input_tokens: int,
    output_tokens: int,
    cost_eur: float,
    outcome: str,
    error: str | None,
    duration_ms: int,
    at: float | None = None,
) -> int:
    if outcome not in OUTCOMES:
        raise ValueError(f"unknown outcome {outcome!r}")
    with write_tx(engine) as conn:
        return conn.execute(
            insert(ai_calls).values(
                at=time.time() if at is None else at,
                task=task,
                model=model,
                files=list(files),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_eur=cost_eur,
                outcome=outcome,
                error=error,
                duration_ms=duration_ms,
            )
        ).inserted_primary_key[0]


def month_start(now: datetime | None = None) -> float:
    """The first instant of the local calendar month, as epoch seconds. A naive local
    datetime: midnight on the 1st gets that day's UTC offset, whatever DST did since."""
    now = now or datetime.now()
    return datetime(now.year, now.month, 1).timestamp()


def month_spend_eur(engine: Engine, now: datetime | None = None) -> float:
    with engine.connect() as conn:
        total = conn.execute(
            select(func.coalesce(func.sum(ai_calls.c.cost_eur), 0.0)).where(
                ai_calls.c.at >= month_start(now)
            )
        ).scalar_one()
    return float(total)


def recent(engine: Engine, limit: int = 50) -> list[dict]:
    """The newest ``limit`` rows, newest first."""
    with engine.connect() as conn:
        rows = conn.execute(select(ai_calls).order_by(ai_calls.c.id.desc()).limit(limit)).mappings()
        return [dict(r) for r in rows]
