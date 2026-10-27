"""The Ongoing publisher: each open, published collection mirrored in ``##. Ongoing``.

Layout: a collection whose only (live) member is a folder, and which has no groups and
no published child collections, is one direct link ``##. Ongoing/<name>`` -> that
folder; any other collection is a folder ``##. Ongoing/<name>/`` holding one link per
live ungrouped member, one subfolder per group (nested groups nest), each holding its
members' links, and one entry per published child collection (see below). A group's
folder is named after the group, ``<name>_2`` when a sibling has the name. A collection
without any live member and without a published child is not published at all (its
owned entries are taken down, as for a closed one). Missing, parked and quarantined
members get no link until they come back; a member whose name cannot be a link name
(e.g. ``.ds_store``) is skipped and named in the status.

Parent collections (round 2). ``##. Ongoing`` mirrors the collection tree: a child
collection is published *inside its parent's folder*, at ``##. Ongoing/<parent
path>/<name>``, in the same form it would take at the top (a direct link, or a folder
holding its links, groups and its own children). Its entry is a sibling of the parent's
member links and group folders, and name clashes among siblings of every kind (links,
group folders, child entries) get ``_2``, members first, then groups, then children
A-Z; the suffix is stable across syncs (an owned entry whose name is a variant of the
wanted one is kept). A parent with nothing of its own is still a folder while a child is
published in it. A child is published only while every ancestor is open and published
(the tree is one unit: an unpublished or closed parent takes its children down with it;
the service refuses to close a parent with open children, and stale state is handled
the same way). Moving a collection to another parent or to the top, and renaming a
child, take its whole subtree down and recreate it at the new place, in the same
batch, exactly as a group rename does; a root rename keeps the in-place rule below.
Planning works per *tree*: one share per top-level collection, whose desired state
nests its descendants; every entry is recorded for the collection it belongs to (the
child's folder or link, and what is inside it, for the child), so each collection has
its own ``ongoing_rel`` and ``ongoing_status``.

Ownership is by identity. Every entry the publisher creates (its folder, its links) is
recorded in ``ongoing_entries`` with the identity (``dam.ops.identity``) it has right after
creation and, for a link, the exact readlink value written. An entry is the publisher's
only while the record still matches: same rel, same kind, same dev/ino, same readlink
value (the birth time is not compared: Google Drive for desktop re-writes a new item a
few seconds after creating it, keeping the inode but giving it a new birth, so a birth
that differs while the rest matches is the app's own entry; the stored birth is then
refreshed). A mismatch means someone else replaced it: the record is forgotten, the entry is never
touched, and the collection's ``ongoing_status`` says so for as long as the entry is
there. Nothing else in ``##. Ongoing`` is ever touched either (real files, foreign
links, folders, foreign links inside the collection's own folder); something foreign at
a name the publisher wants makes it use ``<name>_2`` (``unique_name`` semantics). An
existing link is never adopted, even one pointing at the right folder (the Ongoing
converter records ownership explicitly). ``collections.ongoing_rel`` mirrors the owned
top entry (the collection's own folder or link) for display.

Only "nothing there" (ENOENT) forgets a record. An entry that cannot be read for any
other reason is unknown: that tree is skipped for the sync (records kept, nothing
planned) and reported. So is a tree with an entry of the same kind and, for a link, the
same readlink value at its recorded rel but a new dev/ino (Drive may re-enumerate): it
is neither forgotten (which would publish ``<name>_2``) nor touched, and the
``ongoing_status`` says so. An Ongoing folder that lists as empty while entries are
recorded skips the whole sync (as the scanner's empty-root guard).

A folder (a collection's, or a group's) holding anything it does not own (other than a
genuine Finder ``.DS_Store``) is never removed, nor is any folder above it: its own
links are, and ``ongoing_status`` says ``"Needs attention: <reason>"`` (on the collection
whose folder it is, on the collection whose folder it was to leave, and on each
collection above it whose own folder had to stay because of it; a collection that
moved away still gets the note about what it left behind). The root collection's
folder also stays its place on a rename or a switch to a direct link, until it is
empty. Only folders the publisher created (recorded, identity matching) are ever
removed, always after their own links and subfolders, deepest first. A child
collection's folder is removed only when that child is taken down itself (closed,
unpublished, moved, renamed, or its tree taken down): the parent's reconciliation
keeps every wanted child folder in place.

Every disk change is a ``Plan`` (origin ``"workflow"``) of MKDIR / SYMLINK /
UNLINK_SYMLINK / REMOVE_EMPTY_DIR through the executor (journaled). All removals come
first, then all creations, so a name vacated in the same plan (a rename, or two
collections swapping names) is reused instead of suffixed. There is never a MOVE or
RENAME inside Ongoing: a renamed collection's entry, or a renamed or moved group's or
child's subtree, is removed and recreated. Creations are ``exact``: the path must
still be free at act time. These batches cannot be undone
(the DB is the truth; undo the collection change instead) and skip the throttle.
The one exception is the Ongoing converter's batch (origin ``"ui"``, undoable): it
carries the publisher's creations for the converted collection (``layout_after``),
and, when converting into a child whose ancestor is one direct link, that ancestor's
switch to a folder (the link's unlink, then the folder with the ancestor's own links,
recorded for the ancestor). The undo of such a batch puts the link back exactly as
it was; ``ongoing_switched`` remembers that it was the publisher's, and
``forget_undone`` records it again (same rel, same readlink value) once the undo has
run, so the sync that follows is quiet.

Races. ``sync`` reads the DB and lists Ongoing without holding ``SCAN_LOCK`` (it never
blocks scans), plans, then applies. If the user changes Ongoing in between, the
executor catches it: ``apply`` re-resolves the plan against the disk (an exact MKDIR or
SYMLINK whose path became occupied refuses the whole plan; nothing runs), then each op
is pre-checked at act time (destination exists, source no longer a link) and
``remove_empty_dir`` re-checks emptiness itself and that the folder still has the
recorded identity (every REMOVE_EMPTY_DIR carries the record's dev/ino: a folder of the
user's swapped in under the same name is refused on the opened fd); the batch stops at
the first refusal. The next sync re-plans from what is then on disk. A link swapped
between planning and its UNLINK is the one residual window (the executor checks only
that it is a link).
Syncs are serialised by a lock of their own, so two triggers never plan twice.
A plan that failed at act time is not applied again while every sync resolves to the
same plan (one failed batch in the journal, not one per trigger), for at most an hour
(then it is retried once more); ``last_failure`` says why until the plan changes or a
sync succeeds. It is kept in memory only.

Two roots (stars). The publisher also mirrors the two built-in collections, by their
``kind`` (their ``publish`` flag is empty and never consulted):

- ★ Ongoing (``starred``): one link per live member *at the top level* of
  ``##. Ongoing``, next to the project collections' entries, sharing their name space
  (a clash gets ``_2`` by ``first_free``; an owned variant of the wanted name is
  kept, so the suffix is stable). Its records are top-level links recorded for the
  built-in; the project trees never see them (they are not of any tree's collection)
  and avoid their names like any other entry on disk.
- ! Important (``important``): published at the root of ``##. Important`` itself,
  which is a top-level archive folder the publisher never creates or removes: its
  members at the top, its groups as subfolders (nested), reconciled exactly like a
  collection's own folder in Ongoing (``_reconcile`` on a synthetic, unremovable node
  for the root). Identity records, no adoption (the user's existing shortcuts there
  are foreign until the Important converter adopts them: a clash gets ``_2``), the
  left-alone rules, the empty-listing guard and the failing-sync throttle all apply
  per root. When ``##. Important`` is missing or not a folder, that root does nothing
  and says so (the built-in's ``ongoing_status``); the Ongoing root still syncs.

Records are partitioned by their ``rel`` (every record lies under exactly one root,
``_records(root)``; the roots must not contain each other, else the Important root
is left alone and says so), so ``ongoing_entries`` needs no root column; each root is
planned, previewed, applied (one batch per root, so a refusal or failure in one
never holds the other back) and recorded on its own, under the same ``sync_lock``.
The empty-listing guard is per root too: an ``##. Important`` that lists empty while
records exist skips only that root, so a Drive that is partly there never makes the
app forget (and then republish as ``_2``) what it owns in ``##. Important``.
The deletion exception is the same under both roots: only app-owned links and
app-owned (identity-matched) empty folders strictly inside the root, plus a genuine
Finder ``.DS_Store``; the guards (``ops.guards``) and the primitives take the root as
a parameter and refuse everything else. The one addition is a *conversion* (origin
``"ui"``, previewed with a fingerprint, undoable): the Important converter's batch
(``collections.convert_important``) unlinks the user's own links in ``##. Important``
and carries this publisher's creations for the built-in as it will be
(``important_layout_after``); "Star it" in the Ongoing converter does the same for
one ★ link (``star_layout_after``). Both are recorded with ``record_layout``.

Archive folders that are not there. A member in an extra archive folder that is not
connected now (an unplugged disk) is not gone, and one in a detached folder is left
as it was: a sync leaves out every change to a link into such a folder (no link is
created, repaired, replaced or taken down, nor the folder it is in, nor whatever was
to take its place) and plans the rest as usual (``_hold``). Once the folder is back,
the next sync catches up.
"""

