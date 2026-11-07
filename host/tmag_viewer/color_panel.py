"""Compact live palette editor. Native pickers open only on explicit clicks."""
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QLineEdit, QPushButton, QColorDialog)
from .color_scheme import ColorScheme


class ColorPanel(QWidget):
    color_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(170)
        self.edits, self.swatches = {}, {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(5)
        for title, roles in (("基础颜色", ColorScheme.ROLES[:5]),
                             ("曲线颜色", ColorScheme.ROLES[5:9]),
                             ("坐标与网格", ColorScheme.ROLES[9:])):
            layout.addWidget(QLabel(title))
            for role in roles:
                row = QHBoxLayout()
                row.setSpacing(3)
                swatch = QPushButton()
                swatch.setFixedSize(16, 24)
                swatch.setToolTip("选择颜色")
                label = QLabel(role)
                label.setFixedWidth(45)
                label.setStyleSheet('font-size: 10px;')
                edit = QLineEdit()
                edit.setFixedWidth(84)
                edit.setStyleSheet('font-size: 11px; padding: 3px;')
                edit.editingFinished.connect(lambda r=role: self.commit(r))
                swatch.clicked.connect(lambda checked=False, r=role: self.pick(r))
                self.edits[role], self.swatches[role] = edit, swatch
                row.addWidget(swatch)
                row.addWidget(label)
                row.addWidget(edit)
                layout.addLayout(row)
        self.reset_button = QPushButton("恢复默认颜色")
        self.reset_button.clicked.connect(self.reset)
        layout.addWidget(self.reset_button)
        layout.addStretch()
        self.refresh()

    def refresh(self):
        for role, edit in self.edits.items():
            edit.setText(getattr(ColorScheme, role))
            edit.setStyleSheet('font-size: 11px; padding: 3px;')
            edit.setToolTip('#RGB 或 #RRGGBB')
            self.swatches[role].setStyleSheet(
                'padding: 0px; background: %s;' % getattr(ColorScheme, role))

    def commit(self, role):
        try:
            ColorScheme.set_color(role, self.edits[role].text().strip())
        except ValueError:
            self.edits[role].setStyleSheet('font-size: 11px; padding: 3px; border: 1px solid #f7768e;')
            self.edits[role].setToolTip('无效颜色，请输入 #RGB 或 #RRGGBB')
            return
        self.refresh()
        self.color_changed.emit(role)

    def pick(self, role):
        color = QColorDialog.getColor(QColor(getattr(ColorScheme, role)), self, "选择颜色")
        if color.isValid():
            self.edits[role].setText(color.name())
            self.commit(role)

    def reset(self):
        ColorScheme.reset()
        self.refresh()
        self.color_changed.emit('*')
