"""The track record of learned filing rules: what each rule suggested and what was kept.

One row per (filing, rule, field); a filing is a ``(batch_id, drive_id)`` pair. DB only,
nothing touches the archive. Undoing a batch removes its rows.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from sqlalchemy import Engine, delete, insert, select

from dam.db.engine import write_tx
from dam.db.tables import files, rule_outcomes

RECENT_FILINGS = 5  # a rule is flagged by its last few filings
FLAG_AFTER = 2  # changed folder or name in this many of them


@dataclass
class RuleStats:
    suggested: int  # filings where the rule made a suggestion
    changed: int  # of those, filings where the user changed anything
    last_used: float | None
    flagged: bool  # folder or name changed in 2 or more of the last 5 filings


@dataclass
class SampleDocument:
    """A document a rule was last used on, for showing the rule's areas on a real page."""

    drive_id: str
    name: str | None
    ext: str | None


class RuleRecord:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def record(self, batch_id: str, drive_id: str, outcomes: list[tuple[str, str, bool]]) -> None:
        """Save ``(rule_id, field, kept)`` outcomes for one filing."""
        if not outcomes:
            return
        now = time.time()
        rows = [
            {
                "batch_id": batch_id,
                "drive_id": drive_id,
                "rule_id": rule_id,
                "field": field,
                "kept": kept,
                "created": now,
            }
            for rule_id, field, kept in outcomes
        ]
        with write_tx(self.engine) as conn:
            conn.execute(insert(rule_outcomes), rows)

    def remove_created_by(self, batch_id: str) -> int:
        """Delete the outcomes a batch recorded; used when that batch is undone."""
        with write_tx(self.engine) as conn:
            return conn.execute(
                delete(rule_outcomes).where(rule_outcomes.c.batch_id == batch_id)
            ).rowcount

    def last_documents(self) -> dict[str, SampleDocument]:
        """Per rule id, the document the rule last made a suggestion for that is still in the
        archive (not gone, parked or a folder). Rules never recorded are absent."""
        query = (
            select(
                rule_outcomes.c.rule_id,
                rule_outcomes.c.drive_id,
                files.c.name,
                files.c.ext,
            )
            .select_from(rule_outcomes.join(files, files.c.drive_id == rule_outcomes.c.drive_id))
            .where(
                files.c.missing.is_not(True),
                files.c.parked_at.is_(None),
                files.c.is_dir.is_not(True),
            )
            .order_by(rule_outcomes.c.created, rule_outcomes.c.id)
        )
        with self.engine.connect() as conn:
            rows = conn.execute(query).all()
        return {
            rule_id: SampleDocument(drive_id, name, ext) for rule_id, drive_id, name, ext in rows
        }

    def stats(self) -> dict[str, RuleStats]:
        """Per rule id, how often it was suggested and kept; rules never recorded are absent."""
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(
                    rule_outcomes.c.rule_id,
                    rule_outcomes.c.batch_id,
                    rule_outcomes.c.drive_id,
                    rule_outcomes.c.field,
                    rule_outcomes.c.kept,
                    rule_outcomes.c.created,
                ).order_by(rule_outcomes.c.id)
            ).all()
        # rule -> filing -> [created, any not kept, folder or name not kept]
        filings: dict[str, dict[tuple[str, str], list]] = {}
        for rule_id, batch_id, drive_id, field, kept, created in rows:
            f = filings.setdefault(rule_id, {}).setdefault(
                (batch_id, drive_id), [created, False, False]
            )
            f[0] = max(f[0], created)
            if not kept:
                f[1] = True
                if field in ("folder", "name"):
                    f[2] = True
        result = {}
        for rule_id, by_filing in filings.items():
            recent = sorted(by_filing.values(), key=lambda f: f[0])[-RECENT_FILINGS:]
            result[rule_id] = RuleStats(
                suggested=len(by_filing),
                changed=sum(1 for f in by_filing.values() if f[1]),
                last_used=max(f[0] for f in by_filing.values()),
                flagged=sum(1 for f in recent if f[2]) >= FLAG_AFTER,
            )
        return result
