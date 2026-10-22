"""Lock shared by every writer of the file index and the archive folder."""

import threading

# The scanner and the operation executor both change the index, and the executor also
# renames files on disk. Without a common lock, a scan can read a directory between the
# executor's rename and its index update (inserting a second row for the moved file), or
# apply directory data it gathered before an op moved a file (reverting that op's index
# update). The executor holds it for one whole operation (act through index update); the
# scanner holds it for one directory (gather plus apply), never a whole scan. It is
# re-entrant so nested index work on the same thread cannot deadlock.
INDEX_LOCK = threading.RLock()
