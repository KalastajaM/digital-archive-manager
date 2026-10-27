"""The App container: builds the engine pieces once and wires the services to them."""

import logging
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import InitVar, dataclass, field, fields
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
from dam.core.jobs import Jobs
from dam.core.paths import ArchivePaths
from dam.db.engine import make_engine, migrate
from dam.db.tables import files
from dam.errors import (
    ArchiveUnavailable,
    Conflict,
    InvalidRequest,
    NotConfigured,
    NotFound,
)
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
from dam.rules.model import LEARNED_FILE, Rule, RuleError, load_rule_file, load_rules
from dam.rules.picture import AREAS_DIR, Pictures
from dam.search import SearchContext, SearchHit, search
from dam.services.activity import ActivityService
from dam.services.area_pictures import AreaPictures
from dam.services.assignments import AssignmentService
from dam.services.browse import BrowseService
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
# why the archive cannot be closed or its database replaced now: a batch of changes
# (filing, undo, a sync) is still journaling
BATCH_RUNNING = "A change is still being carried out. Try again when it has finished."


# -- construction ------------------------------------------------------------------------
# The App is built in groups, each by one function from explicit inputs: the file index,
# the operation layer, the collections (which publish into the archive through it), then
# the services. ``BUILD_ORDER`` lists them in the order ``App.create`` calls them, and
# ``tests/test_app_wiring.py`` checks that every input of a group is made before it. The
# services also get the App itself (``live``), only to read what changes while it runs
# (settings, rules, trays, codes) and the few methods of the App they call back.


@dataclass(frozen=True)
class IndexParts:
    """The file index: its rows, tags, the extractors and the content indexer."""

    repo: FileRepo
    tags: TagRepo
    registry: ExtractorRegistry
    content: ContentIndexer


def build_index(
    settings: Settings, app_paths: AppPaths, paths: ArchivePaths, engine: Engine
) -> IndexParts:
    repo = FileRepo(engine, inbox=settings.special_folders.inbox)
    paths.has_rows = repo.has_live_under  # an empty mount with rows is not connected
    registry = default_registry(settings.ocr_languages)
    content = ContentIndexer(
        paths,
        repo,
        engine,
        registry,
        settings.indexer_reads_per_minute,
        ocr_languages=settings.ocr_languages,
        cache_dir=app_paths.cache_dir,
    )
    return IndexParts(repo=repo, tags=TagRepo(engine), registry=registry, content=content)


@dataclass(frozen=True)
class OpsParts:
    """The operation layer (the only writer to the archive) and its background copies."""

    executor: Executor
    copy_jobs: CopyJobs


def build_ops(
    settings: Settings,
    app_paths: AppPaths,
    paths: ArchivePaths,
    engine: Engine,
    repo: FileRepo,
    jobs: Jobs,
) -> OpsParts:
    executor = Executor(
        paths,
        engine,
        repo,
        throttle_ms=settings.ops_throttle_ms,
        areas_dir=app_paths.config_dir / "rules" / AREAS_DIR,
    )
    copy_jobs = CopyJobs(jobs)  # moves across disks that run in the background
    executor.copying = copy_jobs.running
    return OpsParts(executor=executor, copy_jobs=copy_jobs)


@dataclass(frozen=True)
class CollectionParts:
    """Collections, marks and locks, and the publishers that mirror them in the archive."""

    notes: NotesService
    publishers: PublisherRegistry
    collections: CollectionService
    marks: MarkService
    locks: LockService
    ongoing: OngoingPublisher
    convert: OngoingConverter
    convert_important: ImportantConverter


def build_collections(
    settings: Settings, paths: ArchivePaths, engine: Engine, repo: FileRepo, executor: Executor
) -> CollectionParts:
    notes = NotesService(engine)
    publishers = PublisherRegistry()
    collections = CollectionService(
        engine, repo, publishers, settings.special_folders, quarantines=paths.quarantines
    )
    marks = MarkService(collections)
    # a locked file (Important, or locked by the owner) is not changed on disk
    locks = LockService(engine, marks.important_paths)
    executor.locks = locks
    ongoing = OngoingPublisher(paths, repo, executor, collections)
    publishers.register(ongoing)
    convert = OngoingConverter(paths, repo, executor, collections, ongoing)
    convert_important = ImportantConverter(paths, repo, executor, collections, ongoing)

    # Collection changes made through the service re-sync every publisher right away, in
    # the caller's thread, after the change has committed.
    def sync_publishers(label: str | None = None) -> object:
        return publishers.sync_all(label=label).get(ONGOING)

    collections.on_change = sync_publishers
    convert.sync_publishers = sync_publishers
    convert_important.sync_publishers = sync_publishers
    return CollectionParts(
        notes=notes,
        publishers=publishers,
        collections=collections,
        marks=marks,
        locks=locks,
        ongoing=ongoing,
        convert=convert,
        convert_important=convert_important,
    )


