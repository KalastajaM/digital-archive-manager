"""Inbox: list incoming files with suggestions, and file them (rename + move + tag), then
put them in a tray, in collections and give them a note."""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal

from dam.bills.barcode import BarcodeError
from dam.bills.barcode import parse as parse_barcode
from dam.collections.service import CollectionService, check_collection_name
from dam.config import SpecialFolders
from dam.core.paths import ArchivePaths, nfc
from dam.index.repo import FileRecord, FileRepo, TagRepo
from dam.notes import NotesService, check_note
from dam.ops.executor import Executor
from dam.ops.guards import canonical, fold_parts, is_ds_store_name, parent
from dam.ops.model import BatchResult, Op, OpKind, Plan, ResolvedOp
from dam.rules.engine import Suggestion, suggest
from dam.rules.fields import DetectedFields
from dam.rules.guess import guess_tray
from dam.rules.model import Rule
from dam.rules.similar import SOURCE as SIMILAR_SOURCE
from dam.rules.similar import similar_folder
from dam.services import check_destination_area, check_disk_identity, check_origin
from dam.services.errors import InvalidRequest, NotFound
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


@dataclass
class FileRequest:
    """File ``drive_id`` as ``folder/name`` and add ``tags``; then optionally create an
    item in ``tray`` (``tray_fields`` over the scan's prefill), add the file to the
    ``collections`` named (created if new) and set its ``note``."""

    drive_id: str
    name: str
    folder: str
    tags: list[str] = field(default_factory=list)
    tray: str | None = None
    tray_fields: dict = field(default_factory=dict)
    collections: list[str] = field(default_factory=list)
    note: str = ""


@dataclass
class _FollowUp:
    """A request's validated follow-ups (what ``file_it`` does after the move)."""

    tray: str | None
    fields: dict
    collections: list[str]
    note: str


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

    def list(self) -> list[InboxEntry]:
        """Files directly in the inbox (no folders, links or parked rows), newest first."""
        records = [
            r
            for r in self.repo.list_dir(self.special.inbox)
            if not r.is_dir and not r.is_link and not r.missing and r.parked_at is None
        ]
        records.sort(key=lambda r: r.mtime if r.mtime is not None else float("-inf"), reverse=True)
        tray_ids = [t.id for t in self.trays.defs()]
        open_trays = self.trays.open_trays([r.drive_id for r in records])
        entries = []
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
                    guess_tray(found.fields, found.tray, tray_ids, barcode),
                    open_trays.get(rec.drive_id, []),
                    detected if saved is None else saved,
                    saved is not None,
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
        self, reqs: list[FileRequest], dry_run: bool = False, origin: str = "ui"
    ) -> FileItResult:
        """Apply the plan, then tag the files it filed and run their follow-ups.

        Everything is validated before anything moves: an invalid tray, tray field,
        collection name or note is ``InvalidRequest`` and nothing is applied; so is a
        stale index (a file replaced on disk since the scan, ``check_disk_identity``).

        Tags and follow-ups go only to files whose op is in ``result.done`` (and to files
        that needed no op). A failed or interrupted batch is returned as is, never
        raised. Per file, in order: tags, the tray item, collection memberships, the
        note; each its own DB transaction, all with ``created_by_batch`` = the batch so
        undoing it removes them. A failure is logged and noted (``tag_error``/
        ``untagged``, ``follow_up_error``) and the rest still run. The batch id is never
        lost. If the batch applied nothing (no op needed, or the only ops failed) there
        is nothing to undo: the follow-ups are created with no batch and stay until
        removed by hand.

        Tray fields: the scan's prefill only fills fields left out of ``tray_fields``. A
        caller that showed prefill values to the user (the review card) must send every
        value it displayed explicitly, so what was shown is what is stored; an explicit
        blank means the user cleared it.

        The note goes on the tray item when a tray is chosen (skipped, and reported,
        if the item could not be created), else on the file. A filing note never
        overwrites: if the target already has one, it is not added and that is
        reported in ``follow_up_error``.
        """
        pairs = self._ops(reqs)
        follow_ups = [self._follow_up(req) for req, _ in pairs]
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
        return outcome

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
        return _FollowUp(req.tray, fields, list(names.values()), check_note(req.note))

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

    def _suggest(self, rec: FileRecord, text: str) -> Suggestion:
        found = suggest(rec, text, self._rules(), self.special)
        if found.folder is None and self._in_inbox(rec):
            folder = similar_folder(self.repo.engine, rec.drive_id, rec.name or "", text, rec.ext)
            if folder is not None:
                found.folder = folder
                found.folder_source = SIMILAR_SOURCE
                found.sources.append(SIMILAR_SOURCE)
        return found

    def _in_inbox(self, rec: FileRecord) -> bool:
        return nfc(parent(rec.path)).casefold() == nfc(self.special.inbox).strip("/").casefold()

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
