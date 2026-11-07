"""Bounded engineering-value plots; the UI refresh timer calls refresh()."""
from __future__ import annotations

from collections import deque
import math
from numbers import Real

import numpy as np
import pyqtgraph as pg
from PyQt5.QtWidgets import QVBoxLayout, QWidget

from .color_scheme import ColorScheme


class MagPlotWidget(QWidget):
    """Three magnetic channels in mT and temperature in degrees Celsius.

    Call from the GUI thread. push_sample only appends a bounded record; an
    external UI timer calls refresh to coalesce incoming samples into frames.
    The horizontal coordinate is a monotonic sample index, not elapsed time.
    """

    def __init__(self, parent=None, max_points: int = 2000):
        self._validate_capacity(max_points)
        super().__init__(parent)
        self.samples = deque(maxlen=max_points)
        self._next_index = 0
        self._dirty = False
        self.graphics = pg.GraphicsLayoutWidget()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.graphics)
        self.mag_plot = self.graphics.addPlot(row=0, col=0)
        self.temp_plot = self.graphics.addPlot(row=1, col=0)
        self.temp_plot.setXLink(self.mag_plot)
        for plot in (self.mag_plot, self.temp_plot):
            plot.addLegend()
            plot.showGrid(x=True, y=True, alpha=0.5)
            plot.getAxis('left').enableAutoSIPrefix(False)
            plot.getAxis('bottom').enableAutoSIPrefix(False)
        self.curves = tuple(self.mag_plot.plot(name=name) for name in ('X', 'Y', 'Z'))
        self.curves += (self.temp_plot.plot(name='Temperature'),)
        self.apply_theme()

    @staticmethod
    def _validate_capacity(n: int) -> None:
        if type(n) is not int or n < 10:
            raise ValueError('max_points must be an integer of at least 10')

    def set_max_points(self, n: int) -> None:
        """Keep the newest n samples and preserve their original indices."""
        self._validate_capacity(n)
        if n != self.samples.maxlen:
            self.samples = deque(self.samples, maxlen=n)
            self._dirty = True

    def push_sample(self, x_mt: float, y_mt: float, z_mt: float, temp_c: float) -> None:
        """Append finite numeric engineering values atomically, without drawing."""
        values = (x_mt, y_mt, z_mt, temp_c)
        if any(isinstance(value, bool) or not isinstance(value, Real)
               or not math.isfinite(value) for value in values):
            raise ValueError('Samples must contain four finite real numbers')
        self.samples.append((self._next_index, *values))
        self._next_index += 1
        self._dirty = True

    def refresh(self) -> bool:
        """Render at most once per dirty batch; return whether data changed."""
        if not self._dirty:
            return False
        if self.samples:
            data = np.asarray(self.samples, dtype=float)
            for column, curve in enumerate(self.curves, start=1):
                curve.setData(data[:, 0], data[:, column])
        else:
            for curve in self.curves:
                curve.clear()
        self._dirty = False
        return True

    def clear(self) -> None:
        """Empty buffered and displayed data, restarting the sample index."""
        self.samples.clear()
        self._next_index = 0
        for curve in self.curves:
            curve.clear()
        self._dirty = False

    def apply_theme(self) -> None:
        """Read the current palette on every call, including grid tick pens."""
        cs = ColorScheme
        self.graphics.setBackground(cs.hex_to_rgba(cs.DARK))
        for curve, role in zip(self.curves, ('AXIS_X', 'AXIS_Y', 'AXIS_Z', 'TEMP')):
            curve.setPen(pg.mkPen(cs.hex_to_rgba(getattr(cs, role)), width=2))
        for plot, title, ylabel in (
            (self.mag_plot, 'Magnetic field', 'Magnetic field (mT)'),
            (self.temp_plot, 'Temperature', 'Temperature (°C)'),
        ):
            plot.setTitle(title, color=cs.TEXT, size=f'{cs.LABEL_SIZE}pt')
            for name, label in (('left', ylabel), ('bottom', 'Sample index (samples)')):
                axis = plot.getAxis(name)
                axis.setLabel(label, color=cs.TEXT, **{'font-size': f'{cs.AXIS_LABEL_SIZE}pt'})
                axis.setPen(pg.mkPen(cs.hex_to_rgba(cs.AXIS)))
                axis.setTextPen(pg.mkPen(cs.hex_to_rgba(cs.TEXT)))
                # pyqtgraph's grid extends its ticks through the view. Their
                # dedicated pen drives GRID while the baseline keeps AXIS.
                axis.setTickPen(pg.mkPen(cs.hex_to_rgba(cs.GRID)))
            plot.legend.setLabelTextColor(cs.TEXT)
            plot.legend.setLabelTextSize(f'{cs.LABEL_SIZE}pt')
            # In pyqtgraph 0.13.7 the legend setters change defaults only;
            # rebuild existing label HTML so a live theme change is visible.
            for _, label in plot.legend.items:
                label.setText(label.text)
            plot.legend.setBrush(pg.mkBrush(cs.hex_to_rgba(cs.DARK)))
            plot.legend.setPen(pg.mkPen(cs.hex_to_rgba(cs.LINE)))
