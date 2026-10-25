"""A file's summaries (``file_summaries``, spec §3 and §7.5): one per (drive id, source),
``ai`` (saved when the user clicks "Use this summary") or ``user`` (typed). Each keeps
the sha256 of the content it describes: when the file changes it is "outdated".

A current user summary is never overwritten without ``replace`` (the UI confirms
first); an outdated one does not block. Saving an AI summary with ``replace`` takes the
user summary's place (that row goes), so what the user confirmed is what they see.
"""

import time
from typing import Any

from sqlalchemy import Engine, delete, select
from sqlalchemy.dialects.sqlite import insert

from dam.db.engine import write_tx
from dam.db.tables import file_summaries
from dam.index.repo import FileRepo
from dam.services.errors import Conflict, InvalidRequest

SOURCES = ("ai", "user")
SUMMARY_CHARS = 2000
FACTS = 5
FACT_CHARS = 300

KEEPS_USER = "this file has a summary you wrote; confirm to replace it"  # 409 without replace


def check(summary: Any, key_facts: Any) -> tuple[str, list[str]]:
    if not isinstance(summary, str) or not summary.strip():
        raise InvalidRequest("the summary is empty")
    summary = summary.strip()
    if len(summary) > SUMMARY_CHARS:
        raise InvalidRequest(f"the summary is longer than {SUMMARY_CHARS} characters")
    if not isinstance(key_facts, list) or len(key_facts) > FACTS:
        raise InvalidRequest(f"at most {FACTS} key facts")
    facts = []
    for fact in key_facts:
        if not isinstance(fact, str) or not fact.strip() or len(fact.strip()) > FACT_CHARS:
            raise InvalidRequest(f"a key fact must be 1 to {FACT_CHARS} characters")
        facts.append(fact.strip())
    return summary, facts


class SummaryService:
    def __init__(self, engine: Engine, repo: FileRepo) -> None:
        self.engine = engine
        self.repo = repo

    def sources_for(self, drive_ids: list[str]) -> dict[str, set[str]]:
        """``{drive_id: {"ai", "user"}}`` for the files that have a summary (one query)."""
        if not drive_ids:
            return {}
        out: dict[str, set[str]] = {}
        with self.engine.connect() as conn:
            for drive_id, source in conn.execute(
                select(file_summaries.c.drive_id, file_summaries.c.source).where(
                    file_summaries.c.drive_id.in_(drive_ids)
                )
            ):
                out.setdefault(drive_id, set()).add(source)
        return out

    def get(self, drive_id: str) -> dict[str, dict | None]:
        """``{ai, user}``: each ``{summary, key_facts, outdated}`` or None."""
        rec = self.repo.get(drive_id)
        current = rec.sha256 if rec is not None else None
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(file_summaries).where(file_summaries.c.drive_id == drive_id)
            ).mappings()
            out: dict[str, dict | None] = {s: None for s in SOURCES}
            for row in rows:
                if row["source"] in out:
                    out[row["source"]] = {
                        "summary": row["summary"],
                        "key_facts": list(row["key_facts"] or []),
                        "outdated": row["sha256"] != current,
                    }
        return out

    def put(
        self,
        drive_id: str,
        source: str,
        summary: str,
        key_facts: list[str] | None = None,
        replace: bool = False,
    ) -> dict[str, dict | None]:
        """Store the file's ``source`` summary for its current content. Refused
        (``Conflict``) when a current user summary would be overwritten or replaced
        without ``replace``."""
        if source not in SOURCES:
            raise InvalidRequest(f"unknown summary source {source!r}")
        summary, facts = check(summary, [] if key_facts is None else key_facts)
        rec = self.repo.get(drive_id)
        sha = rec.sha256 if rec is not None else None
        user_row = (file_summaries.c.drive_id == drive_id, file_summaries.c.source == "user")
        with write_tx(self.engine) as conn:
            user_sha = conn.execute(select(file_summaries.c.sha256).where(*user_row)).first()
            if user_sha is not None and user_sha[0] == sha and not replace:
                raise Conflict(KEEPS_USER)
            if source == "ai" and replace:
                conn.execute(delete(file_summaries).where(*user_row))
            stmt = insert(file_summaries).values(
                drive_id=drive_id,
                source=source,
                sha256=sha,
                summary=summary,
                key_facts=facts,
                at=time.time(),
            )
            conn.execute(
                stmt.on_conflict_do_update(
                    index_elements=["drive_id", "source"],
                    set_={
                        "sha256": stmt.excluded.sha256,
                        "summary": stmt.excluded.summary,
                        "key_facts": stmt.excluded.key_facts,
                        "at": stmt.excluded.at,
                    },
                )
            )
        return self.get(drive_id)
