"""The App container: builds the engine pieces once and wires the services to them."""

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import Engine, func, select

from dam.ai.service import AIService
from dam.codes.model import CodeProblem, FilingCode, check_table, load_codes
from dam.codes.model import save_codes as write_codes
from dam.collections.convert import OngoingConverter
from dam.collections.convert_important import ImportantConverter
from dam.collections.marks import MarkService
from dam.collections.ongoing import PUBLISHER_ID as ONGOING
from dam.collections.ongoing import OngoingPublisher
from dam.collections.publishers import PublisherRegistry
from dam.collections.service import CollectionService
from dam.config import DEFAULTS_DIR, AppPaths, Person, Settings, load_settings
from dam.core.paths import ArchivePaths
from dam.db.engine import make_engine, migrate
from dam.db.tables import files
from dam.extract.base import ExtractorRegistry, default_registry
from dam.index.content import ContentIndexer
from dam.index.repo import FileRepo, TagRepo
from dam.index.scanner import ScanReport, listable, scan
from dam.locks import LockService
from dam.maintenance.service import MaintenanceService
from dam.notes import NotesService
from dam.ops.executor import Executor
from dam.ops.jobs import CopyJobs
from dam.reminders.engine import clear_unsent
from dam.reminders.notify import RemindResult
from dam.rules.jobs import ReplayJobs
from dam.rules.learned import rule_file, write_rules_file
from dam.rules.model import LEARNED_FILE, Rule, RuleError, _load_file, load_rules
from dam.rules.picture import AREAS_DIR, Pictures
from dam.search import SearchContext, SearchHit, search
from dam.services.activity import ActivityService
from dam.services.area_pictures import AreaPictures
from dam.services.assignments import AssignmentService
from dam.services.browse import BrowseService
from dam.services.errors import ArchiveUnavailable, InvalidRequest, NotConfigured, NotFound
from dam.services.inbox import InboxService
from dam.services.intake import IntakeService
from dam.services.launch import LaunchService
from dam.services.layout import LayoutService
from dam.services.preview import PreviewService
from dam.services.rule_record import RuleRecord
from dam.services.scan_fields import ScanFieldService
from dam.services.summaries import SummaryService
from dam.services.today import TodayService
from dam.settings_write import write_keys
from dam.setup import NOT_CONFIGURED
from dam.tags import TagAdmin
from dam.trays import defaults as tray_defaults
from dam.trays.model import TrayDef, load_trays
from dam.trays.service import TrayService

log = logging.getLogger(__name__)

# why the archive cannot be reopened now (adding, detaching or attaching a folder)
JOBS_RUNNING = (
    "A maintenance check, rule replay or move across disks is running. Try again when it"
    " has finished."
)


