"""Results by (file sha256 / input digest, task, model, prompt version): a hit costs
nothing and is shown as "from earlier" (spec §2.9)."""

import time

from sqlalchemy import Engine, select
from sqlalchemy.dialects.sqlite import insert

from dam.db.engine import write_tx
from dam.db.tables import ai_cache


def get(engine: Engine, sha_key: str, task: str, model: str, prompt_version: str) -> dict | None:
    if not sha_key:
        return None
    with engine.connect() as conn:
        row = conn.execute(
            select(ai_cache.c.data).where(
                ai_cache.c.sha_key == sha_key,
                ai_cache.c.task == task,
                ai_cache.c.model == model,
                ai_cache.c.prompt_version == prompt_version,
            )
        ).scalar_one_or_none()
    return dict(row) if isinstance(row, dict) else None


def put(
    engine: Engine, sha_key: str, task: str, model: str, prompt_version: str, data: dict
) -> None:
    if not sha_key:
        return
    stmt = insert(ai_cache).values(
        sha_key=sha_key,
        task=task,
        model=model,
        prompt_version=prompt_version,
        data=data,
        at=time.time(),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["sha_key", "task", "model", "prompt_version"],
        set_={"data": stmt.excluded.data, "at": stmt.excluded.at},
    )
    with write_tx(engine) as conn:
        conn.execute(stmt)
