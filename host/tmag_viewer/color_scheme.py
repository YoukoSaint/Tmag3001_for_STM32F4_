"""Shared palette and dynamic QSS generation, independent of Qt imports.

Class attributes are the live palette. DEFAULT_COLORS is a read-only startup
snapshot for restoring defaults; consumers should read ColorScheme for changes.
"""

from __future__ import annotations

import re
from types import MappingProxyType


ROLES_BASE = ("TEXT", "LIGHT", "DARK", "LINE", "BTN")
ROLES_CURVE = ("AXIS_X", "AXIS_Y", "AXIS_Z", "TEMP")
ROLES_DISPLAY = ("GRID", "AXIS")
ROLES = ROLES_BASE + ROLES_CURVE + ROLES_DISPLAY
_HEX_PATTERN = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})")


def _normalize_hex(hex_color: str) -> str:
    if not isinstance(hex_color, str) or not _HEX_PATTERN.fullmatch(hex_color):
        raise ValueError("Color must be #RGB or #RRGGBB hexadecimal")
    digits = hex_color[1:]
    if len(digits) == 3:
        digits = "".join(channel * 2 for channel in digits)
    return "#" + digits.upper()


class ColorScheme:
    """Single source of truth for the application and plot colors."""

    ROLES = ROLES
    LABEL_SIZE = 14
    AXIS_LABEL_SIZE = 13
    LABEL_ALPHA = "ff"

    TEXT = "#c0caf5"
    LIGHT = "#1e1f2e"
    DARK = "#1a1b26"
    LINE = "#3b3d56"
    BTN = "#3b3d56"
    AXIS_X = "#f7768e"
    AXIS_Y = "#9ece6a"
    AXIS_Z = "#7aa2f7"
    TEMP = "#e0af68"
    GRID = "#2c2d3f"
    AXIS = "#565f89"

    @classmethod
    def set_color(cls, role: str, hex_color: str) -> None:
        """Set a whitelisted role; reject invalid settings before mutation."""
        if role not in ROLES:
            raise KeyError(role)
        setattr(cls, role, _normalize_hex(hex_color))

    @staticmethod
    def hex_to_rgba(hex_color: str, alpha: int = 255) -> tuple[int, int, int, int]:
        """Convert #RGB or #RRGGBB with an integer alpha in 0..255."""
        color = _normalize_hex(hex_color)
        if type(alpha) is not int or not 0 <= alpha <= 255:
            raise ValueError("Alpha must be an integer from 0 to 255")
        return (int(color[1:3], 16), int(color[3:5], 16),
                int(color[5:7], 16), alpha)

    @staticmethod
    def adjust(hex_color: str, amount: int) -> str:
        """Add an integer offset to RGB channels, clamping at their limits."""
        rgb = ColorScheme.hex_to_rgba(hex_color)[:3]
        if type(amount) is not int:
            raise ValueError("Adjustment must be an integer")
        return "#" + "".join(f"{max(0, min(255, channel + amount)):02X}"
                             for channel in rgb)

    @classmethod
    def snapshot(cls) -> dict[str, str]:
        """Return an independent copy of all live color roles."""
        return {role: getattr(cls, role) for role in ROLES}

    @classmethod
    def reset(cls) -> None:
        """Restore startup color defaults without changing label settings."""
        for role, color in DEFAULT_COLORS.items():
            setattr(cls, role, color)

    @classmethod
    def get_stylesheet(cls) -> str:
        """Build fresh QSS for application-wide use by QApplication."""
        text, light, dark, line, btn = (
            cls.TEXT, cls.LIGHT, cls.DARK, cls.LINE, cls.BTN
        )
        text2 = cls.adjust(text, -30)
        text3 = cls.adjust(text, -50)
        dark2 = cls.adjust(dark, -6)
        accent = cls.adjust(light, 30)
        btn_hover = cls.adjust(btn, 10)
        return f"""
QWidget {{
    background-color: {dark}; color: {text};
    font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
    font-size: 13px;
}}
QMainWindow {{ background-color: {dark2}; }}
QLabel {{ background-color: transparent; color: {text2}; border: none; }}
QGroupBox {{
    background-color: {light}; border: 1px solid {line};
    border-radius: 8px; margin-top: 16px;
    padding: 16px 12px 12px 12px;
    font-weight: bold; color: {accent};
}}
QGroupBox::title {{
    subcontrol-origin: margin; subcontrol-position: top left;
    left: 14px; top: 2px; padding: 2px 8px;
    background-color: {light}; border-radius: 4px; color: {accent};
}}
QPushButton {{
    background-color: {btn}; color: {text}; border: 1px solid {btn};
    border-radius: 6px; padding: 7px 16px; font-weight: bold;
}}
QPushButton:hover {{ background-color: {btn_hover}; border-color: {accent}; }}
QPushButton:pressed {{ background-color: {dark}; }}
QPushButton:disabled {{ background-color: {light}; color: {text3}; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background-color: {dark2}; color: {text}; border: 1px solid {line};
    border-radius: 5px; padding: 5px 8px;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {accent};
}}
QComboBox QAbstractItemView {{
    background-color: {light}; color: {text}; border: 1px solid {line};
    border-radius: 4px; selection-background-color: {accent}; outline: none;
}}
QSplitter::handle {{ background-color: {line}; margin: 1px; }}
QSplitter::handle:horizontal {{ width: 3px; }}
QSplitter::handle:vertical {{ height: 3px; }}
QSplitter::handle:hover {{ background-color: {accent}; }}
QPlainTextEdit {{
    background-color: {dark2}; color: {text2}; border: 1px solid {line};
    border-radius: 6px; padding: 8px;
    font-family: "Consolas", "Courier New", monospace; font-size: 12px;
}}
QStatusBar {{
    background-color: {dark2}; color: {text2};
    border-top: 1px solid {line}; padding: 2px 8px; font-size: 12px;
}}
QScrollBar:vertical {{ background-color: {dark2}; width: 10px; border-radius: 5px; }}
QScrollBar::handle:vertical {{
    background-color: {line}; border-radius: 5px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background-color: {accent}; }}
QScrollBar:horizontal {{ background-color: {dark2}; height: 10px; border-radius: 5px; }}
QScrollBar::handle:horizontal {{
    background-color: {line}; border-radius: 5px; min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{ background-color: {accent}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: none; }}
"""


DEFAULT_COLORS = MappingProxyType(ColorScheme.snapshot())
