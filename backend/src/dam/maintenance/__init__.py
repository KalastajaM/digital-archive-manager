"""Maintenance checks: duplicates and a few small lists, each run on a click.

Nothing here runs by itself. A check is a job the owner starts, polls and can stop; it
only reads the index (and, for the duplicate check, the files it must hash). Anything that
changes the archive is a normal previewed batch through the operation layer."""
