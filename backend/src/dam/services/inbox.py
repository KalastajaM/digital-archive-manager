"""Inbox: list incoming files with suggestions, and file them (rename + move + tag), then
put them in a tray, in collections and give them a note."""

import logging
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text as sql_text

from dam.bills.barcode import BarcodeError
from dam.bills.barcode import parse as parse_barcode
from dam.codes.apply import apply_codes, apply_ticks, codes_for, known_reads
from dam.codes.model import FilingCode
from dam.collections.service import CollectionService, check_collection_name
from dam.config import DEFAULT_ADDRESS_ZONE, Person, SpecialFolders
from dam.core.naming import parse_doc_date
from dam.core.paths import ArchivePaths
from dam.extract.layout import check_box, lines_in_zone
from dam.index.repo import FileRecord, FileRepo, TagRepo
from dam.notes import NotesService, check_note
from dam.ops.executor import Executor
from dam.ops.guards import canonical, fold_parts, is_ds_store_name, parent
from dam.ops.model import BatchResult, Op, OpKind, Plan, ResolvedOp
from dam.rules.draft import ZoneDraft, draft_rule
from dam.rules.engine import (
    Suggestion,
    _parent,
    person_for,
    stem_and_ext,
    suggest,
    template_uses_person,
)
from dam.rules.fields import DetectedFields
from dam.rules.guess import guess_tray
from dam.rules.model import RESERVED_IDS, Rule
from dam.rules.offer import (
    RuleOffer,
    make_doc_frequency,
    offer_target,
    outcomes,
    rule_id_of,
    same,
)
from dam.rules.people import PeopleContext
from dam.rules.similar import SOURCE as SIMILAR_SOURCE
from dam.rules.similar import similar_folder
from dam.rules.state import load_state
from dam.services import check_destination_area, check_disk_identity, check_origin
from dam.services.assignments import Assignment, AssignmentService
from dam.services.errors import InvalidRequest, NotFound
from dam.services.rule_record import RuleRecord
from dam.services.scan_fields import ScanFieldService, detected_of, prefill_from
from dam.trays.service import TrayService

log = logging.getLogger(__name__)

EXCERPT_CHARS = 500


def normalise_tags(tags: list[str]) -> list[str]:
    """Strip whitespace, drop empty tags, drop duplicates (first wins); case is kept."""
    return list(dict.fromkeys(t.strip() for t in tags if t.strip()))


def prefill_of(
    found: DetectedFields, payee: str | None = None, barcode: str | None = None
) -> dict[str, str]:
    """Scan values for tray fields (``FieldDef.prefill`` keys); only the ones found.
    ``payee`` is a rule's ``then.payee`` (the suggestion's), not read from the text.

    ``barcode`` is the bank barcode read from the scan. When ``parse`` accepts it, its
    IBAN, amount, reference and due date beat the text's; an amount of 0 (the payer
    chooses) or no due date in the barcode leaves the text's value."""
    out: dict[str, str] = {}
    if payee:
        out["payee"] = payee
    if found.due_date is not None:
        out["due_date"] = found.due_date.isoformat()
    if found.total is not None:
        out["total"] = str(found.total.quantize(Decimal("0.01")))
    if found.iban:
        out["iban"] = found.iban
    if found.reference:
        out["reference"] = found.reference
    if barcode:
        try:
            data = parse_barcode(barcode)
        except BarcodeError:
            return out
        out["iban"] = data.iban
        out["reference"] = data.reference
        if data.amount:
            out["total"] = str(data.amount)
        if data.due is not None:
            out["due_date"] = data.due.isoformat()
    return out


@dataclass
class FileItResult:
    """Outcome of ``file_it``: the batch, plus tagging and follow-up problems kept apart.

    ``tag_error`` is the first error from writing tags (None if all went well);
    ``untagged`` lists the drive ids whose tags could not be written. ``items`` are the
    ids of the tray items created; ``follow_up_error`` is the first error from creating
    items, collection memberships or notes. The files themselves were filed as the
    batch says, and undo still works.
    """

    batch: BatchResult
    tag_error: str | None = None
    untagged: list[str] = field(default_factory=list)
    items: list[int] = field(default_factory=list)
    follow_up_error: str | None = None
    offer: RuleOffer | None = None  # "make a rule from this?", see ``file_it``


