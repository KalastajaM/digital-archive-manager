from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
    false,
    text,
)

metadata = MetaData()

files = Table(
    "files",
    metadata,
    Column("drive_id", Text, primary_key=True),
    Column("path", Text, nullable=False, unique=True),
    Column("path_nfc", Text, nullable=False),
    Column("name", Text),
    Column("ext", Text),
    Column("is_dir", Boolean),
    Column("is_link", Boolean),
    Column("link_target", Text, nullable=True),
    Column("size", Integer),
    Column("mtime", Float),
    Column("sha256", Text, nullable=True),
    Column("doc_date", Date, nullable=True),
    # pending | indexed | cloud_pending | error | unsupported
    Column("index_state", Text),
    Column("retry_at", Float, nullable=True),
    Column("attempts", Integer, server_default="0"),
    # why the content could not be indexed (states error / unsupported; 0012)
    Column("last_error", Text, nullable=True),
    Column("missing", Boolean, server_default=false()),
    Column("last_seen", Float),
    # set while a scan holds a displaced row aside; purged by the next full scan
    Column("parked_at", Float, nullable=True),
    # indexes from migration 0004
    Index("ix_files_path_nfc", "path_nfc"),
    Index("ix_files_index_state_retry_at", "index_state", "retry_at"),
    Index("ix_files_parked_at", "parked_at"),
)

file_text = Table(
    "file_text",
    metadata,
    Column("drive_id", Text, ForeignKey("files.drive_id"), primary_key=True),
    Column("text", Text),
    Column("extractor", Text),
    Column("ocr_used", Boolean),
)

# The FTS rowid of each file's ``file_fts`` row (migration 0037). ``file_fts`` cannot
# index ``drive_id``, so every FTS write finds its row through this map, by rowid. Since
# 0044 it also holds the name and path the index searches (NFC; a parked file's path is
# ''): ``file_fts`` keeps no copy and reads them, with ``file_text``, through the view
# ``file_fts_src`` (see ``dam.index.repo.model`` for the order its writes need).
file_fts_map = Table(
    "file_fts_map",
    metadata,
    Column("drive_id", Text, primary_key=True),
    Column("fts_rowid", Integer, nullable=False),
    Column("name", Text, nullable=False, server_default=""),
    Column("path", Text, nullable=False, server_default=""),
    Index("ix_file_fts_map_fts_rowid", "fts_rowid", unique=True),
)

# The bank barcode read from the file's scan (migration 0009); ``code`` None: read, none
# found (0010). ``sha256`` is the content it was read from: a row for other content is
# ignored, and the barcode pass reads the file again.
file_barcodes = Table(
    "file_barcodes",
    metadata,
    Column("drive_id", Text, ForeignKey("files.drive_id"), primary_key=True),
    Column("code", Text, nullable=True),
    Column("sha256", Text, nullable=True),
    Column("read_at", Float, nullable=False),
)

# The dam QR stickers read from page 1 of the file's scan (migration 0026): ``reads`` is
# a JSON list of ``QrRead`` (``[]``: read, none found). Same lifetime as
# ``file_barcodes``: a row for other content than ``sha256`` is ignored and read again.
file_qr_codes = Table(
    "file_qr_codes",
    metadata,
    Column("drive_id", Text, ForeignKey("files.drive_id"), primary_key=True),
    Column("sha256", Text, nullable=True),
    Column("reads", Text, nullable=False),
    Column("read_at", Float, nullable=False),
)

# The filing code the owner gave an inbox file in the app (migration 0035): one per file,
# kept after filing (an undone filing brings the file back with it) and used only while
# the file is in the inbox. Not tied to the content: the decision is about the document.
file_assigned_codes = Table(
    "file_assigned_codes",
    metadata,
    Column("drive_id", Text, ForeignKey("files.drive_id"), primary_key=True),
    Column("code", Text, nullable=False),
    Column("assigned_at", Float, nullable=False),
)

# Where the text of page 1 sits (migration 0028): ``lines`` is a JSON list of
# ``{text, box}`` (``[]``: read, no text on page 1), zlib-compressed since 0045
# (``Page1Layout.stored``), ``source`` the reader
# (``text-layer`` | ``vision`` | ``tesseract``). Same lifetime as ``file_barcodes``: a row
# for other content than ``sha256`` is ignored and read again.
file_layouts = Table(
    "file_layouts",
    metadata,
    Column("drive_id", Text, ForeignKey("files.drive_id"), primary_key=True),
    Column("sha256", Text, nullable=True),
    Column("lines", LargeBinary, nullable=False),
    Column("source", Text, nullable=False),
    Column("read_at", Float, nullable=False),
)

