"""Configure per-run diagnostic files and concise console logging."""

from __future__ import annotations

from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


logger = logging.getLogger(__name__)
_owned_handlers: list[logging.Handler] = []


def _reserve_log_path(directory: Path, app_name: str) -> Path:
    """Reserve a new filename even when several runs start in one second."""
    stem = f"{app_name}_{datetime.now():%Y%m%d_%H%M%S}"
    suffix = 0
    while True:
        name = f"{stem}_{suffix}.log" if suffix else f"{stem}.log"
        path = directory / name
        try:
            with path.open("x", encoding="utf-8"):
                return path
        except FileExistsError:
            suffix += 1


def setup_logging(
    app_name: str = "tmag_viewer",
    log_dir: str | Path | None = None,
    console_level: int = logging.INFO,
) -> str:
    """Replace root handlers, returning a fresh UTF-8 rotating log path.

    The default directory is ``host/logs`` regardless of working directory.
    Detached foreign handlers remain open; only handlers created here are
    closed on reconfiguration. Directory and file errors propagate to callers.
    """
    directory = (
        Path(log_dir) if log_dir is not None
        else Path(__file__).resolve().parent.parent / "logs"
    )
    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-7s] %(message)s"
    ))
    directory.mkdir(parents=True, exist_ok=True)
    path = _reserve_log_path(directory, app_name)
    file_handler = RotatingFileHandler(
        path, maxBytes=10 * 1024 * 1024, backupCount=7, encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-7s] %(name)s:%(lineno)d - %(message)s"
    ))

    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)
    for handler in _owned_handlers:
        handler.close()
    _owned_handlers[:] = [file_handler, console_handler]
    root.setLevel(logging.DEBUG)
    root.addHandler(file_handler)
    root.addHandler(console_handler)
    logger.info("Logging initialized: %s", path)
    return str(path)
