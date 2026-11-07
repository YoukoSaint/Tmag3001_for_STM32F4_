"""Real Qt plots, with the shared process-only offscreen application."""
import importlib.util

import numpy as np
import pytest
from PyQt5.QtWidgets import QWidget

from tmag_viewer.color_scheme import ColorScheme


def test_module_exists():
    assert importlib.util.find_spec('tmag_viewer.plot_widgets') is not None


@pytest.fixture
def widget(qapp):
    from tmag_viewer.plot_widgets import MagPlotWidget
    result = MagPlotWidget(max_points=10)
    yield result
    result.close()
    result.deleteLater()
    qapp.processEvents()


def test_buffered_refresh_and_clean_noop(widget, monkeypatch):
    assert isinstance(widget, QWidget)
    calls = []
    for curve in widget.curves:
        original = curve.setData
        def record(*args, _original=original, **kwargs):
            calls.append(1)
            return _original(*args, **kwargs)
        monkeypatch.setattr(curve, 'setData', record)
    widget.push_sample(1.5, -2.5, 3.5, 24)
    widget.push_sample(2.5, -3.5, 4.5, 25)
    assert not calls
    assert widget.refresh() is True
    assert len(calls) == 4
    for curve, expected in zip(widget.curves, ([1.5, 2.5], [-2.5, -3.5], [3.5, 4.5], [24, 25])):
        x, y = curve.getData()
        np.testing.assert_array_equal(x, [0, 1])
        np.testing.assert_array_equal(y, expected)
    assert widget.refresh() is False
    assert len(calls) == 4


def test_labels_and_link(widget):
    assert widget.temp_plot.getViewBox().linkedView(0) is widget.mag_plot.getViewBox()
    for plot, unit in ((widget.mag_plot, 'mT'), (widget.temp_plot, '°C')):
        assert unit in plot.getAxis('left').label.toPlainText()
        assert 'Sample index' in plot.getAxis('bottom').label.toPlainText()
        assert not plot.getAxis('left').autoSIPrefix
    assert [c.name() for c in widget.curves] == ['X', 'Y', 'Z', 'Temperature']


def test_offscreen_render_and_default_capacity(qapp):
    from tmag_viewer.plot_widgets import MagPlotWidget
    assert qapp.platformName() == 'offscreen'
    result = MagPlotWidget()
    try:
        assert result.samples.maxlen == 2000
        result.resize(900, 600)
        for i in range(50):
            result.push_sample(i / 10, -i / 10, i / 20, 25)
        result.refresh()
        result.layout().activate()
        qapp.processEvents()
        image = result.grab().toImage()
        assert not image.isNull()
        assert image.width() == 900
        assert image.height() == 600
        assert not result.isVisible()
    finally:
        result.close()
        result.deleteLater()


@pytest.mark.parametrize('size', [1, 9, False, 10.0])
def test_constructor_rejects_invalid_capacity(qapp, size):
    from tmag_viewer.plot_widgets import MagPlotWidget
    with pytest.raises(ValueError):
        MagPlotWidget(max_points=size)


def test_rollover_resize_and_clear(widget):
    for i in range(25):
        widget.push_sample(i, i + 1, i + 2, i + 3)
    widget.refresh()
    np.testing.assert_array_equal(widget.curves[0].getData()[0], np.arange(15, 25))
    widget.set_max_points(12)
    for i in range(25, 30):
        widget.push_sample(i, i + 1, i + 2, i + 3)
    widget.set_max_points(10)
    widget.refresh()
    np.testing.assert_array_equal(widget.curves[0].getData()[1], np.arange(20, 30))
    assert len(widget.samples) == widget.samples.maxlen == 10
    widget.clear()
    assert not widget.samples
    for curve in widget.curves:
        x, y = curve.getData()
        assert x is None or len(x) == 0
        assert y is None or len(y) == 0
    assert widget.refresh() is False
    widget.push_sample(9, 8, 7, 6)
    widget.refresh()
    np.testing.assert_array_equal(widget.curves[0].getData()[0], [0])


@pytest.mark.parametrize('size', [0, -1, 9, 10.5, True, '20', None])
def test_invalid_capacity_is_atomic(widget, size):
    widget.push_sample(1, 2, 3, 4)
    with pytest.raises(ValueError):
        widget.set_max_points(size)
    assert len(widget.samples) == 1
    assert widget.samples.maxlen == 10


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), -float('inf'), 'bad', None, True])
def test_invalid_sample_is_atomic(widget, bad):
    with pytest.raises(ValueError):
        widget.push_sample(1, 2, bad, 4)
    assert not widget.samples
    widget.push_sample(1, 2, 3, 4)
    widget.refresh()
    np.testing.assert_array_equal(widget.curves[0].getData()[0], [0])


def test_live_theme(widget):
    saved = ColorScheme.snapshot()
    try:
        changes = dict(DARK='#112233', TEXT='#445566', AXIS='#778899', GRID='#123456',
                       AXIS_X='#234567', AXIS_Y='#345678', AXIS_Z='#456789', TEMP='#56789A')
        for role, value in changes.items():
            ColorScheme.set_color(role, value)
        widget.apply_theme()
        assert widget.graphics.backgroundBrush().color().name() == changes['DARK'].lower()
        for curve, role in zip(widget.curves, ('AXIS_X', 'AXIS_Y', 'AXIS_Z', 'TEMP')):
            assert curve.opts['pen'].color().name() == changes[role].lower()
        for plot in (widget.mag_plot, widget.temp_plot):
            for name in ('left', 'bottom'):
                axis = plot.getAxis(name)
                assert axis.pen().color().name() == changes['AXIS'].lower()
                assert axis.textPen().color().name() == changes['TEXT'].lower()
                assert axis.tickPen().color().name() == changes['GRID'].lower()
                assert axis.grid is not False
                assert changes['TEXT'].lower() in axis.label.toHtml().lower()
            assert changes['TEXT'].lower() in plot.titleLabel.item.toHtml().lower()
            for _, label in plot.legend.items:
                assert changes['TEXT'].lower() in label.item.toHtml().lower()
    finally:
        for role, value in saved.items():
            ColorScheme.set_color(role, value)
        widget.apply_theme()