@dataclass(eq=False)
class App:
    settings: Settings
    app_paths: AppPaths
    paths: ArchivePaths
    engine: Engine
    repo: FileRepo
    tags: TagRepo
    tag_admin: TagAdmin = field(init=False)
    executor: Executor
    registry: ExtractorRegistry
    content: ContentIndexer
    trays: TrayService = field(init=False)
    notes: NotesService = field(init=False)
    rule_record: RuleRecord = field(init=False)
    assignments: AssignmentService = field(init=False)
    publishers: PublisherRegistry = field(init=False)
    collections: CollectionService = field(init=False)
    marks: MarkService = field(init=False)
    locks: LockService = field(init=False)
    ongoing: OngoingPublisher = field(init=False)
    convert: OngoingConverter = field(init=False)
    convert_important: ImportantConverter = field(init=False)
    inbox: InboxService = field(init=False)
    pictures: Pictures = field(init=False)
    replay_jobs: ReplayJobs = field(init=False)
    area_pictures: AreaPictures = field(init=False)
    browse: BrowseService = field(init=False)
    maintenance: MaintenanceService = field(init=False)
    activity: ActivityService = field(init=False)
    today: TodayService = field(init=False)
    launch: LaunchService = field(init=False)
    previews: PreviewService = field(init=False)
    ai: AIService = field(init=False)
    summaries: SummaryService = field(init=False)
    scan_fields: ScanFieldService = field(init=False)
    layout: LayoutService = field(init=False)
    intake: IntakeService = field(init=False)
    # where the shipped default tray files live (tests point it elsewhere)
    defaults_dir: Path = field(init=False, default=DEFAULTS_DIR)
    # ends the background indexer's idle wait (``dam serve`` wires it); a no-op otherwise
    wake_indexer: Callable[[], None] = field(init=False)
    rules: list[Rule] = field(init=False, default_factory=list)
    rule_errors: list[RuleError] = field(init=False, default_factory=list)
    tray_defs: list[TrayDef] = field(init=False, default_factory=list)
    tray_errors: list[RuleError] = field(init=False, default_factory=list)
    codes: list[FilingCode] = field(init=False, default_factory=list)
    code_problems: list[CodeProblem] = field(init=False, default_factory=list)
    # the last completed ``run_reminders`` result (for Today); None until a run in this
    # process. ``dam serve`` sets ``skipped`` on it when its latest check was skipped.
    last_reminders: RemindResult | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        special = self.settings.special_folders
        # an item's date changed: forget reminder records of occasions it no longer has
        self.trays = TrayService(
            self.engine,
            lambda: self.tray_defs,
            on_date_changed=lambda item_id: clear_unsent(self.engine, item_id),
            # self.inbox is created below, with this TrayService
            prefill_for=lambda drive_id: self.inbox.prefill_for(drive_id),
        )
        self.notes = NotesService(self.engine)
        self.publishers = PublisherRegistry()
        self.collections = CollectionService(
            self.engine, self.repo, self.publishers, special, quarantines=self.paths.quarantines
        )
        self.marks = MarkService(self.collections)
        # a locked file (Important, or locked by the owner) is not changed on disk
        self.locks = LockService(self.engine, self.marks.important_paths)
        self.executor.locks = self.locks
        self.ongoing = OngoingPublisher(self.paths, self.repo, self.executor, self.collections)
        self.publishers.register(self.ongoing)
        self.convert = OngoingConverter(
            self.paths, self.repo, self.executor, self.collections, self.ongoing
        )
        # Collection changes made through the service re-sync every publisher right
        # away, in the caller's thread, after the change has committed.
        self.convert_important = ImportantConverter(
            self.paths, self.repo, self.executor, self.collections, self.ongoing
        )
        self.collections.on_change = self.sync_publishers
        self.convert.sync_publishers = self.sync_publishers
        self.convert_important.sync_publishers = self.sync_publishers
        # self.inbox is created next, with this ScanFieldService
        self.scan_fields = ScanFieldService(
            self.engine, lambda drive_id: self.inbox.detected_fields(drive_id)
        )
        self.rule_record = RuleRecord(self.engine)
        self.tag_admin = TagAdmin(self.engine)
        # page-1 pictures (cache) and the crops of picture areas (the rules' folder)
        self.pictures = Pictures(lambda: self.rules_dir, self.app_paths.cache_dir)
        self.replay_jobs = ReplayJobs()  # rule tests that run in the background
        self.copy_jobs = CopyJobs()  # moves across disks that run in the background
        self.area_pictures = AreaPictures(
            self.repo,
            self.app_paths.cache_dir,
            lambda: self.rules_dir,
            want_layouts=lambda ids: self.content.want_layouts(ids),
            executor=self.executor,
        )
        self.assignments = AssignmentService(self.engine, self.repo, lambda: self.settings.people)
        self.inbox = InboxService(
            self.paths,
            self.repo,
            self.tags,
            self.executor,
            lambda: self.rules,
            special,
            self.trays,
            self.collections,
            self.notes,
            self.scan_fields,
            lambda: self.codes,
            rule_record=self.rule_record,
            rules_dir=lambda: self.rules_dir,
            data_dir=self.app_paths.data_dir,
            want_layouts=lambda ids: self.content.want_layouts(ids),
            layout_blocked=lambda drive_id: self.content.layout_blocked(drive_id),
            people=lambda: self.settings.people,
            address_zone=lambda: self.settings.address_zone,
            assigned_person=self.assignments.person_of,
            assignments=self.assignments,
            pictures=self.pictures,
            area_pictures=self.area_pictures,
        )
        self.layout = LayoutService(
            self.paths,
            self.executor,
            self.app_paths,
            reload_rules=self.reload_rules,
            defaults_dir=lambda: self.defaults_dir,
            rescan=self.scan,
        )
        self.intake = IntakeService(self.paths, self.executor, rescan=self.scan)
        self.browse = BrowseService(
            self.repo,
            self.executor,
            special,
            self.collections.member_paths,
            important=self.marks.important_paths,
            important_lock=self.collections.important_lock,
            rescan=self.scan,
        )
        self.browse.copy_jobs = self.copy_jobs
        self.executor.copying = self.copy_jobs.running
        self.maintenance = MaintenanceService(
            self.paths,
            self.repo,
            self.engine,
            self.executor,
            self.locks,
            self.collections,
            self.tags,
            self.notes,
            self.trays,
            self.assignments,
            tray_name=self._tray_name,
            rescan=self.scan,
            important_lock=self.collections.important_lock,
        )
        self.activity = ActivityService(
            self.executor,
            self.trays,
            self.collections,
            self.notes,
            self.rule_record,
            self.ongoing,
        )
        self.today = TodayService(
            self.trays,
            lambda: self.tray_defs,
            self.collections,
            self.notes,
            lambda: self.repo.counts()["inbox"],
            self.repo,
            self.paths.quarantines,
            self.convert.unmanaged_count,
            self.inbox.list,
            self.convert_important.unmanaged_count,
        )
        self.wake_indexer = lambda: None
        self.launch = LaunchService(self.paths)
        self.previews = PreviewService(self.paths, self.app_paths.cache_dir / "thumbs")
        self.content.barcode_trays = self.barcode_trays
        self.content.thumbs = self.pictures.thumbs
        self.content.page1_backfill = lambda: self.settings.page1_backfill
        self.content.page1_fast_per_minute = lambda: self.settings.page1_text_reads_per_minute
        # DAM_AI_FAKE=1 (demos, tests): a deterministic provider that counts as a key
        provider = None
        if os.environ.get("DAM_AI_FAKE") == "1":
            from dam.ai.fake import FakeProvider, demo_reply

            provider = FakeProvider(demo_reply, demo=True)
        self.ai = AIService(self, provider)
        self.summaries = SummaryService(self.engine, self.repo)
        self.reload_rules()

    def _tray_name(self, tray_id: str) -> str:
        return next((t.name for t in self.tray_defs if t.id == tray_id), tray_id)

    def barcode_trays(self) -> list[str]:
        """The trays whose open items' files get the barcode pass: those with an IBAN."""
        return [
            t.id
            for t in self.tray_defs
            if any(name == "iban" or f.type == "iban" for name, f in t.fields.items())
        ]

    @classmethod
    def create(cls, data_dir: Path | None = None, require_archive: bool = True) -> "App":
        """Open the app on ``data_dir`` (default: ``DAM_DATA_DIR`` or the standard folder).

        Raises ``ArchiveUnavailable`` if the archive folder is not an existing folder
        (an absent archive must never look like an empty one). ``require_archive=False``
        only for commands that never read the archive (``dam openapi``).
        """
        app_paths = AppPaths(data_dir)
        app_paths.ensure()
        settings = load_settings(app_paths)
        if settings.archive_root is None:
            if require_archive:
                raise NotConfigured(NOT_CONFIGURED)
            # a command that never reads the archive: point at a folder that does not
            # exist, never at a real one
            root = app_paths.data_dir / "no-archive-configured"
        else:
            root = settings.archive_root
        if require_archive and not root.is_dir():
            raise ArchiveUnavailable(
                f"the archive folder {root} is not available (no such folder). Check that "
                "your cloud drive (Google Drive, OneDrive, Dropbox, ...) is running and "
                f"signed in, and that archive_root in "
                f"{app_paths.config_dir / 'settings.yaml'} is right."
            )
        paths = ArchivePaths(root, settings)
        engine = make_engine(app_paths.db_path)
        try:
            migrate(engine)
            repo = FileRepo(engine, inbox=settings.special_folders.inbox)
            paths.has_rows = repo.has_live_under  # an empty mount with rows is not connected
            registry = default_registry(settings.ocr_languages)
            return cls(
                settings=settings,
                app_paths=app_paths,
                paths=paths,
                engine=engine,
                repo=repo,
                tags=TagRepo(engine),
                executor=Executor(
                    paths,
                    engine,
                    repo,
                    throttle_ms=settings.ops_throttle_ms,
                    areas_dir=app_paths.config_dir / "rules" / AREAS_DIR,
                ),
                registry=registry,
                content=ContentIndexer(
                    paths,
                    repo,
                    engine,
                    registry,
                    settings.indexer_reads_per_minute,
                    ocr_languages=settings.ocr_languages,
                    cache_dir=app_paths.cache_dir,
                ),
            )
        except BaseException:
            engine.dispose()
            raise

    def sync_publishers(self, label: str | None = None) -> object:
        """Sync every registered publisher (failures logged); returns the Ongoing
        publisher's ``SyncResult`` (None if it failed or is not registered). ``label``:
        what the user did, the title of the batch the sync journals."""
        return self.publishers.sync_all(label=label).get(ONGOING)

    @property
    def archive_available(self) -> bool:
        """The archive folder can be listed right now (Drive may go away)."""
        # the main folder: extra folders being offline is reported per folder
        return listable(self.paths.root)

    @property
    def rules_dir(self) -> Path:
        return self.app_paths.config_dir / "rules"

    @property
    def trays_dir(self) -> Path:
        return self.app_paths.config_dir / "trays"

    def reload_rules(self) -> list[RuleError]:
        """Reload the rule and tray files (bad files are skipped and reported in
        ``rule_errors``/``tray_errors``), then recompute the open items' dates under the
        new tray config (a failure there is logged, never fatal). Returns the rule
        errors followed by the tray errors."""
        self.rules, self.rule_errors = load_rules(self.rules_dir)
        self.tray_defs, self.tray_errors = load_trays(self.trays_dir)
        self.codes, self.code_problems = load_codes(
            self.app_paths.filing_codes_path, {t.id for t in self.tray_defs}
        )
        # files in a code's inbox folder (``<inbox>/To pay``) are inbox files
        self.repo.code_folders = {
            c.inbox_folder.casefold(): c.code for c in self.codes if c.inbox_folder is not None
        }
        try:
            self.trays.refresh_dates()
        except Exception:
            log.warning("recomputing tray item dates failed", exc_info=True)
        return [*self.rule_errors, *self.tray_errors]

    def _rule_file_rules(self, path: Path) -> list[Rule]:
        try:
            return _load_file(path) if path.exists() else []
        except ValueError as e:
            raise InvalidRequest(f"{path.name} could not be read: {e}") from e

    def _write_rule_file(self, path: Path, rules: list[Rule]) -> None:
        try:
            write_rules_file(path, rules)
        except OSError as e:
            raise InvalidRequest(f"the rule could not be saved: {e}") from e
        self.reload_rules()

    def save_rule(
        self, rule: Rule, replaces: str | None = None, place_above: str | None = None
    ) -> None:
        """Save ``rule``. A new rule goes at the end of ``learned.yaml``, or directly above
        the rule ``place_above`` when that is in ``learned.yaml`` (hand-written files are
        never reordered); with
        ``replaces`` (an id) that rule is rewritten in place, in whichever file holds it,
        and the file's other rules are kept as they are. A repeated id raises
        ``InvalidRequest``; ``NotFound`` if ``replaces`` is unknown."""
        if rule.id != replaces and any(r.id == rule.id for r in self.rules):
            raise InvalidRequest(f"a rule with the id {rule.id!r} exists already")
        if replaces is None:
            path = self.rules_dir / LEARNED_FILE
            current = self._rule_file_rules(path)
            at = next((i for i, r in enumerate(current) if r.id == place_above), len(current))
            current.insert(at, rule)
            self._write_rule_file(path, current)
            return
        path = rule_file(self.rules_dir, replaces)
        if path is None:
            raise NotFound(replaces)
        current = self._rule_file_rules(path)
        self._write_rule_file(path, [rule if r.id == replaces else r for r in current])

    def delete_rule(self, rule_id: str) -> None:
        """Remove a rule from the file that holds it (the file is backed up first)."""
        path = rule_file(self.rules_dir, rule_id)
        if path is None:
            raise NotFound(rule_id)
        self._write_rule_file(path, [r for r in self._rule_file_rules(path) if r.id != rule_id])

    def move_rule(self, rule_id: str, delta: int) -> None:
        """Move a learned rule ``delta`` places within ``learned.yaml`` (clamped)."""
        path = rule_file(self.rules_dir, rule_id)
        if path is None:
            raise NotFound(rule_id)
        if path.name != LEARNED_FILE:
            raise InvalidRequest("only learned rules can be moved here")
        rules = self._rule_file_rules(path)
        i = next(n for n, r in enumerate(rules) if r.id == rule_id)
        j = max(0, min(len(rules) - 1, i + delta))
        rules.insert(j, rules.pop(i))
        self._write_rule_file(path, rules)

    def set_page1_backfill(self, enabled: bool) -> None:
        """Turn the page-1 backfill on or off (``page1_backfill`` in settings.yaml) and use
        it from now on. ``InvalidRequest`` when the file could not be written."""
        try:
            write_keys(
                self.app_paths, {"page1_backfill": enabled}, lambda s: s.page1_backfill == enabled
            )
        except OSError as e:
            raise InvalidRequest(f"the setting could not be saved: {e}") from e
        self.settings.page1_backfill = enabled
        if enabled:
            self.wake_indexer()

    def set_page1_speed(self, reads_per_minute: int) -> None:
        """Set how many PDFs with a text layer have page 1 read per minute
        (``page1_text_reads_per_minute`` in settings.yaml) and use it from now on.
        ``InvalidRequest`` for a rate outside 1 to 6000 or when the file could not be
        written."""
        if not 1 <= reads_per_minute <= 6000:
            raise InvalidRequest("Page 1 reading speed is between 1 and 6000 a minute.")
        try:
            write_keys(
                self.app_paths,
                {"page1_text_reads_per_minute": reads_per_minute},
                lambda s: s.page1_text_reads_per_minute == reads_per_minute,
            )
        except OSError as e:
            raise InvalidRequest(f"the setting could not be saved: {e}") from e
        self.settings.page1_text_reads_per_minute = reads_per_minute
        self.wake_indexer()

    def set_people(
        self, people: list[Person], address_zone: tuple[float, float, float, float] | None
    ) -> None:
        """Save the people list (and, when given, the address zone of page 1) to
        settings.yaml and use them from now on. ``InvalidRequest`` when the file could not
        be written (it is left as it was)."""
        updates: dict[str, object] = {"people": [p.model_dump() for p in people]}
        if address_zone is not None:
            updates["address_zone"] = list(address_zone)

        def read_back(s: Settings) -> bool:
            return s.people == people and (address_zone is None or s.address_zone == address_zone)

        try:
            write_keys(self.app_paths, updates, read_back)
        except OSError as e:
            raise InvalidRequest(f"the people could not be saved: {e}") from e
        self.settings.people = people
        if address_zone is not None:
            self.settings.address_zone = address_zone

    def save_codes(self, codes: list[FilingCode]) -> list[CodeProblem]:
        """Replace the code table with ``codes`` and reload. Raises ``InvalidRequest``
        (nothing written) for a repeated code or inbox folder or an unknown tray."""
        problems = check_table(codes, {t.id for t in self.tray_defs})
        if problems:
            raise InvalidRequest("; ".join(f"{p.code}: {p.message}" for p in problems))
        try:
            write_codes(self.app_paths.filing_codes_path, codes)
        except OSError as e:
            raise InvalidRequest(f"the codes could not be saved: {e}") from e
        self.reload_rules()
        return self.code_problems

    @property
    def dismissed_defaults_path(self) -> Path:
        """Default tray keys the user chose not to add (JSON; not in the tray files)."""
        return self.app_paths.data_dir / "tray-defaults-dismissed.json"

    def _dismissed(self, tray_id: str) -> list[str]:
        return tray_defaults.load_dismissed(self.dismissed_defaults_path).get(tray_id, [])

    def tray_defaults_diff(
        self, tray_id: str, paths: list[str] | None = None
    ) -> tray_defaults.DefaultsDiff:
        """What the shipped default tray file adds to the user's tray ``tray_id``
        (dismissed keys left out); ``new_text`` adds ``paths`` (default: all valid)."""
        return tray_defaults.defaults_diff(
            self.trays_dir, self.defaults_dir / "trays", tray_id, paths, self._dismissed(tray_id)
        )

    def apply_tray_defaults(
        self, tray_id: str, paths: list[str], expect_current_text: str, expect_new_text: str
    ) -> tuple[str, Path]:
        """Add the chosen missing default keys to ``tray_id``'s file (backup first) if
        nothing changed since the preview, then reload; returns (file name, backup)."""
        result = tray_defaults.apply_defaults(
            self.trays_dir,
            self.defaults_dir / "trays",
            tray_id,
            paths,
            expect_current_text,
            expect_new_text,
            self._dismissed(tray_id),
        )
        self.reload_rules()
        return result

    def dismiss_tray_defaults(self, tray_id: str, paths: list[str]) -> list[str]:
        """Stop offering those default keys for ``tray_id``; returns all dismissed."""
        return tray_defaults.dismiss(
            self.dismissed_defaults_path,
            self.trays_dir,
            self.defaults_dir / "trays",
            tray_id,
            paths,
        )

    def dismissed_tray_defaults(self, tray_id: str) -> list[str]:
        """The dismissed default keys of ``tray_id`` that are still missing."""
        return tray_defaults.dismissed_paths(
            self.dismissed_defaults_path, self.trays_dir, self.defaults_dir / "trays", tray_id
        )

    def undismiss_tray_defaults(self, tray_id: str, paths: list[str]) -> list[str]:
        """Offer those default keys for ``tray_id`` again; returns the rest dismissed.
        ``NotFound`` for a tray that does not exist."""
        tray_defaults.find_tray_file(self.trays_dir, tray_id)
        return tray_defaults.undismiss(self.dismissed_defaults_path, tray_id, paths)

    def retry_index(self, drive_ids: list[str]) -> int:
        """Queue the files in error/unsupported for content indexing again."""
        queued = self.repo.retry_index(drive_ids)
        if queued:
            self.wake_indexer()
        return queued

    def scan(self, subtree: str = "") -> ScanReport:
        """Sync the file index with the archive (all of it, or ``subtree``)."""
        return scan(self.paths, self.repo, subtree)

    def index(self, limit: int | None = None) -> int:
        """Index file contents until nothing is left to process or ``limit`` files are done,
        then read bank barcodes (``ContentIndexer.run_barcodes_once``) and page-1 layouts
        (``run_layouts_once``) the same way. The layout pass reads only the inbox and the
        wanted files here, never the whole archive: the background pass does the rest."""
        # Hard cap: a file is attempted at most about once per call, so never more than
        # the number of rows, even if a failing file were somehow picked again.
        with self.engine.connect() as conn:
            cap = conn.execute(select(func.count()).select_from(files)).scalar_one()
        if limit is not None:
            cap = min(cap, limit)
        total = 0
        while total < cap:
            n = self.content.run_once(min(20, cap - total))
            if n == 0:
                break
            total += n
        # then the barcode and page-1 layout passes (their reads are not counted as
        # indexed files)
        for read_pass in (
            self.content.run_barcodes_once,
            lambda n: self.content.run_layouts_once(n, backfill=False),
        ):
            read = 0
            while read < cap:
                n = read_pass(min(20, cap - read))
                if n == 0:
                    break
                read += n
        return total

    def search(
        self,
        query: str,
        folder: str | None = None,
        limit: int = 50,
        tags: list[str] | None = None,
        tag_mode: str = "all",
    ) -> list[SearchHit]:
        """Full-text search over names and extracted text, with ``name:value`` filters in
        ``query`` (``dam.query``); ``folder`` limits to a subtree, ``tags`` to files that have
        all of them (``tag_mode`` "any": at least one)."""
        ctx = SearchContext(
            trays=lambda: [(t.id, t.name) for t in self.trays.defs()],
            disconnected=self.paths.disconnected_labels(),
        )
        return search(
            self.engine,
            query,
            limit=limit,
            folder=folder,
            tag_names=tags,
            tag_mode=tag_mode,
            ctx=ctx,
        )

    def jobs_running(self) -> bool:
        """A maintenance check or a rule replay is running (closing the App ends it)."""
        return (
            self.maintenance.jobs.running()
            or self.replay_jobs.running()
            or self.copy_jobs.running()
        )

    def close(self) -> None:
        self.executor.cancel_copies.set()  # a copy in progress ends at its next chunk
        self.copy_jobs.close()
        self.replay_jobs.close()
        self.maintenance.close()
        self.content.close()
        self.engine.dispose()