@dataclass(frozen=True)
class ServiceParts:
    """What the API and the commands use: one service per screen or task."""

    trays: TrayService
    scan_fields: ScanFieldService
    rule_record: RuleRecord
    tag_admin: TagAdmin
    pictures: Pictures
    replay_jobs: ReplayJobs
    area_pictures: AreaPictures
    assignments: AssignmentService
    inbox: InboxService
    layout: LayoutService
    intake: IntakeService
    browse: BrowseService
    maintenance: MaintenanceService
    activity: ActivityService
    today: TodayService
    launch: LaunchService
    previews: PreviewService
    ai: AIService
    summaries: SummaryService


def build_services(
    app_paths: AppPaths,
    paths: ArchivePaths,
    engine: Engine,
    index: IndexParts,
    ops: OpsParts,
    cols: CollectionParts,
    live: "App",
) -> ServiceParts:
    special = live.settings.special_folders
    repo, executor, content = index.repo, ops.executor, index.content
    # an item's date changed: forget reminder records of occasions it no longer has
    trays = TrayService(
        engine,
        lambda: live.tray_defs,
        on_date_changed=lambda item_id: clear_unsent(engine, item_id),
        # inbox is created below, with this TrayService
        prefill_for=lambda drive_id: inbox.prefill_for(drive_id),
    )
    # inbox is created next, with this ScanFieldService
    scan_fields = ScanFieldService(engine, lambda drive_id: inbox.detected_fields(drive_id))
    rule_record = RuleRecord(engine)
    # page-1 pictures (cache) and the crops of picture areas (the rules' folder)
    pictures = Pictures(lambda: live.rules_dir, app_paths.cache_dir)
    area_pictures = AreaPictures(
        repo,
        app_paths.cache_dir,
        lambda: live.rules_dir,
        want_layouts=lambda ids: content.want_layouts(ids),
        executor=executor,
    )
    assignments = AssignmentService(engine, repo, lambda: live.settings.people)
    inbox = InboxService(
        paths,
        repo,
        index.tags,
        executor,
        lambda: live.rules,
        special,
        trays,
        cols.collections,
        cols.notes,
        scan_fields,
        lambda: live.codes,
        rule_record=rule_record,
        rules_dir=lambda: live.rules_dir,
        data_dir=app_paths.data_dir,
        want_layouts=lambda ids: content.want_layouts(ids),
        layout_blocked=lambda drive_id: content.layout_blocked(drive_id),
        people=lambda: live.settings.people,
        address_zone=lambda: live.settings.address_zone,
        assigned_person=assignments.person_of,
        assignments=assignments,
        pictures=pictures,
        area_pictures=area_pictures,
    )
    layout = LayoutService(
        paths,
        executor,
        app_paths,
        reload_rules=live.reload_rules,
        defaults_dir=lambda: live.defaults_dir,
        rescan=live.scan,
    )
    browse = BrowseService(
        repo,
        executor,
        special,
        cols.collections.member_paths,
        important=cols.marks.important_paths,
        important_lock=cols.collections.important_lock,
        rescan=live.scan,
    )
    browse.copy_jobs = ops.copy_jobs
    maintenance = MaintenanceService(
        paths,
        repo,
        engine,
        executor,
        cols.locks,
        cols.collections,
        index.tags,
        cols.notes,
        trays,
        assignments,
        tray_name=live.tray_name,
        rescan=live.scan,
        important_lock=cols.collections.important_lock,
        ongoing=cols.ongoing,
    )
    activity = ActivityService(
        executor, trays, cols.collections, cols.notes, rule_record, cols.ongoing
    )
    today = TodayService(
        trays,
        lambda: live.tray_defs,
        cols.collections,
        cols.notes,
        lambda: repo.counts()["inbox"],
        repo,
        paths.quarantines,
        cols.convert.unmanaged_count,
        inbox.list,
        cols.convert_important.unmanaged_count,
    )
    # DAM_AI_FAKE=1 (demos, tests): a deterministic provider that counts as a key
    provider = None
    if os.environ.get("DAM_AI_FAKE") == "1":
        from dam.ai.fake import FakeProvider, demo_reply

        provider = FakeProvider(demo_reply, demo=True)
    return ServiceParts(
        trays=trays,
        scan_fields=scan_fields,
        rule_record=rule_record,
        tag_admin=TagAdmin(engine),
        pictures=pictures,
        replay_jobs=ReplayJobs(),  # rule tests that run in the background
        area_pictures=area_pictures,
        assignments=assignments,
        inbox=inbox,
        layout=layout,
        intake=IntakeService(paths, executor, rescan=live.scan),
        browse=browse,
        maintenance=maintenance,
        activity=activity,
        today=today,
        launch=LaunchService(paths),
        previews=PreviewService(paths, app_paths.cache_dir / "thumbs"),
        ai=AIService(live, provider),
        summaries=SummaryService(engine, repo),
    )


