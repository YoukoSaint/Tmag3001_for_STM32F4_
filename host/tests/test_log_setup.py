"""Behavioral checks for application logging configuration."""

import io
import logging
from pathlib import Path
import re
from datetime import datetime

import pytest

from tmag_viewer import log_setup


@pytest.fixture(autouse=True)
def restore_root_logging():
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    yield
    for handler in root.handlers[:]:
        root.removeHandler(handler)
        if handler not in original_handlers:
            handler.close()
    root.handlers[:] = original_handlers
    root.setLevel(original_level)


def test_routes_levels_and_preserves_utf8_module_and_line(tmp_path, capsys):
    path = Path(log_setup.setup_logging(log_dir=tmp_path / "nested" / "logs"))
    logger = logging.getLogger(__name__)
    logger.debug("debug-only 中文")
    logger.info("visible 中文")

    content = path.read_text(encoding="utf-8")
    console = capsys.readouterr().err
    assert "debug-only 中文" in content
    assert "debug-only" not in console
    assert "visible 中文" in content and "visible 中文" in console
    assert re.search(r"\d{4}-\d{2}-\d{2} .* \[INFO   \] "
                     + re.escape(__name__) + r":\d+ - visible 中文", content)
    assert "Logging initialized:" in content
    assert "tmag_viewer.log_setup:" in content
    assert len(logging.getLogger().handlers) == 2
    assert re.fullmatch(r"tmag_viewer_\d{8}_\d{6}\.log", path.name)


def test_console_level_can_be_overridden(tmp_path, capsys):
    log_setup.setup_logging(log_dir=tmp_path, console_level=logging.WARNING)
    logger = logging.getLogger(__name__)
    logger.info("hidden-info")
    logger.warning("visible-warning")
    console = capsys.readouterr().err
    assert "hidden-info" not in console
    assert "visible-warning" in console


def test_default_directory_is_anchored_to_module(tmp_path, monkeypatch):
    host = tmp_path / "host"
    monkeypatch.setattr(log_setup, "__file__", str(host / "tmag_viewer" / "log_setup.py"))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    path = Path(log_setup.setup_logging())
    assert path.parent == host / "logs"
    assert path.is_file()


def test_repeated_setup_creates_fresh_files_and_closes_owned_file(tmp_path, monkeypatch):
    class FrozenDatetime:
        @staticmethod
        def now():
            return datetime(2026, 11, 7, 12, 30, 0)

    monkeypatch.setattr(log_setup, "datetime", FrozenDatetime)
    first = Path(log_setup.setup_logging(app_name="viewer", log_dir=tmp_path))
    old_file_handler = next(h for h in logging.getLogger().handlers
                            if isinstance(h, logging.FileHandler))
    logging.getLogger(__name__).info("first-run-only")
    second = Path(log_setup.setup_logging(app_name="viewer", log_dir=tmp_path))
    logging.getLogger(__name__).info("second-run-only")
    assert first != second
    assert old_file_handler.stream is None
    assert len(logging.getLogger().handlers) == 2
    first_content = first.read_text(encoding="utf-8")
    second_content = second.read_text(encoding="utf-8")
    assert "first-run-only" in first_content
    assert "second-run-only" not in first_content
    assert "first-run-only" not in second_content
    assert second_content.count("second-run-only") == 1


def test_foreign_handlers_are_detached_without_closing_streams(tmp_path):
    class ForeignHandler(logging.StreamHandler):
        was_closed = False

        def close(self):
            self.was_closed = True
            super().close()

    stream = io.StringIO()
    foreign = ForeignHandler(stream)
    root = logging.getLogger()
    root.addHandler(foreign)
    try:
        log_setup.setup_logging(log_dir=tmp_path)
        assert foreign not in root.handlers
        assert not foreign.was_closed
        assert not stream.closed
    finally:
        root.removeHandler(foreign)
        foreign.close()


def test_log_directory_errors_propagate(tmp_path):
    file_path = tmp_path / "file"
    file_path.write_text("not a directory", encoding="utf-8")
    with pytest.raises(OSError):
        log_setup.setup_logging(log_dir=file_path / "logs")
