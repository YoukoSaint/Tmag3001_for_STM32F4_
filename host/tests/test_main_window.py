from dataclasses import replace
import csv
import logging
from pathlib import Path

import pytest
from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtGui import QCloseEvent
from tmag_viewer import settings_manager
from tmag_viewer.main_window import MainWindow
from tmag_viewer.protocol import Frame


class FakeSource(QObject):
    sample_received = pyqtSignal(object)
    status_received = pyqtSignal(object)
    error_received = pyqtSignal(object)
    transport_error = pyqtSignal(str)
    metadata_invalidated = pyqtSignal(str)
    stats_updated = pyqtSignal(dict)
    connection_changed = pyqtSignal(bool)
    stats = dict(queue_depth=3, queue_capacity=4096, rate_hz=92.0, dropped_frames=7,
                 queue_dropped=2, skipped_bytes=31, errors=1)
    def __init__(self):
        super().__init__()
        self.fail_close = False
        self.fail_open = False
    def open(self, port, baud):
        self.connection_changed.emit(not self.fail_open)
        return not self.fail_open
    def close(self):
        if self.fail_close:
            raise RuntimeError('reader timeout')
        self.connection_changed.emit(False)


@pytest.fixture
def window(qapp, monkeypatch, request):
    directory = Path(__file__).resolve().parents[2] / 'build' / 'host-ui' / request.node.name
    directory.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings_manager, 'get_settings_path', lambda: directory / 'settings.json')
    monkeypatch.setattr('tmag_viewer.main_window.list_ports.comports', lambda: [])
    source = FakeSource()
    win = MainWindow(source)
    yield win
    source.fail_close = False
    win.close()
    qapp.processEvents()


def ready(sensitivity=500, **changes):
    return replace(Frame('status', 1, version=0x12, flags=0x4c, sensitivity=sensitivity,
                         sample_rate_hz=100, conv_status=1), **changes)


def sample(x=1000):
    return Frame('data', 2, x_raw=x, y_raw=-1000, z_raw=500, temp_raw=17512)


def test_wait_status_and_received_scaling(window):
    window.on_sample(sample())
    assert not window.plot.samples
    window.source.connection_changed.emit(True)
    window.on_sample(sample())
    assert not window.plot.samples
    window.on_status(ready())
    window.on_sample(sample())
    assert tuple(window.plot.samples[-1])[1:] == (2., -2., 1., 25.)
    window.on_status(ready(250, range_code=1))
    window.on_sample(sample())
    assert window.plot.samples[-1][1] == 4


@pytest.mark.parametrize('changes', [dict(flags=0), dict(version=0x11), dict(sensitivity=0),
    dict(conv_status=3), dict(device_status=0x14), dict(device_status=6), dict(range_code=7)])
def test_fault_gates_and_status_recovery(window, changes):
    window.on_connection(True)
    window.on_status(ready())
    window.on_status(ready(**changes))
    window.on_sample(sample())
    assert not window.plot.samples
    assert window.metadata is None
    window.on_status(ready())
    window.on_sample(sample())
    assert len(window.plot.samples) == 1


def test_invalidation_disconnect_and_normal_bits(window):
    window.on_connection(True)
    window.on_status(ready(device_status=0x11))
    window.on_sample(sample())
    assert len(window.plot.samples) == 1
    window.source.metadata_invalidated.emit('queue overflow')
    window.on_sample(sample())
    assert len(window.plot.samples) == 1
    window.on_status(ready())
    window.on_connection(False)
    window.on_sample(sample())
    assert len(window.plot.samples) == 1


def test_csv_raw_while_display_filtered(window, monkeypatch):
    path = settings_manager.get_settings_path().with_suffix('.csv')
    monkeypatch.setattr('tmag_viewer.main_window.QFileDialog.getSaveFileName', lambda *a: (str(path), 'CSV'))
    window.on_connection(True)
    window.on_status(ready())
    window.kalman_check.setChecked(True)
    window.toggle_csv()
    window.on_sample(sample(0))
    window.on_sample(sample(2000))
    assert 0 < window.plot.samples[-1][1] < 4
    window.invalidate_metadata('fault')
    assert window.csv_button.isEnabled()
    window.on_sample(sample(3000))
    window.toggle_csv()
    with path.open() as stream:
        rows = list(csv.reader(stream))
    assert len(rows) == 3 and rows[2][0] == '4.0000'
    window.clear()
    assert not window.plot.samples and window._filter is None