# the groups in the order they are built; a group's inputs are made by those before it
BUILD_ORDER = (build_index, build_ops, build_collections, build_services)


def _take(app: "App", parts: object) -> None:
    """Set each part of a group on the App, under its own name."""
    for f in fields(parts):  # type: ignore[arg-type]
        setattr(app, f.name, getattr(parts, f.name))


@dataclass(eq=False)
class App:
    settings: Settings
    app_paths: AppPaths
    paths: ArchivePaths
    engine: Engine
    # the background runner: the workers (``dam serve`` starts them), the moves across
    # disks, and their status; closing the App stops them
    jobs: Jobs
    index_parts: InitVar[IndexParts]
    ops_parts: InitVar[OpsParts]
    repo: FileRepo = field(init=False)
    tags: TagRepo = field(init=False)
    registry: ExtractorRegistry = field(init=False)
    content: ContentIndexer = field(init=False)
    executor: Executor = field(init=False)
    copy_jobs: CopyJobs = field(init=False)
    notes: NotesService = field(init=False)
    publishers: PublisherRegistry = field(init=False)
    collections: CollectionService = field(init=False)
    marks: MarkService = field(init=False)
    locks: LockService = field(init=False)
    ongoing: OngoingPublisher = field(init=False)
    convert: OngoingConverter = field(init=False)
    convert_important: ImportantConverter = field(init=False)
    trays: TrayService = field(init=False)
    scan_fields: ScanFieldService = field(init=False)
    rule_record: RuleRecord = field(init=False)
    tag_admin: TagAdmin = field(init=False)
    pictures: Pictures = field(init=False)
    replay_jobs: ReplayJobs = field(init=False)
    area_pictures: AreaPictures = field(init=False)
    assignments: AssignmentService = field(init=False)
    inbox: InboxService = field(init=False)
    layout: LayoutService = field(init=False)
    intake: IntakeService = field(init=False)
    browse: BrowseService = field(init=False)
    maintenance: MaintenanceService = field(init=False)
    activity: ActivityService = field(init=False)
    today: TodayService = field(init=False)
    launch: LaunchService = field(init=False)
    previews: PreviewService = field(init=False)
    ai: AIService = field(init=False)
    summaries: SummaryService = field(init=False)
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

    def __post_init__(self, index_parts: IndexParts, ops_parts: OpsParts) -> None:
        _take(self, index_parts)
        _take(self, ops_parts)
        cols = build_collections(self.settings, self.paths, self.engine, self.repo, self.executor)
        _take(self, cols)
        _take(
            self,
            build_services(
                self.app_paths, self.paths, self.engine, index_parts, ops_parts, cols, self
            ),
        )
        self.wake_indexer = lambda: None
        self.content.barcode_trays = self.barcode_trays
        self.content.thumbs = self.pictures.thumbs
        self.content.page1_backfill = lambda: self.settings.page1_backfill
        self.content.page1_fast_per_minute = lambda: self.settings.page1_text_reads_per_minute
        self.reload_rules()

    def tray_name(self, tray_id: str) -> str:
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
            index = build_index(settings, app_paths, paths, engine)
            jobs = Jobs()
            ops = build_ops(settings, app_paths, paths, engine, index.repo, jobs)
            return cls(settings, app_paths, paths, engine, jobs, index, ops)
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
            return load_rule_file(path) if path.exists() else []
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
        # a file whose read stopped dam last time (``dam index`` or the app) is skipped
        self.content.recover_interrupted()
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
            disconnected=self.paths.disconnected_labels(cached=True),
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

    @contextmanager
    def held(self) -> Iterator[None]:
        """Around a change that closes the archive or replaces its database (a reopen,
        a restore, a change of archive folders): ``Conflict`` when a job or a batch of
        changes runs now, and none starts until the change is done."""
        with self.copy_jobs.held(), self.executor.batches.held():
            if self.jobs_running():
                raise Conflict(JOBS_RUNNING)  # closing the App would end them unasked
            if self.executor.batches.running():
                raise Conflict(BATCH_RUNNING)  # it would journal into the closed database
            yield

    def close(self) -> None:
        self.executor.cancel_copies.set()  # a copy in progress ends at its next chunk
        self.copy_jobs.close()
        self.replay_jobs.close()
        self.maintenance.close()
        self.jobs.close()  # the workers end before what they use is closed
        self.content.close()
        self.engine.dispose()