@dataclass
class InboxEntry:
    record: FileRecord
    suggestion: Suggestion
    text_excerpt: str  # first EXCERPT_CHARS characters of the extracted text
    # tray field prefills found in the scan (``prefill_of``), or from the edited fields
    prefill: dict[str, str] = field(default_factory=dict)
    # the tray the document probably belongs in (``guess_tray``), None: no guess
    tray_guess: str | None = None
    # ids of the trays the file already has an open item in
    open_trays: list[str] = field(default_factory=list)
    # the scan fields: the user's saved list, else the detected one (``scan_fields``)
    fields: list[dict[str, str | None]] = field(default_factory=list)
    fields_edited: bool = False
    # who the owner says the document is from and for (None: nothing set)
    assignment: Assignment | None = None


@dataclass
class FileRequest:
    """File ``drive_id`` as ``folder/name`` and add ``tags``; then optionally create an
    item in ``tray`` (``tray_fields`` over the scan's prefill), add the file to the
    ``collections`` named (created if new), star it or mark it important (a QR
    sticker's tick boxes) and set its ``note``. Star and Important are collection
    memberships made by the batch, so undoing it removes them (a file starred before
    keeps its star)."""

    drive_id: str
    name: str
    folder: str
    tags: list[str] = field(default_factory=list)
    tray: str | None = None
    tray_fields: dict = field(default_factory=dict)
    collections: list[str] = field(default_factory=list)
    note: str = ""
    star: bool = False
    important: bool = False


@dataclass
class _FollowUp:
    """A request's validated follow-ups (what ``file_it`` does after the move)."""

    tray: str | None
    fields: dict
    collections: list[str]
    note: str
    star: bool = False
    important: bool = False


