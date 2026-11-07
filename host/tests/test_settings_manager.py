"""Settings survive partial files and failed atomic writes without losing data."""
import json
from pathlib import Path

import pytest

from tmag_viewer import settings_manager as settings


@pytest.fixture
def target(tmp_path, monkeypatch):
    path = tmp_path / "nested" / "settings.json"
    monkeypatch.setattr(settings, "get_settings_path", lambda: path)
    return path


def write_config(target, data):
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data), encoding="utf-8")


def test_missing_defaults_are_fresh(target):
    from tmag_viewer.color_scheme import DEFAULT_COLORS

    first = settings.load_settings()
    assert first["panels"] == {"left": True, "right": True, "log": True}
    assert first["acquisition"] == {
        "port": "", "baud": 115200, "kalman": False, "sample_rate_hz": 0,
    }
    assert first["colors"] == dict(DEFAULT_COLORS)
    assert first["chart_labels"] == {}
    first["colors"]["TEXT"] = "damaged"
    first["panels"]["left"] = False
    assert settings.load_settings() == settings.DEFAULTS


def test_partial_merge_keeps_future_keys_and_isolates_inputs(target):
    override = {"panels": {"left": False, "future": {"items": [1]}},
                "future": ["kept"], "chart_labels": {"x": "磁场"}}
    write_config(target, override)
    result = settings.load_settings()
    assert result["panels"] == {
        "left": False, "right": True, "log": True, "future": {"items": [1]},
    }
    assert result["future"] == ["kept"]
    assert result["chart_labels"] == {"x": "磁场"}
    base = {"nested": {"a": [1]}}
    merged = settings._deep_merge(base, override)
    merged["nested"]["a"].append(2)
    merged["panels"]["future"]["items"].append(2)
    assert base == {"nested": {"a": [1]}}
    assert override["panels"]["future"]["items"] == [1]


@pytest.mark.parametrize("content", [b"{broken", b"[]", b"null", b'"root"', b"\xff"])
def test_unreadable_content_uses_defaults(target, content, caplog):
    target.parent.mkdir(parents=True)
    target.write_bytes(content)
    assert settings.load_settings() == settings.DEFAULTS
    assert "FILE_IO" in caplog.text


def test_read_os_error_uses_defaults(target, caplog):
    target.mkdir(parents=True)
    assert settings.load_settings() == settings.DEFAULTS
    assert "op=read" in caplog.text


@pytest.mark.parametrize("bad", [None, [], "bad", 7])
def test_malformed_sections_do_not_replace_dict_defaults(target, bad):
    write_config(target, {"colors": bad, "panels": bad, "chart_labels": bad,
                          "acquisition": {"baud": 9600}, "future": bad})
    result = settings.load_settings()
    for section in ("colors", "panels", "chart_labels"):
        assert result[section] == settings.DEFAULTS[section]
    assert result["acquisition"]["baud"] == 9600
    assert result["future"] == bad


@pytest.mark.parametrize("bad", [None, [], "bad", 7])
def test_malformed_acquisition_section_uses_default(target, bad):
    write_config(target, {"acquisition": bad, "panels": {"left": False}})
    assert settings.load_settings()["acquisition"] == settings.DEFAULTS["acquisition"]
    assert settings.load_settings()["panels"]["left"] is False


@pytest.mark.parametrize("patch", [
    {"panels": {"left": 1, "right": "false", "log": None}},
    {"acquisition": {"port": 1, "baud": True, "kalman": 1, "sample_rate_hz": -1}},
    {"acquisition": {"baud": 0, "sample_rate_hz": True}},
    {"acquisition": {"baud": 1.5, "sample_rate_hz": 2.5}},
])
def test_invalid_known_values_fall_back(target, patch):
    write_config(target, patch)
    assert settings.load_settings() == settings.DEFAULTS


def test_colors_validate_without_changing_live_palette(target):
    from tmag_viewer.color_scheme import ColorScheme
    before = ColorScheme.TEXT
    write_config(target, {"colors": {"TEXT": "#aBc", "LIGHT": "invalid", "future": "kept"}})
    result = settings.load_settings()
    assert result["colors"]["TEXT"] == "#aBc"
    assert result["colors"]["LIGHT"] == settings.DEFAULTS["colors"]["LIGHT"]
    assert result["colors"]["future"] == "kept"
    assert ColorScheme.TEXT == before


def test_utf8_atomic_save_replaces_complete_file(target, monkeypatch, caplog):
    write_config(target, {"old": True})
    old_bytes = target.read_bytes()
    replace = settings.os.replace
    observed = []

    def inspect_replace(source, destination):
        assert Path(source).parent == target.parent
        assert target.read_bytes() == old_bytes
        observed.append(json.loads(Path(source).read_text(encoding="utf-8")))
        replace(source, destination)

    monkeypatch.setattr(settings.os, "replace", inspect_replace)
    caplog.set_level("INFO", logger=settings.__name__)
    data = {"chart_labels": {"x": "磁场"}}
    settings.save_settings(data)
    assert observed == [data]
    assert "磁场" in target.read_text(encoding="utf-8")
    assert settings.load_settings()["chart_labels"] == data["chart_labels"]
    assert list(target.parent.iterdir()) == [target]
    assert "op=rename" in caplog.text


def test_save_creates_parent(target):
    settings.save_settings({"chart_labels": {"x": "X"}})
    assert target.exists()


@pytest.mark.parametrize("failure", ["serialize", "replace", "fdopen", "fsync", "mkstemp"])
def test_failed_save_preserves_previous_file_and_cleans_temp(target, monkeypatch, caplog, failure):
    write_config(target, {"old": "intact"})
    old_bytes = target.read_bytes()
    data = {"unsupported": object()} if failure == "serialize" else {"new": True}

    def fail(*args, **kwargs):
        raise OSError("simulated " + failure)

    if failure in ("replace", "fdopen", "fsync"):
        monkeypatch.setattr(settings.os, failure, fail)
    elif failure == "mkstemp":
        monkeypatch.setattr(settings.tempfile, "mkstemp", fail)
    with pytest.raises((TypeError, OSError)):
        settings.save_settings(data)
    assert target.read_bytes() == old_bytes
    assert list(target.parent.iterdir()) == [target]
    assert "FAILED" in caplog.text


def test_paths_are_anchored_to_module_or_frozen_executable(monkeypatch, tmp_path):
    monkeypatch.delattr(settings.sys, "frozen", raising=False)
    monkeypatch.chdir(tmp_path)
    assert settings.get_settings_path() == Path(settings.__file__).resolve().parent.parent / "settings.json"
    monkeypatch.setattr(settings.sys, "frozen", True, raising=False)
    monkeypatch.setattr(settings.sys, "executable", str(tmp_path / "viewer.exe"))
    assert settings.get_settings_path() == tmp_path / "settings.json"
