"""Desktop assembly with status-gated engineering conversion and bounded logging."""
from __future__ import annotations
import logging
import time

import psutil
from serial.tools import list_ports
from PyQt5.QtCore import QObject, QTimer, Qt, pyqtSignal
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QPushButton, QComboBox,
                             QCheckBox, QPlainTextEdit, QFileDialog, QShortcut)
from PyQt5.QtGui import QKeySequence
from . import settings_manager as settings
from .color_scheme import ColorScheme
from .color_panel import ColorPanel
from .plot_widgets import MagPlotWidget
from .serial_source import SerialSource
from .csv_writer import CsvWriter
from .protocol import ERR_NONE, Frame, PROTO_VERSION, to_celsius

logger = logging.getLogger(__name__)


class _LogBridge(QObject):
    line = pyqtSignal(str)


class _UiHandler(logging.Handler):
    def __init__(self, bridge):
        super().__init__(logging.INFO)
        self.bridge = bridge
        self.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s', '%H:%M:%S'))

    def emit(self, record):
        try:
            self.bridge.line.emit(self.format(record))
        except RuntimeError:
            # The handler is detached before QObject destruction on normal close.
            self.handleError(record)


class MainWindow(QMainWindow):
    def __init__(self, source=None):
        super().__init__()
        self.setWindowTitle('TMAG3001 · 磁场与温度')
        self.resize(1440, 920)
        self.setMinimumSize(1100, 700)
        self.preferences = settings.load_settings()
        for role in ColorScheme.ROLES:
            ColorScheme.set_color(role, self.preferences['colors'][role])
        self.source = source if source is not None else SerialSource(self)
        self.connected = False
        self.metadata = None
        self.csv_writer = None
        self._filter = None
        self._hsi_warned = self._int_warned = False
        self._error_log_started = float('-inf')
        self._error_log_keys = set()
        self._error_log_suppressed = 0
        self._started = time.monotonic()
        self._process = psutil.Process()
        self._process.cpu_percent(None)
        self._last_rss = self._process.memory_info().rss / (1024 ** 2)
        self._stats = {}
        self._closed = False
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        controls = QHBoxLayout()
        self.port_combo = QComboBox()
        self.port_combo.setEditable(True)
        self.port_combo.setMinimumWidth(140)
        self.refresh_button = QPushButton('刷新')
        self.connect_button = QPushButton('连接')
        self.baud_combo = QComboBox()
        baud = str(self.preferences['acquisition']['baud'])
        self.baud_combo.addItems(list(dict.fromkeys(['115200', '921600', baud])))
        self.baud_combo.setCurrentText(baud)
        self.rate_label = QLabel('配置 — Hz / 实际 — Hz')
        self.csv_button = QPushButton('保存 CSV')
        self.clear_button = QPushButton('清空')
        self.kalman_check = QCheckBox('Kalman 平滑')
        self.kalman_check.setChecked(self.preferences['acquisition']['kalman'])
        self.kalman_check.setToolTip('仅平滑 XYZ 显示；CSV 始终记录未滤波工程值。非传感器校准。')
        for widget in (QLabel('串口'), self.port_combo, self.refresh_button,
                       self.baud_combo, self.connect_button, self.rate_label,
                       self.csv_button, self.clear_button, self.kalman_check):
            controls.addWidget(widget)
        layout.addLayout(controls)
        toggles = QHBoxLayout()
        self.color_toggle = QCheckBox('颜色面板')
        self.log_toggle = QCheckBox('运行日志')
        self.color_toggle.setChecked(self.preferences['panels']['right'])
        self.log_toggle.setChecked(self.preferences['panels']['log'])
        toggles.addStretch()
        toggles.addWidget(self.color_toggle)
        toggles.addWidget(self.log_toggle)
        layout.addLayout(toggles)
        content = QHBoxLayout()
        self.plot = MagPlotWidget()
        self.color_panel = ColorPanel()
        content.addWidget(self.plot, 1)
        content.addWidget(self.color_panel)
        layout.addLayout(content, 1)
        self.log_panel = QPlainTextEdit()
        self.log_panel.setReadOnly(True)
        self.log_panel.setMaximumBlockCount(500)
        self.log_panel.setFixedHeight(150)
        layout.addWidget(self.log_panel)
        self.color_panel.setVisible(self.color_toggle.isChecked())
        self.log_panel.setVisible(self.log_toggle.isChecked())
        self.status_label = QLabel('未连接 · 等待有效状态')
        self.statusBar().addWidget(self.status_label, 1)
        self._bridge = _LogBridge(self)
        self._bridge.line.connect(self.log_panel.appendPlainText, Qt.QueuedConnection)
        self._ui_handler = _UiHandler(self._bridge)
        logging.getLogger().addHandler(self._ui_handler)
        self.refresh_button.clicked.connect(self.refresh_ports)
        self.connect_button.clicked.connect(self.toggle_connection)
        self.csv_button.clicked.connect(self.toggle_csv)
        self.clear_button.clicked.connect(self.clear)
        self.kalman_check.toggled.connect(self._reset_filter)
        self.color_toggle.toggled.connect(self.color_panel.setVisible)
        self.log_toggle.toggled.connect(self.log_panel.setVisible)
        self.color_panel.color_changed.connect(self.apply_theme)
        self.source.connection_changed.connect(self.on_connection)
        self.source.status_received.connect(self.on_status)
        self.source.sample_received.connect(self.on_sample)
        self.source.error_received.connect(self.on_error)
        self.source.metadata_invalidated.connect(self.invalidate_metadata)
        self.source.transport_error.connect(self.on_transport_error)
        self.source.stats_updated.connect(self.on_stats)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(33)
        self.refresh_timer.timeout.connect(self.plot.refresh)
        self.refresh_timer.start()
        self.health_timer = QTimer(self)
        self.health_timer.setInterval(30000)
        self.health_timer.timeout.connect(self.report_health)
        self.health_timer.start()
        self._fullscreen_shortcut = QShortcut(QKeySequence('F10'), self, activated=self.toggle_fullscreen)
        self._escape_shortcut = QShortcut(QKeySequence('Escape'), self, activated=self.showNormal)
        self.refresh_ports()
        self.port_combo.setCurrentText(self.preferences['acquisition']['port'])
        self.apply_theme(persist=False)
        self._update_buttons()

    def refresh_ports(self):
        previous = self.port_combo.currentText()
        try:
            ports = [port.device for port in list_ports.comports()]
        except Exception:
            logger.exception('串口列表读取失败')
            return
        self.port_combo.clear()
        self.port_combo.addItems(ports)
        self.port_combo.setCurrentText(previous)

    def _reset_filter(self, *_):
        self._filter = None

    def clear(self):
        self.plot.clear()
        self._reset_filter()

    def toggle_fullscreen(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def toggle_connection(self):
        try:
            if self.connected:
                self.source.close()
            else:
                self.source.open(self.port_combo.currentText().strip(), int(self.baud_combo.currentText()))
        except Exception as exc:
            self.on_transport_error(str(exc))
        self._update_buttons()

    def on_connection(self, connected):
        self.connected = connected
        self.invalidate_metadata('等待有效状态' if connected else '未连接')
        self._hsi_warned = self._int_warned = False
        self._error_log_started = float('-inf')
        self._error_log_keys.clear()
        self._error_log_suppressed = 0
        self._stats = {}
        self._update_buttons()

    def invalidate_metadata(self, reason):
        self.metadata = None
        self._reset_filter()
        self.rate_label.setText('配置 — Hz / 实际 — Hz')
        self.status_label.setText(('已连接' if self.connected else '未连接') + ' · ' + reason)
        self._update_buttons()

    def _update_buttons(self):
        self.connect_button.setText('断开' if self.connected else '连接')
        self.port_combo.setEnabled(not self.connected)
        self.baud_combo.setEnabled(not self.connected)
        self.refresh_button.setEnabled(not self.connected)
        self.csv_button.setText('停止 CSV' if self.csv_writer else '保存 CSV')
        self.csv_button.setEnabled(self.csv_writer is not None or (self.connected and self.metadata is not None))

    def on_status(self, frame):
        valid = (isinstance(frame, Frame) and frame.kind == 'status'
                 and frame.version == PROTO_VERSION
                 and type(frame.flags) is int and 0 <= frame.flags <= 255
                 and type(frame.sample_rate_hz) is int and 0 < frame.sample_rate_hz <= 2550
                 and type(frame.sensitivity) is int and 0 < frame.sensitivity <= 65535
                 and type(frame.range_code) is int and 0 <= frame.range_code <= 3
                 and type(frame.conv_status) is int and 0 <= frame.conv_status <= 255
                 and type(frame.device_status) is int and 0 <= frame.device_status <= 255
                 and frame.sensor_ready and frame.cfg_ok
                 and not frame.conv_status & 0x02 and not frame.device_status & 0x06)
        if not self.connected or not valid:
            self.invalidate_metadata('传感器故障或状态无效，等待有效状态')
            return
        if self.metadata is None or (frame.sensitivity, frame.range_code) != (self.metadata.sensitivity, self.metadata.range_code):
            self._reset_filter()
        self.metadata = frame
        if not frame.clock_from_hse and not self._hsi_warned:
            logger.warning('时钟使用 HSI；请核对采样速率')
            self._hsi_warned = True
        # INT path is meaningful only after a conversion reports completion.
        if frame.conv_status & 0x01 and not frame.int_path_ok and not self._int_warned:
            logger.warning('转换已完成，但 INT 路径未确认，正在使用回退读取')
            self._int_warned = True
        self._render_status()
        self._update_buttons()

    def on_sample(self, frame):
        if not self.connected or self.metadata is None or not isinstance(frame, Frame) or frame.kind != 'data':
            return
        sensitivity = self.metadata.sensitivity
        values = [frame.to_mt(raw, sensitivity) for raw in (frame.x_raw, frame.y_raw, frame.z_raw)]
        values.append(to_celsius(frame.temp_raw))
        if self.csv_writer is not None:
            try:
                self.csv_writer.write(*values)
            except Exception as exc:
                self._csv_failure(exc)
        display = values[:3]
        if self.kalman_check.isChecked():
            # Dimensionless display smoothing: no physical noise/calibration claim.
            if self._filter is None:
                self._filter = [[value, 1.0] for value in display]
            else:
                for state, value in zip(self._filter, display):
                    variance = state[1] + 0.01
                    gain = variance / (variance + 1.0)
                    state[:] = [state[0] + gain * (value - state[0]), (1 - gain) * variance]
            display = [state[0] for state in self._filter]
        self.plot.push_sample(*display, values[3])

    def on_error(self, frame):
        if not isinstance(frame, Frame) or frame.kind != 'error':
            return
        if frame.err_code == ERR_NONE:
            return
        self.invalidate_metadata('传感器故障：' + (frame.err_name or str(frame.err_code)))
        key, now = (frame.err_code, frame.i2c_addr, frame.reg_addr), time.monotonic()
        if now - self._error_log_started >= 5:
            self._error_log_started = now
            self._error_log_keys.clear()
        # Keep the first two distinct diagnostics per window, even if faults
        # alternate every frame. The key set never grows beyond two entries.
        if key not in self._error_log_keys and len(self._error_log_keys) < 2:
            logger.warning('传感器错误 %s (code=%s addr=0x%02X reg=0x%02X suppressed=%d)',
                           frame.err_name, frame.err_code, frame.i2c_addr,
                           frame.reg_addr, self._error_log_suppressed)
            self._error_log_keys.add(key)
            self._error_log_suppressed = 0
        else:
            self._error_log_suppressed += 1

    def on_transport_error(self, reason):
        self.invalidate_metadata('串口异常：' + reason)
        logger.error('串口异常：%s', reason)

    def on_stats(self, stats):
        self._stats = dict(stats)
        self._render_status()

    def _render_status(self):
        if self.metadata is None:
            return
        actual = self._stats.get('rate_hz', 0.0)
        self.rate_label.setText('配置 %s Hz / 实际 %.1f Hz' % (self.metadata.sample_rate_hz, actual))
        self.status_label.setText('已连接 · 传感器就绪 · SEQ %s · 丢帧 %s · %.1f Hz · %s · %s LSB/mT' % (
            self._stats.get('last_seq', '—'), self._stats.get('dropped_frames', 0), actual,
            self.metadata.range_name, self.metadata.sensitivity))

    def toggle_csv(self):
        if self.csv_writer is not None:
            writer, self.csv_writer = self.csv_writer, None
            try:
                writer.close()
                logger.info('CSV 已保存')
            except Exception as exc:
                self._csv_failure(exc, writer)
        elif self.connected and self.metadata is not None:
            path, _ = QFileDialog.getSaveFileName(self, '保存测量数据', '', 'CSV (*.csv)')
            # A native picker runs a nested event loop; status or connection may
            # have changed while the user chose the destination.
            if path and not self._closed and self.connected and self.metadata is not None:
                writer = CsvWriter(path)
                try:
                    writer.open()
                    self.csv_writer = writer
                    logger.info('CSV 记录开始：%s', path)
                except Exception as exc:
                    self._csv_failure(exc, writer)
        self._update_buttons()

    def _csv_failure(self, exc, writer=None):
        active, self.csv_writer = writer or self.csv_writer, None
        if active is not None:
            try:
                active.abort()
            except Exception:
                logger.exception('CSV 清理失败')
        logger.error('CSV 保存失败：%s', exc)
        self.status_label.setText('CSV 保存失败：' + str(exc))
        self._update_buttons()

    def apply_theme(self, role=None, persist=True):
        QApplication.instance().setStyleSheet(ColorScheme.get_stylesheet())
        self.plot.apply_theme()
        self.color_panel.refresh()
        if persist:
            self.persist_settings()

    def persist_settings(self):
        self.preferences['colors'].update(ColorScheme.snapshot())
        self.preferences['panels'].update(right=self.color_toggle.isChecked(), log=self.log_toggle.isChecked())
        self.preferences['acquisition'].update(port=self.port_combo.currentText(),
            baud=int(self.baud_combo.currentText()), kalman=self.kalman_check.isChecked())
        try:
            settings.save_settings(self.preferences)
        except Exception as exc:
            logger.error('设置保存失败：%s', exc)
            self.status_label.setText('设置保存失败：' + str(exc))

    def report_health(self):
        try:
            cpu = self._process.cpu_percent(None)
            rss = self._process.memory_info().rss / (1024 ** 2)
            threads = self._process.num_threads()
            stats = self.source.stats
            logger.info('HEALTH cpu=%.1f%% rss_mib=%.1f delta_mib=%+.1f threads=%d uptime_s=%.0f queue=%s/%s data_hz=%s dropped_frames=%s queue_dropped=%s skipped_bytes=%s errors=%s',
                        cpu, rss, rss-self._last_rss, threads, time.monotonic()-self._started,
                        stats.get('queue_depth', 'unknown'), stats.get('queue_capacity', 'unknown'),
                        stats.get('rate_hz', 'unknown'), stats.get('dropped_frames', 'unknown'),
                        stats.get('queue_dropped', 'unknown'), stats.get('skipped_bytes', 'unknown'), stats.get('errors', 'unknown'))
            self._last_rss = rss
        except Exception:
            logger.exception('HEALTH 读取系统指标失败')

    def closeEvent(self, event):
        if self._closed:
            event.accept()
            return
        try:
            self.source.close()
        except Exception as exc:
            self.on_transport_error('关闭未完成：' + str(exc))
            event.ignore()
            return
        if self.csv_writer is not None:
            self.toggle_csv()
        self.persist_settings()
        self.refresh_timer.stop()
        self.health_timer.stop()
        # Disconnect injected sources too, so later emissions cannot target this UI.
        for signal, slot in ((self.source.connection_changed, self.on_connection),
                (self.source.status_received, self.on_status), (self.source.sample_received, self.on_sample),
                (self.source.error_received, self.on_error), (self.source.metadata_invalidated, self.invalidate_metadata),
                (self.source.transport_error, self.on_transport_error), (self.source.stats_updated, self.on_stats)):
            signal.disconnect(slot)
        logging.getLogger().removeHandler(self._ui_handler)
        self._ui_handler.close()
        self._bridge.line.disconnect(self.log_panel.appendPlainText)
        self._closed = True
        event.accept()