tags = Table(
    "tags",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", Text, unique=True),
    # migration 0033: pinned for the sidebar (when), the group it is shown in (no
    # foreign key: SQLite cannot add one to a column), when it was last put on a file
    Column("pinned_at", Float, nullable=True),
    Column("group_id", Integer, nullable=True),
    Column("last_used_at", Float, nullable=True),
)

tag_groups = Table(
    "tag_groups",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", Text, nullable=False, unique=True),
)

file_tags = Table(
    "file_tags",
    metadata,
    Column("drive_id", Text, ForeignKey("files.drive_id"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id"), primary_key=True),
    Index("ix_file_tags_tag_id", "tag_id"),  # migration 0033
)

operations = Table(
    "operations",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("batch_id", Text),
    Column("seq", Integer),
    Column("kind", Text),
    Column("src", Text, nullable=True),
    Column("dst", Text, nullable=True),
    Column("drive_id", Text, nullable=True),
    Column("size", Integer, nullable=True),
    Column("mtime", Float, nullable=True),
    Column("is_file", Boolean, nullable=True),  # source was a regular file (0002)
    # planned | done | failed | unverified (acted, verification failed) | undone
    Column("state", Text),
    Column("error", Text, nullable=True),
    Column("origin", Text),
    Column("undo_of", Text, nullable=True),
    Column("created", Float),
    Column("finished", Float, nullable=True),
    Column("label", Text, nullable=True),  # the batch's title for Activity (0022)
    # rule pictures only (0030): "rename" or "copy", and the sha256 of the file's content
    Column("method", Text, nullable=True),
    Column("content_hash", Text, nullable=True),
    # a folder moved across disks (0036), on its final QUARANTINE: where the copy is, and
    # the folder rows that followed it as JSON {"rows": [[old_id, new_id, old_path,
    # new_path], ...], "applied": bool} (``dam.ops.model.read_followed``)
    Column("copied_to", Text, nullable=True),
    Column("followed", Text, nullable=True),
    Index("ix_operations_batch_id", "batch_id"),  # migration 0004
    # the status poll looks for planned rows (migration 0037)
    Index("ix_operations_planned", "state", sqlite_where=text("state = 'planned'")),
)

# --- Phase 2 (migration 0005): trays, collections, notes, reminders ---
# Notes and checklist items point at their target polymorphically
# (target_kind + target_id), so they carry no foreign key.

items = Table(
    "items",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("tray_id", Text, nullable=False),
    Column("title", Text, nullable=False),
    Column("fields", JSON, nullable=False),
    Column("date", Date, nullable=True),
    # open | done
    Column("state", Text, nullable=False, server_default="open"),
    Column("created", Float, nullable=False),
    Column("done_at", Float, nullable=True),
    Column("done_fields", JSON, nullable=True),
    Column("created_by_batch", Text, nullable=True),
    Index("ix_items_state_date", "state", "date"),
    Index("ix_items_tray_id_state", "tray_id", "state"),
    Index("ix_items_created_by_batch", "created_by_batch"),
)

# No FK to files: files rows may be parked or purged.
item_files = Table(
    "item_files",
    metadata,
    Column("item_id", Integer, ForeignKey("items.id", ondelete="CASCADE"), primary_key=True),
    Column("drive_id", Text, primary_key=True),
    Index("ix_item_files_drive_id", "drive_id"),
)

item_events = Table(
    "item_events",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("item_id", Integer, ForeignKey("items.id", ondelete="CASCADE"), nullable=False),
    Column("at", Float, nullable=False),
    # created | edited | done | reopened | file_added | file_removed | moved
    Column("kind", Text, nullable=False),
    Column("data", JSON, nullable=False),
)

reminders_sent = Table(
    "reminders_sent",
    metadata,
    Column("item_id", Integer, ForeignKey("items.id", ondelete="CASCADE"), primary_key=True),
    Column("rule", Text, primary_key=True),
    Column("occasion", Date, primary_key=True),
    Column("fired_at", Float, nullable=False),
    Column("channels", JSON, nullable=False),
)

collections = Table(
    "collections",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", Text, nullable=False, unique=True),
    # NFC-casefolded name; keeps "Sauna" and "sauna" from coexisting
    Column("name_fold", Text, nullable=False, unique=True),
    # open | closed
    Column("state", Text, nullable=False, server_default="open"),
    Column("created", Float, nullable=False),
    Column("closed_at", Float, nullable=True),
    Column("publish", JSON, nullable=False, server_default=text("'{\"ongoing\": true}'")),
    # managed path inside ##. Ongoing, set by the publisher
    Column("ongoing_rel", Text, nullable=True),
    # set by the publisher when it could not finish ("not managed: <reason>"), else NULL
    Column("ongoing_status", Text, nullable=True),
    # typed by the user (Phase 3 AI may fill it on request); migration 0011
    Column("summary", Text, nullable=False, server_default=""),
    # the parent collection (None: at the top); migration 0015. No cascade: the
    # service keeps the tree whole (no orphans, no cycles)
    Column("parent_id", Integer, ForeignKey("collections.id"), nullable=True),
    # starred | important: the two built-in collections (★ Ongoing, ! Important), one
    # of each; NULL for an ordinary collection. Migration 0017
    Column("kind", Text, nullable=True),
    # the owner's order among the collections with the same parent (0, 1, 2, ...; ties
    # by name); the built-ins ignore it. Migration 0032
    Column("position", Integer, nullable=False, server_default="0"),
    Index("ix_collections_parent_id", "parent_id"),
    Index("ux_collections_kind", "kind", unique=True, sqlite_where=text("kind IS NOT NULL")),
)

collection_members = Table(
    "collection_members",
    metadata,
    Column(
        "collection_id",
        Integer,
        ForeignKey("collections.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("drive_id", Text, primary_key=True),
    Column("added", Float, nullable=False),
    Column("created_by_batch", Text, nullable=True),
    # the member's group in this collection (NULL: ungrouped); migration 0011. No FK:
    # the service keeps it pointing at a group of the same collection.
    Column("group_id", Integer, nullable=True),
    # the name the member's published link keeps (a converted shortcut's own name);
    # NULL: the file's own name. Migration 0019
    Column("link_name", Text, nullable=True),
    Index("ix_collection_members_drive_id", "drive_id"),
    Index("ix_collection_members_created_by_batch", "created_by_batch"),
)

# Groups inside a collection, nested to any depth (migration 0011). Sibling names are
# unique per (collection, parent) after folding; the service enforces it, as SQLite
# treats NULL parents as distinct. ``position`` orders siblings (0, 1, ...).
collection_groups = Table(
    "collection_groups",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "collection_id",
        Integer,
        ForeignKey("collections.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("parent_id", Integer, ForeignKey("collection_groups.id"), nullable=True),
    Column("name", Text, nullable=False),
    Column("name_fold", Text, nullable=False),
    Column("position", Integer, nullable=False),
    Column("summary", Text, nullable=False, server_default=""),
    # the conversion batch that made the group (undo removes it while it is still
    # empty); NULL for a group the user made. Migration 0018
    Column("created_by_batch", Text, nullable=True),
    Index("ix_collection_groups_collection_id_parent_id", "collection_id", "parent_id"),
    Index("ix_collection_groups_created_by_batch", "created_by_batch"),
)

# What the Ongoing publisher created (migration 0008). An entry in ##. Ongoing is the
# publisher's only while this record still matches it: same rel, same lstat
# identity (dev, ino, birth: dam.ops.identity) and, for a link, the exact readlink value it wrote.
ongoing_entries = Table(
    "ongoing_entries",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "collection_id",
        Integer,
        ForeignKey("collections.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("rel", Text, nullable=False, unique=True),
    # link | folder
    Column("kind", Text, nullable=False),
    Column("link_value", Text, nullable=True),
    # identity as text (a Windows file index does not fit an INTEGER; migration 0024)
    Column("st_dev", Text, nullable=False),
    Column("st_ino", Text, nullable=False),
    Column("st_birth", Text, nullable=True),
    Column("created", Float, nullable=False),
    Index("ix_ongoing_entries_collection_id", "collection_id"),
)

# Folders a user-confirmed New folder / layout batch made (migration 0023): the
# ``(st_dev, st_ino)`` each had right after it was made. Undo of the batch removes a
# folder only while it still has that identity and is empty.
made_folders = Table(
    "made_folders",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("batch_id", Text, nullable=False),
    Column("rel", Text, nullable=False),
    Column("st_dev", Text, nullable=False),
    Column("st_ino", Text, nullable=False),
    Column("st_birth", Text, nullable=True),
    Column("created", Float, nullable=False),
    UniqueConstraint("batch_id", "rel", name="uq_made_folders_batch_rel"),
)

# A direct link of the publisher's that an Ongoing conversion batch replaced with a
# folder (a parent collection getting its first published child; migration 0016).
# The undo of that batch puts the link back exactly as it was, and the publisher
# then records it as its own again (``OngoingPublisher.forget_undone``). One row per
# switched link, gone once the batch is undone.
# the last ``link_name`` a member had in a collection, kept when its row goes (unmark,
# undo) and given back by a later add without an explicit name. Migration 0020
member_link_names = Table(
    "member_link_names",
    metadata,
    Column(
        "collection_id",
        Integer,
        ForeignKey("collections.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("drive_id", Text, primary_key=True),
    Column("link_name", Text, nullable=False),
)

ongoing_switched = Table(
    "ongoing_switched",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("batch_id", Text, nullable=False),
    Column(
        "collection_id",
        Integer,
        ForeignKey("collections.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("rel", Text, nullable=False),
    Column("link_value", Text, nullable=False),
    Column("created", Float, nullable=False),
    Index("ix_ongoing_switched_batch_id", "batch_id"),
)

notes = Table(
    "notes",
    metadata,
    Column("id", Integer, primary_key=True),
    # file | collection | item
    Column("target_kind", Text, nullable=False),
    Column("target_id", Text, nullable=False),
    Column("text", Text, nullable=False),
    Column("updated", Float, nullable=False),
    Column("created_by_batch", Text, nullable=True),
    UniqueConstraint("target_kind", "target_id"),
    Index("ix_notes_created_by_batch", "created_by_batch"),
)

checklist_items = Table(
    "checklist_items",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("target_kind", Text, nullable=False),
    Column("target_id", Text, nullable=False),
    Column("text", Text, nullable=False),
    Column("done", Boolean, nullable=False, server_default=false()),
    Column("position", Integer, nullable=False),
    Index("ux_checklist_items_position", "target_kind", "target_id", "position", unique=True),
)


# --- Phase 3 (migration 0013): the AI call log and the result cache ---

ai_calls = Table(
    "ai_calls",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("at", Float, nullable=False),  # epoch seconds
    Column("task", Text, nullable=False),
    Column("model", Text, nullable=False),
    Column("files", JSON, nullable=False),  # the drive ids involved
    Column("input_tokens", Integer, nullable=False, server_default="0"),
    Column("output_tokens", Integer, nullable=False, server_default="0"),
    Column("cost_eur", Float, nullable=False, server_default="0"),
    # ok | cached | error | fake (blocked calls never reach the log: nothing was sent;
    # fake is the DAM_AI_FAKE=1 demo provider, logged at no cost as model "fake:<id>")
    Column("outcome", Text, nullable=False),
    Column("error", Text, nullable=True),
    Column("duration_ms", Integer, nullable=False, server_default="0"),
    Index("ix_ai_calls_at", "at"),
)

# A result keyed by what produced it: the file text (sha), task, model and prompt version.
ai_cache = Table(
    "ai_cache",
    metadata,
    Column("sha_key", Text, primary_key=True),
    Column("task", Text, primary_key=True),
    Column("model", Text, primary_key=True),
    Column("prompt_version", Text, primary_key=True),
    Column("data", JSON, nullable=False),
    Column("at", Float, nullable=False),
)

# A file's summary (Phase 3, migration 0014): one row per (drive_id, source), source
# "ai" (saved by "Use this summary") or "user" (typed). ``sha256`` is the content it
# describes: a different current sha means "outdated (the file changed)". No FK to
# files: files rows may be parked or purged.
file_summaries = Table(
    "file_summaries",
    metadata,
    Column("drive_id", Text, primary_key=True),
    Column("source", Text, primary_key=True),
    Column("sha256", Text, nullable=True),
    Column("summary", Text, nullable=False),
    Column("key_facts", JSON, nullable=False),
    Column("at", Float, nullable=False),
)

# A file's scan fields as the user edited them (``services/scan_fields``): JSON list of
# {kind, label, value}. Replaces the detected list for that file; no row = detected.
# Migration 0021. No FK to files: files rows may be parked or purged.
file_fields = Table(
    "file_fields",
    metadata,
    Column("drive_id", Text, primary_key=True),
    Column("fields", Text, nullable=False),
    Column("updated", Float, nullable=False),
)

# What each learned filing rule suggested and whether the user kept it (migration 0027):
# one row per (filing, rule, field). A filing is a (batch_id, drive_id) pair. Removed
# when the batch is undone. No FKs: files rows may be parked or purged.
rule_outcomes = Table(
    "rule_outcomes",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("batch_id", Text, nullable=False),
    Column("drive_id", Text, nullable=False),
    Column("rule_id", Text, nullable=False),
    Column("field", Text, nullable=False),  # "folder" | "name" | "tray"
    Column("kept", Boolean, nullable=False),
    Column("created", Float, nullable=False),
    Index("ix_rule_outcomes_batch_id", "batch_id"),
    Index("ix_rule_outcomes_rule_id", "rule_id"),
)

# Who a document is from and for, as the owner (or a confirmed filing) said (migration
# 0029). Index data only: not journaled. Keyed by ``drive_id`` alone, not by content:
# who a document is from does not change when its content is saved again. No FK, as
# ``rule_outcomes``: files rows may be parked or purged.
file_assignments = Table(
    "file_assignments",
    metadata,
    Column("drive_id", Text, primary_key=True),
    Column("sender", Text, nullable=True),
    Column("person", Text, nullable=True),
    Column("set_by", Text, nullable=False),  # "owner" | "filing"
    Column("set_at", Float, nullable=False),
)

# Pairs of files the owner marked "Not related" (0041): left out of each other's Relatives.
# ``drive_a`` is the smaller of the two drive ids. Keyed by drive id so the mark survives
# moves and renames; no FK (rows may be parked or purged).
related_dismissed = Table(
    "related_dismissed",
    metadata,
    Column("drive_a", Text, primary_key=True),
    Column("drive_b", Text, primary_key=True),
    Column("created", Float, nullable=False),
)

# Where the address sits on page 1 of one document, as the owner drew it (migration 0047):
# used instead of the archive's address area and a rule's. All four sides null: the
# document has no address area (nobody is looked for). No row: the general area applies.
# Keyed by drive id so it survives moves and renames; no FK (rows may be parked or purged).
file_address_zones = Table(
    "file_address_zones",
    metadata,
    Column("drive_id", Text, primary_key=True),
    Column("x0", Float, nullable=True),
    Column("y0", Float, nullable=True),
    Column("x1", Float, nullable=True),
    Column("y1", Float, nullable=True),
    Column("set_at", Float, nullable=False),
)

# Files the owner locked: a safety catch against file changes (``dam.locks``). Keyed by
# drive id so the lock survives moves and renames; no FK (rows may be parked or purged).
# Important files are always locked and need no row. Temporary unlocks are never stored.
file_locks = Table(
    "file_locks",
    metadata,
    Column("drive_id", Text, primary_key=True),
    Column("locked_at", Float, nullable=False),
)

# Maintenance results the owner chose to ignore (0034): left out of later checks until
# they are no longer ignored. ``members``: for a group (duplicates, versions), the JSON
# list of drive ids it had; a group with a file beyond those shows again.
maintenance_ignored = Table(
    "maintenance_ignored",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("kind", Text, nullable=False),
    Column("key", Text, nullable=False),
    Column("label", Text, nullable=False),
    Column("members", Text, nullable=True),
    Column("created", Float, nullable=False),
    UniqueConstraint("kind", "key", name="uq_maintenance_ignored_kind_key"),
)

# Facts about the database itself (0038). ``app``: whose migrations it follows
# (``dam.db.engine.APP_ID``), checked before migrating so a database another build of
# dam stamped with the same revision numbers is never taken for this one's.
dam_meta = Table(
    "dam_meta",
    metadata,
    Column("key", Text, primary_key=True),
    Column("value", Text, nullable=False),
)

# One row per pair reconnected by Maintenance's "Moved outside dam" (migration 0039): the
# old row's ``files`` columns as JSON, and ``moved`` as JSON {table: [[key, ...], ...]},
# the keys (besides the file's id) of each row that moved from ``old_id`` to ``new_id``.
# Undo moves those rows back and brings the old row back; ``undone`` says when.
reconnects = Table(
    "reconnects",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("batch_id", Text, nullable=False),
    Column("old_id", Text, nullable=False),
    Column("new_id", Text, nullable=False),
    Column("old_row", Text, nullable=False),
    Column("moved", Text, nullable=False),
    Column("created", Float, nullable=False),
    Column("undone", Float, nullable=True),
    Index("ix_reconnects_batch_id", "batch_id"),
)

# One row per entry of ##. Ongoing or ##. Important whose new device number Maintenance's
# "Left alone after a Drive restart" took over (migration 0040): the ``ongoing_entries``
# row, its rel, kind and inode, and the device number before and after. Undo puts ``old_dev``
# back while the entry still has ``new_dev`` and that inode; ``undone`` says when.
readopted = Table(
    "readopted",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("batch_id", Text, nullable=False),
    Column("entry_id", Integer, nullable=False),
    Column("rel", Text, nullable=False),
    Column("kind", Text, nullable=False),  # link | folder
    Column("st_ino", Text, nullable=False),
    Column("old_dev", Text, nullable=False),
    Column("new_dev", Text, nullable=False),
    Column("created", Float, nullable=False),
    Column("undone", Float, nullable=True),
    Index("ix_readopted_batch_id", "batch_id"),
)

# One row per rename of a special folder (``dam.special_folders``, migration 0042). The
# folder itself is renamed by a journaled batch (``batch_id``); the row says which settings,
# rules and stored paths followed it, and how far the rename got, so an interruption is
# finished (or undone) at the next start. ``state``: planned (the rename started),
# done, undone, failed (the folder never moved), attention (some of it is done and dam
# could not finish or take it back). ``key``: inbox | ongoing | important |
# quarantine; ``old`` and ``new`` are the folder's names.
special_folder_renames = Table(
    "special_folder_renames",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("batch_id", Text, nullable=False, unique=True),
    Column("key", Text, nullable=False),
    Column("old", Text, nullable=False),
    Column("new", Text, nullable=False),
    Column("state", Text, nullable=False),
    # how many folders the batch renames (one per disk for To Delete)
    Column("folders", Integer, nullable=False, server_default="1"),
    # what followed the folder: JSON {"files": {config file: [[yaml path, old, new]]},
    # "db": {table: [[row id, old, new]]}}; Undo puts back exactly these
    Column("changes", Text, nullable=True),
    # why a rename is ``attention`` (or waits for recovery), in words
    Column("note", Text, nullable=True),
    Column("created", Float, nullable=False),
    Column("finished", Float, nullable=True),
)


# Business IDs, IBANs and domains found in a file's stored text by the country packs
# (migration 0043): one row per (file, kind, value), ``kind`` namespaced by its pack
# ("fi.ytunnus"). ``sha256`` is the content they were found in; rows for other content are
# ignored and the identifiers pass reads the file's text again. No FK, as
# ``file_assignments``; removed and rekeyed with the file.
file_identifiers = Table(
    "file_identifiers",
    metadata,
    Column("drive_id", Text, primary_key=True),
    Column("kind", Text, primary_key=True),
    Column("value", Text, primary_key=True),
    Column("sha256", Text, nullable=False),
    # the company name printed next to the value in this file, when the pack reads one (0046)
    Column("name", Text, nullable=True),
    Index("ix_file_identifiers_kind_value", "kind", "value"),
)

# Which content of each file the identifiers pass read, and with which packs
# (``countries.signature()``, "core:1 fi:1"): another signature reads it again (0043).
file_identifier_reads = Table(
    "file_identifier_reads",
    metadata,
    Column("drive_id", Text, primary_key=True),
    Column("sha256", Text, nullable=False),
    Column("signature", Text, nullable=False),
    Column("read_at", Float, nullable=False),
)

# The owner's name for an identifier (0046): "Vesilaitos Oy" for Y-tunnus 0112038-9. It
# fills From (``file_assignments.sender``, set_by "filing") on the files that carry it,
# never on a row the owner set. ``set_by`` is "owner" (confirmed in Settings, Senders).
identifier_names = Table(
    "identifier_names",
    metadata,
    Column("kind", Text, primary_key=True),
    Column("value", Text, primary_key=True),
    Column("name", Text, nullable=False),
    Column("set_by", Text, nullable=False),
    Column("set_at", Float, nullable=False),
)
