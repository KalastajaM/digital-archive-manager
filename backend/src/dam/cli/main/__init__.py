"""The ``dam`` command line. A thin interface: every command only calls ``App`` services.

Exit codes: 0 success; 1 user error (unknown file, invalid request, guard refusal);
2 command line usage error (click); 3 internal error (traceback goes to the log file);
4 a batch problem (``failed``, ``error``, ``index_error`` or a tag error).
"""

# The command modules register their commands when imported, so this order is the order
# ``dam --help`` lists them in (the order they had in one module). Only ``app`` is used
# from outside; each command and helper lives in its module.
# isort: off
from dam.cli.main import (  # noqa: F401
    common,
    files_cmds,
    serve_cmds,
    setup_cmds,
    remind_cmds,
    archives_cmds,
    ai_cmds,
    trays_cmds,
    stars_cmds,
)

# isort: on
from dam.cli.main.common import app

__all__ = ["app"]
