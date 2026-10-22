import logging
from logging.handlers import RotatingFileHandler

from typer.testing import CliRunner

from dam.cli.main import app as cli
from dam.extract.base import ExtractorRegistry, UnsupportedContent
from dam.index.content import ContentIndexer
from dam.index.repo import FileRecord
from dam.logging_setup import configure_logging, log_internal_error
from test_content import FakeExtractor, setup


def _dam_handlers():
    return [h for h in logging.getLogger("dam").handlers if getattr(h, "dam_handler", False)]


def test_content_indexer_info_reaches_log_file(app_paths, fake_archive, engine):
    configure_logging(app_paths)

    def refuse(path):
        raise UnsupportedContent("encrypted")

    paths, repo, _ = setup(fake_archive, engine)
    registry = ExtractorRegistry()
    registry.register(FakeExtractor(refuse, ".pdf"))
    indexer = ContentIndexer(paths, repo, engine, registry, 60)
    try:
        fake_archive.add("##. Organize/e.pdf", b"secret")
        repo.upsert(FileRecord(drive_id="e1", path="##. Organize/e.pdf"))
        indexer.run_once(now=1_000_000.0)
    finally:
        indexer.close()
    for h in _dam_handlers():
        h.flush()
    text = (app_paths.logs_dir / "dam.log").read_text(encoding="utf-8")
    assert "INFO" in text and "unsupported content in ##. Organize/e.pdf" in text


def test_configure_logging_is_idempotent_and_rotates(app_paths):
    configure_logging(app_paths)
    configure_logging(app_paths)
    handlers = _dam_handlers()
    files = [h for h in handlers if isinstance(h, RotatingFileHandler)]
    others = [h for h in handlers if not isinstance(h, RotatingFileHandler)]
    assert len(files) == 1 and len(others) == 1
    assert files[0].baseFilename == str(app_paths.logs_dir / "dam.log")
    assert files[0].maxBytes == 5 * 1024 * 1024 and files[0].backupCount == 3
    assert files[0].level == logging.INFO and others[0].level == logging.WARNING


def test_stderr_gets_warnings_only(app_paths, capsys):
    configure_logging(app_paths)
    log = logging.getLogger("dam.test")
    log.info("quiet info")
    log.warning("loud warning")
    err = capsys.readouterr().err
    assert "loud warning" in err and "quiet info" not in err


def test_internal_error_traceback_goes_to_file_only(app_paths, capsys):
    configure_logging(app_paths)
    try:
        raise RuntimeError("kaput")
    except RuntimeError:
        path = log_internal_error(app_paths.logs_dir)
    for h in _dam_handlers():
        h.flush()
    assert path == app_paths.logs_dir / "dam.log"
    text = path.read_text(encoding="utf-8")
    assert "Traceback" in text and "RuntimeError: kaput" in text
    assert "kaput" not in capsys.readouterr().err


def test_every_cli_command_configures_the_log_file(app_paths):
    r = CliRunner().invoke(cli, ["--data-dir", str(app_paths.data_dir), "scan"])
    assert r.exit_code == 0, r.output
    files = [h for h in _dam_handlers() if isinstance(h, RotatingFileHandler)]
    assert [h.baseFilename for h in files] == [str(app_paths.logs_dir / "dam.log")]
