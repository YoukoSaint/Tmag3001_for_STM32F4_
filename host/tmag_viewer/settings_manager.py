"""Qt-free configuration loading and atomic, UTF-8 persistence."""
from copy import deepcopy
import json
import logging
import os
from pathlib import Path
import re
import sys
import tempfile

from .color_scheme import DEFAULT_COLORS


logger = logging.getLogger(__name__)

DEFAULTS = {
    "colors": dict(DEFAULT_COLORS),
    "panels": {"left": True, "right": True, "log": True},
    "acquisition": {"port": "", "baud": 115200, "kalman": False, "sample_rate_hz": 0},
    "chart_labels": {},
}


def get_settings_path() -> Path:
    """Use the host directory, or the executable directory in a frozen build."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "settings.json"
    return Path(__file__).resolve().parent.parent / "settings.json"


def _deep_merge(base: dict, override: dict) -> dict:
    """Return an independent recursive merge, retaining unknown future keys."""
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _safe_overrides(data: dict) -> dict:
    """Reject malformed known values without discarding valid or future keys.

    Known colors accept CSS-style three/six digit hex strings. Validation never
    applies them to the live ColorScheme; unknown color roles remain untouched.
    """
    safe = deepcopy(data)
    for section in DEFAULTS:
        if section in safe and not isinstance(safe[section], dict):
            safe.pop(section)
    for key in DEFAULTS["panels"]:
        panel = safe.get("panels", {})
        if key in panel and not isinstance(panel[key], bool):
            panel.pop(key)
    acquisition = safe.get("acquisition", {})
    validators = {
        "port": lambda value: isinstance(value, str),
        "baud": lambda value: type(value) is int and value > 0,
        "kalman": lambda value: isinstance(value, bool),
        "sample_rate_hz": lambda value: type(value) is int and value >= 0,
    }
    for key, valid in validators.items():
        if key in acquisition and not valid(acquisition[key]):
            acquisition.pop(key)
    colors = safe.get("colors", {})
    for role in DEFAULTS["colors"]:
        if role in colors and (
            not isinstance(colors[role], str)
            or re.fullmatch(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})", colors[role]) is None
        ):
            colors.pop(role)
    return safe


def load_settings() -> dict:
    """Load available settings, falling back safely for missing/invalid files."""
    path = get_settings_path()
    try:
        with path.open("r", encoding="utf-8") as stream:
            data = json.load(stream)
        if not isinstance(data, dict):
            logger.warning("FILE_IO op=read kind=config path=%s FAILED: root must be an object", path)
            return deepcopy(DEFAULTS)
    except FileNotFoundError:
        return deepcopy(DEFAULTS)
    except (OSError, ValueError, UnicodeError) as exc:
        logger.warning("FILE_IO op=read kind=config path=%s FAILED: %s", path, exc)
        return deepcopy(DEFAULTS)
    return _deep_merge(DEFAULTS, _safe_overrides(data))


def save_settings(data: dict) -> None:
    """Replace settings only after the complete new file has reached disk.

    Failures propagate to the caller. Cleanup is limited to our own temporary
    file and cannot hide the original write/serialization/rename exception.
    """
    path = get_settings_path()
    temporary = None
    descriptor = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".settings-", suffix=".tmp", dir=path.parent)
        stream = os.fdopen(descriptor, "w", encoding="utf-8")
        descriptor = None  # The stream owns the descriptor after fdopen succeeds.
        with stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        # Also clean up on interruption, then re-raise it unchanged.
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass
        logger.exception("FILE_IO op=write kind=config path=%s FAILED", path)
        raise
    logger.info("FILE_IO op=rename kind=config path=%s->%s", temporary, path)