class InboxService:
    def __init__(
        self,
        paths: ArchivePaths,
        repo: FileRepo,
        tags: TagRepo,
        executor: Executor,
        rules: Callable[[], list[Rule]],
        special: SpecialFolders,
        trays: TrayService,
        collections: CollectionService,
        notes: NotesService,
        scan_fields: ScanFieldService,
        codes: Callable[[], list[FilingCode]] = list,
        *,
        rule_record: RuleRecord | None = None,
        rules_dir: Callable[[], Path] | None = None,
        data_dir: Path | None = None,
        want_layouts: Callable[[Collection[str]], None] | None = None,
        people: Callable[[], Sequence[Person]] = list,
        address_zone: Callable[[], Sequence[float]] = lambda: DEFAULT_ADDRESS_ZONE,
        assigned_person: Callable[[str], str | None] = lambda drive_id: None,
        assignments: AssignmentService | None = None,
    ) -> None:
        self.paths = paths
        self.repo = repo
        self.tags = tags
        self.executor = executor
        self._rules = rules
        self.special = special
        self.trays = trays
        self.collections = collections
        self.notes = notes
        self.scan_fields = scan_fields
        self._codes = codes
        self._rule_record = rule_record
        self._rules_dir = rules_dir
        self._data_dir = data_dir
        # asks the layout pass to read page 1 of these files next (a rule needs it)
        self._want_layouts = want_layouts
        # who documents are for: the people list, the address zone of page 1, and the
        # person the owner assigned to a document
        self._people = people
        self._address_zone = address_zone
        self._assigned_person = assigned_person
        self._assignments = assignments

    def people_context(self, drive_id: str) -> PeopleContext:
        return PeopleContext(
            self._people(), tuple(self._address_zone()), self._assigned_person(drive_id)
        )

    def list(self) -> list[InboxEntry]:
        """Files directly in the inbox or in a filing code's inbox folder (no folders,
        links or parked rows), newest first."""
        records = self.repo.inbox_files()
        records.sort(key=lambda r: r.mtime if r.mtime is not None else float("-inf"), reverse=True)
        tray_ids = [t.id for t in self.trays.defs()]
        open_trays = self.trays.open_trays([r.drive_id for r in records])
        entries = []
        assigned = self._assignments.get([r.drive_id for r in records]) if self._assignments else {}
        for rec in records:
            text = self.repo.text_for(rec.drive_id)
            found = self._suggest(rec, text)
            barcode = self.repo.barcode_for(rec.drive_id)
            prefill = prefill_of(found.fields, found.payee, barcode)
            detected, saved = detected_of(found, prefill), self.scan_fields.saved(rec.drive_id)
            entries.append(
                InboxEntry(
                    rec,
                    found,
                    text[:EXCERPT_CHARS],
                    prefill if saved is None else prefill_from(saved),
                    self._tray_guess(found, tray_ids, barcode),
                    open_trays.get(rec.drive_id, []),
                    detected if saved is None else saved,
                    saved is not None,
                    assigned.get(rec.drive_id),
                )
            )
        return entries

    def prefill_for(self, drive_id: str) -> dict[str, str]:
        """The file's scan prefill: from its saved fields if the user edited them, else
        (``prefill_of`` of its suggestion) from its text, the rules and its bank barcode;
        for an unknown file, none."""
        rec = self.repo.get(drive_id)
        if rec is None:
            return {}
        saved = self.scan_fields.saved(drive_id)
        if saved is not None:
            return prefill_from(saved)
        found = self._suggest(rec, self.repo.text_for(drive_id))
        return prefill_of(found.fields, found.payee, self.repo.barcode_for(drive_id))

    def detected_fields(self, drive_id: str) -> list[dict[str, str | None]]:
        """The file's detected scan fields (``detected_of``), ignoring any saved list."""
        rec = self.repo.get(drive_id)
        if rec is None:
            return []
        found = self._suggest(rec, self.repo.text_for(drive_id))
        return detected_of(
            found, prefill_of(found.fields, found.payee, self.repo.barcode_for(drive_id))
        )

    def suggestion(self, drive_id: str) -> Suggestion:
        rec = self._record(drive_id)
        return self._suggest(rec, self.repo.text_for(drive_id))

    def build_plan(self, reqs: list[FileRequest], origin: str = "ui") -> Plan:
        """One op per file: RENAME within its folder, MOVE (with ``name``) elsewhere.

        A request that changes nothing gets no op. Path policy (collisions, protected
        paths, top-level folders, valid names) is left to the executor's guards.
        """
        return self._plan(self._ops(reqs), origin)

    def preview(self, reqs: list[FileRequest], origin: str = "ui") -> list[ResolvedOp]:
        """The plan ``file_it`` would apply. The follow-ups are validated the same way
        first, so a request that ``file_it`` would refuse (``InvalidRequest``: tray,
        tray field, collection name or note) is refused here too."""
        pairs = self._ops(reqs)
        for req, _ in pairs:
            self._follow_up(req)
        resolved = self.executor.preview(self._plan(pairs, origin))
        self._check_identity(pairs, resolved)
        return resolved

    def file_it(
        self,
        reqs: list[FileRequest],
        dry_run: bool = False,
        origin: str = "ui",
        via: str = "form",
    ) -> FileItResult:
        """Apply the plan, then tag the files it filed and run their follow-ups.

        Everything is validated before anything moves: an invalid tray, tray field,
        collection name or note is ``InvalidRequest`` and nothing is applied; so is a
        stale index (a file replaced on disk since the scan, ``check_disk_identity``).

        Tags and follow-ups go only to files whose op is in ``result.done`` (and to files
        that needed no op). A failed or interrupted batch is returned as is, never
        raised. Per file, in order: tags, the tray item, collection memberships (then
        Starred and Important), the note; each its own DB transaction, all with
        ``created_by_batch`` = the batch so undoing it removes them. A failure is
        logged and noted (``tag_error``/``untagged``, ``follow_up_error``) and the rest
        still run. The batch id is never lost. If the batch applied nothing (no op
        needed, or the only ops failed) there is nothing to undo: the follow-ups are
        created with no batch and stay until removed by hand.

        Tray fields: the scan's prefill only fills fields left out of ``tray_fields``. A
        caller that showed prefill values to the user (the review card) must send every
        value it displayed explicitly, so what was shown is what is stored; an explicit
        blank means the user cleared it.

        The note goes on the tray item when a tray is chosen (skipped, and reported,
        if the item could not be created), else on the file. A filing note never
        overwrites: if the target already has one, it is not added and that is
        reported in ``follow_up_error``.

        ``via`` is how the filing was made (``"form"``, ``"batch"`` or ``"codes"``, not
        to be confused with the journal ``origin``). Form and batch filings record
        whether each rule-suggested value was kept; only a form filing of one file can
        come back with an ``offer`` to make or update a rule (``dam.rules.offer``).
        """
        pairs = self._ops(reqs)
        follow_ups = [self._follow_up(req) for req, _ in pairs]
        suggested = {} if dry_run else self._suggestions_before(reqs, via)
        plan = self._plan(pairs, origin)
        result = self.executor.apply(
            plan, dry_run=dry_run, check=lambda ops: self._check_identity(pairs, ops)
        )
        outcome = FileItResult(result)
        if dry_run:
            return outcome
        batch_id = result.batch_id if result.done else None
        done = {fold_parts(r.src) for r in result.done if r.kind in (OpKind.RENAME, OpKind.MOVE)}
        for (req, op), follow in zip(pairs, follow_ups, strict=True):
            if not (op is None or fold_parts(op.src) in done):
                continue
            tags = normalise_tags(req.tags)
            if tags:
                try:
                    self.tags.add(req.drive_id, tags)
                except Exception as e:
                    log.warning(
                        "tagging %s failed (batch %s)", req.drive_id, result.batch_id, exc_info=True
                    )
                    outcome.untagged.append(req.drive_id)
                    outcome.tag_error = outcome.tag_error or f"{type(e).__name__}: {e}"
            self._run_follow_up(req.drive_id, follow, batch_id, outcome)
            if req.drive_id in suggested:
                self._learn(req, suggested[req.drive_id], batch_id, via, len(reqs), outcome)
                self._record_person(req, suggested[req.drive_id][0])
        return outcome

    def _suggestions_before(self, reqs: list[FileRequest], via: str) -> dict:
        """``drive_id -> (suggestion, record, text)``, taken before the file moves."""
        found: dict = {}
        if via not in ("form", "batch") or self._rule_record is None:
            return found
        for req in reqs:
            try:
                rec = self._record(req.drive_id)
                text = self.repo.text_for(req.drive_id)
                found[req.drive_id] = (self._suggest(rec, text), rec, text)
            except Exception:
                log.warning("no suggestion to record for %s", req.drive_id, exc_info=True)
        return found

    def _learn(
        self,
        req: FileRequest,
        before: tuple,
        batch_id: str | None,
        via: str,
        count: int,
        outcome: FileItResult,
    ) -> None:
        """Record which rule values were kept; maybe set ``outcome.offer``. Never fails
        the filing."""
        found, rec, text = before
        try:
            if batch_id is not None and self._rule_record is not None:
                done = outcomes(found, req.name, req.folder, req.tray)
                if done:
                    self._rule_record.record(batch_id, req.drive_id, done)
        except Exception:
            log.warning("recording the filing of %s failed", req.drive_id, exc_info=True)
        try:
            if via == "form" and count == 1 and batch_id is not None:
                outcome.offer = self._offer(req, found, rec, text)
        except Exception:
            log.warning("offering a rule for %s failed", req.drive_id, exc_info=True)

    def _record_person(self, req: FileRequest, found: Suggestion) -> None:
        """The folder came from a rule whose template has ``{person}`` and the owner kept
        it: that person is who the document is for (unless the owner said otherwise).
        Never fails the filing."""
        try:
            rule_id = rule_id_of(found.folder_source)
            if self._assignments is None or rule_id is None or found.person is None:
                return
            rule = next((r for r in self._rules() if r.id == rule_id), None)
            if rule is None or not template_uses_person(rule.then.folder):
                return
            if same(found.folder, req.folder):
                self._assignments.record_filing(req.drive_id, found.person)
        except Exception:
            log.warning("recording the person of %s failed", req.drive_id, exc_info=True)

    def _offer(
        self, req: FileRequest, found: Suggestion, rec: FileRecord, text: str
    ) -> RuleOffer | None:
        if self._data_dir is None or self._rules_dir is None:
            return None
        state = load_state(self._data_dir)
        if not state.offer:
            return None
        wanted, kind, rule_id = offer_target(found, req.name, req.folder, self._rules_dir())
        if not wanted:
            return None
        frequency = make_doc_frequency(*self._frequency_counter())
        draft = draft_rule(
            text=text,
            original_name=rec.name or "",
            filed_name=req.name,
            filed_folder=req.folder,
            doc_date=found.doc_date,
            tags=list(req.tags),
            tray=req.tray,
            payee=req.tray_fields.get("payee") if isinstance(req.tray_fields, dict) else None,
            doc_frequency=frequency,
            taken_ids={r.id for r in self._rules()} | RESERVED_IDS,
            person=found.person,
        )
        if draft is None:
            return None
        ticked = {w.word for w in draft.words if w.ticked}
        if any(ticked == set(d) for d in state.declined):
            return None
        return RuleOffer(kind, rule_id, req.drive_id, draft)

    def draft_zone(self, drive_id: str, box: list[float], sender: str | None = None) -> ZoneDraft:
        """The rule a box drawn on page 1 starts from: ``when.zone`` is the box with the
        most distinctive word of the lines in it ticked (the draft's usual choice), and
        ``when.folder_is`` is the inbox. A document that is filed already gives the folder
        and name it has now as patterns; one in the inbox gives none. ``InvalidRequest``
        when the box is bad, page 1 is not read yet, or no usable word is in the box."""
        rec = self._record(drive_id)
        try:
            area = check_box(box)
        except ValueError as e:
            raise InvalidRequest(str(e)) from e
        layout = self.repo.layout_for(drive_id)
        if layout is None:
            if self._want_layouts is not None:
                self._want_layouts([drive_id])
            raise InvalidRequest("Page 1 of this document has not been read yet.")
        lines = [ln.text for ln in lines_in_zone(layout.lines, area)]
        if not lines:
            raise InvalidRequest("There is no text in that area of page 1.")
        filed = not self._in_inbox(rec)
        folder = _parent(rec.path) if filed else ""
        name = rec.name or ""
        doc_date = parse_doc_date(name) or rec.doc_date
        draft = draft_rule(
            text="\n".join(lines),
            original_name="",
            filed_name=name if filed and name else None,
            filed_folder=folder or None,
            doc_date=doc_date,
            tags=self.tags.for_file(drive_id) if filed else [],
            tray=None,
            payee=None,
            doc_frequency=make_doc_frequency(*self._frequency_counter()),
            taken_ids={r.id for r in self._rules()} | RESERVED_IDS,
            person=person_for(self.people_context(drive_id), layout).name,
        )
        if draft is None:
            raise InvalidRequest("There is no usable word in that area of page 1.")
        return ZoneDraft(
            **{f: getattr(draft, f) for f in draft.__dataclass_fields__},
            box=area,
            folder_is=self.special.inbox,
            lines=lines,
            sender=sender,
        )

    def _frequency_counter(self) -> tuple[Callable[[str], int], Callable[[], int]]:
        """(documents matching a word, documents in all): filed documents with text,
        outside the configured special folders. Counted in SQL, lazily."""
        names = [
            self.special.inbox,
            self.special.ongoing,
            self.special.important,
            self.special.quarantine,
        ]
        params: dict = {}
        clauses = []
        for i, name in enumerate(names):
            escaped = name.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            params[f"s{i}"] = name
            params[f"s{i}p"] = escaped + "/%"
            clauses.append(f"f.path = :s{i} OR f.path LIKE :s{i}p ESCAPE '\\'")
        base = (
            "SELECT count(*) FROM file_fts JOIN files f ON f.drive_id = file_fts.drive_id "
            "WHERE f.missing IS NOT 1 AND f.parked_at IS NULL "
            f"AND NOT ({' OR '.join(clauses)})"
        )

        def number(extra: str, more: dict) -> int:
            with self.repo.engine.connect() as conn:
                return conn.execute(sql_text(base + extra), {**params, **more}).scalar() or 0

        def count(word: str) -> int:
            quoted = '"' + word.replace('"', '""') + '"'
            return number(" AND file_fts MATCH :q", {"q": quoted})

        return count, lambda: number("", {})

    def _follow_up(self, req: FileRequest) -> _FollowUp:
        """Validate a request's tray/collections/note (no DB writes)."""
        if not isinstance(req.tray_fields, dict):
            raise InvalidRequest("tray fields must be a mapping")
        fields: dict = {}
        if req.tray is not None:
            fields = self.trays.filing_fields(
                req.tray, req.tray_fields, self.prefill_for(req.drive_id)
            )
            # already in this tray: refused (an open item in another tray is moved here later)
            if req.tray in self.trays.open_trays([req.drive_id]).get(req.drive_id, []):
                name = next((t.name for t in self.trays.defs() if t.id == req.tray), req.tray)
                raise InvalidRequest(f"already in {name}")
        elif req.tray_fields:
            raise InvalidRequest("tray fields given without a tray")
        if isinstance(req.collections, str) or not isinstance(req.collections, list | tuple):
            raise InvalidRequest("collections must be a list of names")
        names: dict[str, str] = {}
        for raw in req.collections:
            name = check_collection_name(raw)
            names.setdefault(name.casefold(), name)
        for flag in ("star", "important"):
            if not isinstance(getattr(req, flag), bool):
                raise InvalidRequest(f"{flag} must be true or false")
        return _FollowUp(
            req.tray, fields, list(names.values()), check_note(req.note), req.star, req.important
        )

    def _run_follow_up(
        self, drive_id: str, follow: _FollowUp, batch_id: str | None, outcome: FileItResult
    ) -> None:
        def failed(what: str, e: Exception) -> None:
            log.warning("%s for %s failed (batch %s)", what, drive_id, batch_id, exc_info=True)
            outcome.follow_up_error = outcome.follow_up_error or f"{type(e).__name__}: {e}"

        item_id: int | None = None
        if follow.tray is not None:
            try:
                item = self.trays.move_in_filing(drive_id, follow.tray, follow.fields, batch_id)
                if item is None:
                    item = self.trays.create(
                        follow.tray, [drive_id], follow.fields, None, batch_id=batch_id
                    )
                item_id = item.id
                outcome.items.append(item_id)
            except Exception as e:
                failed("creating the tray item", e)
        for name in follow.collections:
            try:
                coll = self.collections.get_or_create(name)
                self.collections.add_members(coll.id, [drive_id], batch_id=batch_id)
            except Exception as e:
                failed(f"adding to collection {name!r}", e)
        # the built-in Starred and Important collections, as the batch's memberships
        if follow.star:
            try:
                starred = self.collections.builtin("starred")
                self.collections.add_members(starred.id, [drive_id], batch_id=batch_id)
            except Exception as e:
                failed("starring", e)
        if follow.important:
            try:
                important = self.collections.builtin("important")
                self.collections.set_group_path(important.id, [drive_id], None, batch_id=batch_id)
            except Exception as e:
                failed("marking important", e)
        if not follow.note:
            return
        if follow.tray is not None and item_id is None:
            outcome.follow_up_error = outcome.follow_up_error or (
                "note not added: the tray item was not created"
            )
            return
        kind, target = ("item", str(item_id)) if item_id is not None else ("file", drive_id)
        try:
            added = self.notes.add_if_absent(kind, target, follow.note, batch_id=batch_id)
        except Exception as e:
            failed("adding the note", e)
            return
        if not added:
            rec = self.repo.get(drive_id)
            name = rec.name if rec is not None else drive_id
            outcome.follow_up_error = outcome.follow_up_error or (
                f"note not added: {name} already has a note"
            )

    # -- helpers ------------------------------------------------------------

    def _record(self, drive_id: str) -> FileRecord:
        rec = self.repo.get(drive_id)
        if rec is None or rec.missing or rec.parked_at is not None:
            raise NotFound(drive_id)
        return rec

    def rule_context(self, drive_id: str) -> tuple[FileRecord, str, str | None]:
        """``(record, text, inbox_alias)`` for judging the rules against one document;
        ``NotFound`` for a file that is gone."""
        rec = self._record(drive_id)
        alias = self.special.inbox if self.repo.inbox_code_of(rec.path) is not None else None
        return rec, self.repo.text_for(drive_id), alias

    def _suggest(self, rec: FileRecord, text: str) -> Suggestion:
        # a file in a code's inbox folder counts as in the inbox for ``folder_is``
        alias = self.special.inbox if self.repo.inbox_code_of(rec.path) is not None else None
        layout = self.repo.layout_for(rec.drive_id)
        found = suggest(
            rec,
            text,
            self._rules(),
            self.special,
            inbox_alias=alias,
            layout=layout,
            people=self.people_context(rec.drive_id),
        )
        if found.waiting_for_page1 and self._want_layouts is not None:
            self._want_layouts([rec.drive_id])
        if found.folder is None and self._in_inbox(rec):
            folder = similar_folder(self.repo.engine, rec.drive_id, rec.name or "", text, rec.ext)
            if folder is not None:
                found.folder = folder
                found.folder_source = SIMILAR_SOURCE
                found.sources.append(SIMILAR_SOURCE)
        # codes last: what a code sets beats the rules and similar files
        table = {c.code: c for c in self._codes()}
        reads = known_reads(self.repo, rec, table)
        hits = codes_for(self.repo, rec, table, reads)
        if hits:
            stem, ext, name = stem_and_ext(rec)
            found = apply_codes(
                found, hits, table, found.doc_date, stem, ext, self.special, original_name=name
            )
        return apply_ticks(found, reads)

    @staticmethod
    def _tray_guess(found: Suggestion, tray_ids: list[str], barcode: str | None) -> str | None:
        """A code decides the tray (None for "file as suggested": already handled);
        otherwise ``guess_tray`` from the rules and the scan."""
        if (found.tray_source or "").startswith("code:"):
            return found.tray if found.tray in tray_ids else None
        return guess_tray(found.fields, found.tray, tray_ids, barcode)

    def _in_inbox(self, rec: FileRecord) -> bool:
        return self.repo.in_inbox_path(rec.path)

    def _ops(self, reqs: list[FileRequest]) -> list[tuple[FileRequest, Op | None]]:
        seen: set[str] = set()
        out: list[tuple[FileRequest, Op | None]] = []
        for req in reqs:
            if req.drive_id in seen:
                raise InvalidRequest(f"file {req.drive_id!r} requested twice")
            seen.add(req.drive_id)
            if not req.name or "/" in req.name:
                raise InvalidRequest(f"invalid name {req.name!r}")
            if is_ds_store_name(req.name):
                raise InvalidRequest(f"the name {req.name!r} is reserved for Finder's .DS_Store")
            self.paths.abs(req.folder)  # OutsideArchiveError (a ValueError) if not a rel
            dest = canonical(req.folder, self.paths)
            # never into the quarantine or Ongoing, whatever the file's marks (an
            # Important file would otherwise skip BrowseService.quarantine's check)
            check_destination_area(dest, self.special)
            rec = self._record(req.drive_id)
            same_folder = fold_parts(dest) == fold_parts(parent(rec.path))
            if same_folder and req.name == rec.name:
                op = None
            elif same_folder:
                op = Op(OpKind.RENAME, rec.path, req.name)
            else:
                op = Op(OpKind.MOVE, rec.path, req.folder, name=req.name)
            out.append((req, op))
        return out

    def _check_identity(
        self, pairs: list[tuple[FileRequest, Op | None]], resolved: list[ResolvedOp]
    ) -> None:
        """Each RENAME/MOVE must be the requested file, a regular file on disk
        (``check_disk_identity``): catches an index that is stale."""
        ids = [req.drive_id for req, op in pairs if op is not None]
        check_disk_identity(self.paths, self.repo, ids, resolved)

    @staticmethod
    def _plan(pairs: list[tuple[FileRequest, Op | None]], origin: str) -> Plan:
        acting = [req for req, op in pairs if op is not None]
        label = None
        if len(acting) == 1:
            label = f"Filed {acting[0].name} into {acting[0].folder}"
        elif acting:
            folders = {req.folder for req in acting}
            where = f" into {next(iter(folders))}" if len(folders) == 1 else ""
            label = f"Filed {len(acting)} files{where}"
        return Plan(
            [op for _, op in pairs if op is not None], origin=check_origin(origin), label=label
        )