def test_stats_and_dedup_health(window, qapp, caplog):
    caplog.set_level(logging.INFO)
    window.on_connection(True)
    window.on_status(ready())
    window.on_stats(dict(window.source.stats, last_seq=77))
    assert '丢帧 7' in window.status_label.text()
    assert '31' not in window.status_label.text()
    for _ in range(100):
        window.on_error(Frame('error', 3, err_code=7, err_name='SENSOR_DIAG'))
    qapp.processEvents()
    assert sum('传感器错误' in r.message for r in caplog.records) == 1
    window.report_health()
    assert 'queue=3/4096' in caplog.text and 'skipped_bytes=31' in caplog.text
    assert 'dropped_frames=7' in caplog.text and 'rss_mib=' in caplog.text
    for n in range(550):
        window.log_panel.appendPlainText(str(n))
    assert window.log_panel.document().blockCount() == 500


def test_shutdown_timeout_keeps_handlers_timers(window):
    window.source.fail_close = True
    event = QCloseEvent()
    window.closeEvent(event)
    assert not event.isAccepted()
    assert window.refresh_timer.isActive()
    assert window._ui_handler in logging.getLogger().handlers
    window.source.fail_close = False
    window.closeEvent(event)
    assert event.isAccepted()
    assert window._ui_handler not in logging.getLogger().handlers
    assert not window.refresh_timer.isActive()


def test_failed_connect_and_reconnect(window):
    window.source.fail_open = True
    window.toggle_connection()
    assert window.connect_button.text() == '连接'
    window.source.fail_open = False
    window.toggle_connection()
    assert window.connect_button.text() == '断开'
    window.toggle_connection()
    assert window.connect_button.text() == '连接'


def test_theme_persistence_and_fullscreen(window, qapp):
    from tmag_viewer.color_scheme import ColorScheme
    window.color_panel.edits['TEXT'].setText('#abc')
    window.color_panel.commit('TEXT')
    assert '#AABBCC' in qapp.styleSheet()
    assert window.plot.mag_plot.getAxis('left').textPen().color().name() == '#aabbcc'
    window.color_toggle.setChecked(False)
    window.log_toggle.setChecked(False)
    window.baud_combo.setCurrentText('921600')
    window.persist_settings()
    saved = settings_manager.load_settings()
    assert saved['colors']['TEXT'] == '#AABBCC'
    assert saved['panels']['right'] is False and saved['panels']['log'] is False
    assert saved['acquisition']['baud'] == 921600
    window.toggle_fullscreen()
    assert window.isFullScreen()
    window.showNormal()
    assert not window.isFullScreen()
    ColorScheme.reset()


def test_csv_failures_nonmodal(window, monkeypatch, caplog):
    monkeypatch.setattr('tmag_viewer.main_window.QFileDialog.getSaveFileName', lambda *a: ('missing/never/out.csv', ''))
    window.on_connection(True)
    window.on_status(ready())
    window.toggle_csv()
    assert window.csv_writer is None
    assert 'CSV 保存失败' in window.status_label.text()
    assert 'CSV 保存失败' in caplog.text

@pytest.mark.parametrize('changes', [dict(flags=None), dict(sensitivity=True),
    dict(sample_rate_hz=0), dict(conv_status='bad'), dict(device_status=-1)])
def test_malformed_status_fails_closed(window, changes):
    window.on_connection(True)
    window.on_status(ready(**changes))
    window.on_sample(sample())
    assert not window.plot.samples
    assert window.metadata is None


def test_picker_disconnect_during_nested_events(window, monkeypatch):
    def choose(*args):
        window.on_connection(False)
        return ('should-never-be-created.csv', '')
    monkeypatch.setattr('tmag_viewer.main_window.QFileDialog.getSaveFileName', choose)
    window.on_connection(True)
    window.on_status(ready())
    window.toggle_csv()
    assert window.csv_writer is None


def test_csv_write_failure_stops_recording(window, caplog):
    class BrokenWriter:
        aborted = False
        def write(self, *values):
            raise OSError('disk full')
        def abort(self):
            self.aborted = True
    broken = BrokenWriter()
    window.on_connection(True)
    window.on_status(ready())
    window.csv_writer = broken
    window.on_sample(sample())
    assert broken.aborted and window.csv_writer is None
    assert len(window.plot.samples) == 1
    assert 'disk full' in caplog.text


def test_filter_reset_on_range_change_and_health_nonblocking(window, caplog):
    class Process:
        def cpu_percent(self, interval):
            assert interval is None
            return 12.3
        def memory_info(self):
            return type('Memory', (), dict(rss=10*1024**2))()
        def num_threads(self):
            return 4
    caplog.set_level(logging.INFO)
    window._process = Process()
    window.report_health()
    assert 'cpu=12.3%' in caplog.text and 'threads=4' in caplog.text
    window.on_connection(True)
    window.on_status(ready())
    window.kalman_check.setChecked(True)
    window.on_sample(sample(0))
    window.on_sample(sample(2000))
    window.on_status(ready(250, range_code=1))
    window.on_sample(sample(2000))
    assert window.plot.samples[-1][1] == 8.0