from dam.collections.ongoing.model import (
    IDENTITY_CHANGED,
    NOT_MANAGED,
    NOT_SHOWN,
    ORIGIN,
    PUBLISHER_ID,
    REPLACED,
    RETRY_FAILED_S,
    Children,
    Desired,
    Layout,
    LeftAlone,
    Node,
    Record,
    Share,
    SyncResult,
    Want,
    WantedLink,
    depth_of,
    entry_kind,
    first_free,
    flatten,
    forest,
    is_variant,
    items_text,
    log,
    names_for_links,
    split_name,
    wanted_name_of,
)
from dam.collections.ongoing.publisher import OngoingPublisher
from dam.collections.ongoing.remount import RemountedEntry, RemountedRoot

_REPLACED = REPLACED  # the name the tests and older imports use

__all__ = [
    "OngoingPublisher",
    "RemountedEntry",
    "RemountedRoot",
    "log",
    "PUBLISHER_ID",
    "ORIGIN",
    "NOT_MANAGED",
    "NOT_SHOWN",
    "REPLACED",
    "RETRY_FAILED_S",
    "IDENTITY_CHANGED",
    "Children",
    "LeftAlone",
    "Desired",
    "WantedLink",
    "Want",
    "SyncResult",
    "Layout",
    "Record",
    "Node",
    "Share",
    "items_text",
    "entry_kind",
    "split_name",
    "first_free",
    "is_variant",
    "names_for_links",
    "wanted_name_of",
    "depth_of",
    "forest",
    "flatten",
]
