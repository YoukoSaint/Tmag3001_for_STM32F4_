from PyQt5.QtGui import QColor
from tmag_viewer.color_panel import ColorPanel
from tmag_viewer.color_scheme import ColorScheme, DEFAULT_COLORS


def test_hex_picker_reset(qapp, monkeypatch):
    ColorScheme.reset()
    panel = ColorPanel()
    assert len(panel.edits) == 11
    events = []
    panel.color_changed.connect(events.append)
    panel.edits['AXIS_X'].setText('bad')
    panel.commit('AXIS_X')
    assert '无效' in panel.edits['AXIS_X'].toolTip()
    assert not events
    panel.edits['AXIS_X'].setText('#abc')
    panel.commit('AXIS_X')
    assert ColorScheme.AXIS_X == '#AABBCC'
    monkeypatch.setattr('tmag_viewer.color_panel.QColorDialog.getColor', lambda *a: QColor('#123456'))
    panel.pick('AXIS_Y')
    assert ColorScheme.AXIS_Y == '#123456'
    panel.reset()
    assert events == ['AXIS_X', 'AXIS_Y', '*']
    assert ColorScheme.snapshot() == dict(DEFAULT_COLORS)
