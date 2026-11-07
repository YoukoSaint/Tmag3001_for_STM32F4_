"""Pure Python palette contract, with no GUI or installed Qt required."""

import importlib
import subprocess
import sys

import pytest


DEFAULTS = {
    "TEXT": "#c0caf5", "LIGHT": "#1e1f2e", "DARK": "#1a1b26",
    "LINE": "#3b3d56", "BTN": "#3b3d56", "AXIS_X": "#f7768e",
    "AXIS_Y": "#9ece6a", "AXIS_Z": "#7aa2f7", "TEMP": "#e0af68",
    "GRID": "#2c2d3f", "AXIS": "#565f89",
}


@pytest.fixture(autouse=True)
def palette():
    module = importlib.import_module("tmag_viewer.color_scheme")
    original = module.ColorScheme.snapshot()
    yield module
    for role, color in original.items():
        setattr(module.ColorScheme, role, color)


def test_role_groups_and_defaults(palette):
    assert tuple(palette.ROLES_BASE) == ("TEXT", "LIGHT", "DARK", "LINE", "BTN")
    assert tuple(palette.ROLES_CURVE) == ("AXIS_X", "AXIS_Y", "AXIS_Z", "TEMP")
    assert tuple(palette.ROLES_DISPLAY) == ("GRID", "AXIS")
    assert tuple(palette.ROLES) == tuple(DEFAULTS)
    assert palette.ColorScheme.ROLES == tuple(DEFAULTS)
    assert palette.ColorScheme.snapshot() == DEFAULTS
    assert dict(palette.DEFAULT_COLORS) == DEFAULTS


def test_reset_restores_defaults_and_preserves_label_configuration(palette):
    assert palette.ColorScheme.LABEL_SIZE == 14
    assert palette.ColorScheme.AXIS_LABEL_SIZE == 13
    assert palette.ColorScheme.LABEL_ALPHA == "ff"
    for role in palette.ROLES:
        palette.ColorScheme.set_color(role, "#123")
    palette.ColorScheme.reset()
    assert palette.ColorScheme.snapshot() == DEFAULTS


@pytest.mark.parametrize("value,expected", [
    ("#abc", "#AABBCC"), ("#aBcDeF", "#ABCDEF"), ("#000", "#000000"),
])
def test_set_color_normalizes_hex(palette, value, expected):
    palette.ColorScheme.set_color("TEXT", value)
    assert palette.ColorScheme.TEXT == expected


@pytest.mark.parametrize("role", ["UNKNOWN", "LABEL_SIZE", "AXIS_LABEL_SIZE", "LABEL_ALPHA", "ROLES", "reset", "set_color", "snapshot", "__dict__", "get_stylesheet", None, 3])
def test_set_color_rejects_non_role_attributes(palette, role):
    before = palette.ColorScheme.snapshot()
    with pytest.raises(KeyError):
        palette.ColorScheme.set_color(role, "#fff")
    assert palette.ColorScheme.snapshot() == before


@pytest.mark.parametrize("value", ["fff", "#ff", "#ffff", "#12345678", "#ggg", "#123456\n", " #fff", "", None, 123])
def test_invalid_hex_rejected_without_changing_palette(palette, value):
    before = palette.ColorScheme.snapshot()
    with pytest.raises(ValueError):
        palette.ColorScheme.set_color("TEXT", value)
    with pytest.raises(ValueError):
        palette.ColorScheme.hex_to_rgba(value)
    with pytest.raises(ValueError):
        palette.ColorScheme.adjust(value, 0)
    assert palette.ColorScheme.snapshot() == before


@pytest.mark.parametrize("color,amount,expected", [
    ("#fff", 10, "#FFFFFF"), ("#000", -20, "#000000"),
    ("#01f0a0", 20, "#15FFB4"), ("#01f0a0", -20, "#00DC8C"),
])
def test_adjust_clamps_channels(palette, color, amount, expected):
    assert palette.ColorScheme.adjust(color, amount) == expected


def test_hex_to_rgba(palette):
    assert palette.ColorScheme.hex_to_rgba("#abc") == (170, 187, 204, 255)
    assert palette.ColorScheme.hex_to_rgba("#0123fF", 0) == (1, 35, 255, 0)
    assert palette.ColorScheme.hex_to_rgba("#0123fF", 128) == (1, 35, 255, 128)


@pytest.mark.parametrize("alpha", [-1, 256, 0.5, "128", None, True])
def test_hex_to_rgba_rejects_invalid_alpha(palette, alpha):
    with pytest.raises(ValueError):
        palette.ColorScheme.hex_to_rgba("#fff", alpha)


def test_snapshot_and_defaults_do_not_leak_mutable_state(palette):
    snapshot = palette.ColorScheme.snapshot()
    snapshot["TEXT"] = "#000000"
    assert palette.ColorScheme.TEXT == DEFAULTS["TEXT"]
    with pytest.raises(TypeError):
        palette.DEFAULT_COLORS["TEXT"] = "#000000"
    palette.ColorScheme.set_color("TEXT", "#fff")
    assert palette.DEFAULT_COLORS["TEXT"] == DEFAULTS["TEXT"]


@pytest.mark.parametrize("role", ["TEXT", "LIGHT", "DARK", "LINE", "BTN"])
def test_stylesheet_reads_current_class_attributes(palette, role):
    before = palette.ColorScheme.get_stylesheet()
    palette.ColorScheme.set_color(role, "#123456")
    after = palette.ColorScheme.get_stylesheet()
    assert after != before
    assert "#123456" in after


def test_stylesheet_covers_widget_states_and_fonts(palette):
    stylesheet = palette.ColorScheme.get_stylesheet()
    for selector in [
        "QWidget", "QMainWindow", "QGroupBox", "QLabel", "QPushButton:hover",
        "QPushButton:pressed", "QPushButton:disabled", "QLineEdit", "QComboBox",
        "QSpinBox", "QSplitter", "QPlainTextEdit", "QStatusBar", "QScrollBar",
    ]:
        assert selector in stylesheet
    assert '"Segoe UI"' in stylesheet
    assert '"Microsoft YaHei"' in stylesheet
    assert "13px" in stylesheet


def test_import_does_not_load_qt(palette):
    result = subprocess.run(
        [sys.executable, "-c", (
            "import sys; import tmag_viewer.color_scheme; "
            "assert not any(name.startswith(('PyQt', 'PySide')) for name in sys.modules)"
        )], capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
