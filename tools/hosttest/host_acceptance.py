"""Bounded headless host acceptance. Offline by default; physical I/O requires --port.

Artifacts are isolated to new directories below this checkout's build/host-acceptance.
Replay contains accepted raw_hex frames, not the original discarded byte stream.
"""
from __future__ import annotations

import argparse
from collections import deque
import csv
from datetime import datetime, timezone
import json
import logging
import math
import os
from pathlib import Path
import sys
import threading
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_ROOT = ROOT / "build" / "host-acceptance"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--synthetic", action="store_true", help="SIMULATION: 100 known raw samples")
    modes.add_argument("--replay", type=Path, help="offline capture JSON with accepted raw_hex records")
    modes.add_argument("--port", help="EXPLICIT physical serial port (never selected automatically)")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--seconds", type=float, help="bounded run, default offline 4 s / live 35 s")
    parser.add_argument("--out-dir", type=Path, help="new directory below build/host-acceptance")
    args = parser.parse_args(argv)
    args.seconds = args.seconds if args.seconds is not None else (35 if args.port else 4)
    if not math.isfinite(args.seconds) or not 2 <= args.seconds <= 120:
        parser.error("--seconds must be finite and between 2 and 120")
    if args.baud <= 0 or (args.port is not None and not args.port.strip()):
        parser.error("port must be nonempty and baud must be positive")
    if args.replay is not None and not args.replay.is_file():
        parser.error("--replay must name an existing capture JSON")
    return args


def reserve_output(path=None):
    """Resolve junctions/symlinks before enforcing a new checkout-contained output."""
    base = ARTIFACT_ROOT.resolve()
    # Also reject an artifact-root junction redirected outside this checkout.
    base.relative_to(ROOT.resolve())
    destination = (path or base / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")).resolve()
    destination.relative_to(base)
    if destination == base:
        raise ValueError("output must be a new child directory, not the artifact root")
    destination.mkdir(parents=True, exist_ok=False)
    return destination


def replay_frames(path):
    capture = json.loads(path.read_text(encoding="utf-8-sig"))
    records = capture.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("capture needs nonempty records with raw_hex")
    frames = []
    for record in records:
        raw = bytes.fromhex(record["raw_hex"])
        if len(raw) != 12:
            raise ValueError("each historical record must contain a 12-byte raw_hex frame")
        frames.append(raw)
    return capture, frames


class FakeSerial:
    """Cancellable paced byte transport, used by the production reader QThread."""

    def __init__(self, frames, delay):
        # Deliberately split frames across read calls to exercise FrameStream.
        self.chunks = deque(chunk for frame in frames for chunk in (frame[:7], frame[7:]))
        self.delay = delay
        self.stopped = threading.Event()
        self.closed = False

    def read(self, size):
        if self.stopped.wait(self.delay if self.chunks else 0.01):
            return b""
        return self.chunks.popleft() if self.chunks else b""

    def cancel_read(self):
        self.stopped.set()

    def close(self):
        self.closed = True
        self.stopped.set()


def synthetic_frames():
    from tmag_viewer import protocol as p
    status = p.encode_status(0, p.FLAG_SENSOR_READY | p.FLAG_CFG_OK | p.FLAG_CLK_SRC_HSE,
                             0, 885, 100, 0, 1, 0x10)
    raw_values = [(885 + i * 17, -1770 + i * 3, 442 - i * 2, 17570 + i) for i in range(100)]
    frames = [status, p.encode_error(1, p.ERR_NONE)]
    frames.extend(p.encode_data(i + 2, *values) for i, values in enumerate(raw_values))
    return frames, raw_values


def require_live_data(report, metadata_ready):
    """A physical healthy run must demonstrate usable data across the whole UI."""
    report["checks"].update(
        live_healthy_metadata=bool(metadata_ready),
        live_received_data=report["delivered"]["data"] > 0,
        live_csv_contains_data=report["csv_numeric_rows"] > 0,
        live_four_curves_have_data=(len(report["curve_points"]) == 4
                                   and all(n > 0 for n in report["curve_points"])))


def run(args):
    # This must precede every Qt import, including pyqtgraph's transitive imports.
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    sys.path.insert(0, str(ROOT / "host"))
    from PyQt5.QtCore import QEventLoop, QTimer
    from PyQt5.QtGui import QFont, QFontDatabase
    from PyQt5.QtWidgets import QApplication, QFileDialog
    from tmag_viewer import log_setup, protocol as p, settings_manager as settings
    from tmag_viewer.color_scheme import ColorScheme
    from tmag_viewer.main_window import MainWindow
    from tmag_viewer.serial_source import SerialSource

    capture, frames, raw_values = {}, [], []
    if args.synthetic:
        frames, raw_values = synthetic_frames()
    elif args.replay:
        capture, frames = replay_frames(args.replay)
    expected_frames = sum(p.decode_frame(raw) is not None for raw in frames)
    out = reserve_output(args.out_dir)
    mode = "live" if args.port else "synthetic" if args.synthetic else "replay"
    report = dict(mode=mode, physical_acceptance=False, source=str(args.replay.resolve()) if args.replay else mode,
                  limitations="Synthetic values are simulation; replay raw_hex omits original discarded bytes and timing. Live healthy acceptance requires DATA.",
                  requested_seconds=args.seconds, checks={}, artifacts=str(out))
    report["historical_records"] = len(frames)
    report["records_rejected_by_current_codec"] = len(frames) - expected_frames
    checks = report["checks"]
    previous_handlers = logging.getLogger().handlers[:]
    previous_level = logging.getLogger().level
    previous_owned = log_setup._owned_handlers[:]
    # setup_logging owns its handlers; don't let it close a caller's previous ones.
    log_setup._owned_handlers[:] = []
    source = window = None
    fake = None
    errors = []
    old_hook = sys.excepthook
    sys.excepthook = lambda kind, value, traceback: errors.append(f"{kind.__name__}: {value}")
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    for name in ("msyh.ttc", "arial.ttf"):
        font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name
        if font_path.is_file():
            QFontDatabase.addApplicationFont(str(font_path))
    app.setFont(QFont("Microsoft YaHei", 10))
    app.setStyleSheet(ColorScheme.get_stylesheet())

    def wait_until(predicate, seconds):
        """Nested bounded Qt event loop, never a busy wait or an unbounded GUI."""
        loop = QEventLoop()
        poll, deadline = QTimer(), QTimer()
        poll.setInterval(10)
        poll.timeout.connect(lambda: loop.quit() if predicate() or errors else None)
        deadline.setSingleShot(True)
        deadline.timeout.connect(loop.quit)
        poll.start()
        deadline.start(max(1, int(seconds * 1000)))
        try:
            if not predicate():
                loop.exec_()
        finally:
            poll.stop()
            deadline.stop()
        if errors:
            raise RuntimeError("Qt callback failure: " + "; ".join(errors))
        return bool(predicate())

    csv_path = out / "samples.csv"
    delivered = {"data": [], "status": [], "error": []}
    expected_csv = []
    first_csv_raw = None
    log_path = None
    start = time.monotonic()
    try:
        log_path = Path(log_setup.setup_logging("host_acceptance", out / "logs", logging.WARNING))
        logging.info("ACCEPTANCE mode=%s physical_port=%s source=%s", mode, args.port or "NONE", report["source"])
        with patch.object(settings, "get_settings_path", lambda: out / "settings.json"), \
                patch.object(QFileDialog, "getSaveFileName", lambda *a, **k: (str(csv_path), "CSV (*.csv)")), \
                patch("tmag_viewer.main_window.list_ports.comports", return_value=[]):
            source = SerialSource()
            if not args.port:
                fake = FakeSerial(frames, 0.005 if args.synthetic else 0)
                source._serial_factory = lambda **kwargs: fake
            window = MainWindow(source)
            window.setWindowTitle("TMAG3001 acceptance — " + mode.upper())
            window.kalman_check.setChecked(bool(args.synthetic))
            checks["initial_unknown_metadata_neutral"] = window.metadata is None and not window.csv_button.isEnabled() and "故障" not in window.status_label.text()
            window.show()  # offscreen platform only; needed for realistic rendering.
            source.sample_received.connect(delivered["data"].append)
            source.status_received.connect(delivered["status"].append)
            source.error_received.connect(delivered["error"].append)

            def observe_sample(frame):
                nonlocal first_csv_raw
                if window.csv_writer is not None and window.metadata is not None:
                    raw = [frame.x_raw, frame.y_raw, frame.z_raw, frame.temp_raw]
                    if first_csv_raw is None:
                        first_csv_raw = raw
                    expected_csv.append([f"{value / window.metadata.sensitivity:.4f}" for value in raw[:3]]
                                        + [f"{(raw[3] - 17512) / 58.2 + 25:.4f}"])
            source.sample_received.connect(observe_sample)

            def begin_csv(frame):
                if window.metadata is not None and window.csv_writer is None and not csv_path.exists():
                    window.toggle_csv()
                    checks["csv_target_hidden_while_open"] = not csv_path.exists() and window.csv_writer is not None
            source.status_received.connect(begin_csv)
            if not source.open(args.port or "OFFLINE_FAKE", args.baud):
                raise RuntimeError("source did not connect")
            checks["connected"] = window.connected
            if args.port:
                wait_until(lambda: False, args.seconds)
                window.report_health() if args.seconds < 31 else None
            else:
                if not wait_until(lambda: not fake.chunks and source.stats["queue_depth"] == 0 and len(delivered["data"]) + len(delivered["status"]) + len(delivered["error"]) == expected_frames, args.seconds):
                    raise RuntimeError("offline replay did not drain before deadline")
                # Explicit snapshot calls the actual metrics implementation; live >=31 s uses its natural timer.
                window.report_health()
            report["elapsed_seconds"] = time.monotonic() - start
            report["source_stats"] = source.stats
            report["delivered"] = {key: len(value) for key, value in delivered.items()}
            report["status_text"] = window.status_label.text()
            report["rate_text"] = window.rate_label.text()
            report["last_status"] = vars(delivered["status"][-1]) if delivered["status"] else None
            report["plotted_samples"] = len(window.plot.samples)
            window.plot.refresh()
            report["curve_points"] = [len(curve.getData()[0]) if curve.getData()[0] is not None else 0 for curve in window.plot.curves]
            report["csv_rows_before_close"] = window.csv_writer._rows if window.csv_writer else 0
            if window.csv_writer:
                checks["csv_target_hidden_before_close"] = not csv_path.exists()
                window.toggle_csv()
            rows = []
            if csv_path.exists():
                with csv_path.open(encoding="utf-8", newline="") as stream:
                    rows = list(csv.reader(stream))
            report["csv_numeric_rows"] = len(rows) - 1 if rows else 0
            report["csv_observed_first_raw"] = first_csv_raw
            report["csv_observed_first_expected"] = expected_csv[0] if expected_csv else None
            checks["csv_rows_match_received_raw_and_status"] = rows[1:] == expected_csv
            if expected_csv:
                checks["csv_published_after_stop"] = csv_path.is_file()
            report["counter_units"] = {"dropped_frames": "global wire sequence frames (all types)",
                                       "skipped_bytes": "parser bytes", "queue_dropped": "delivery queue frames",
                                       "queue_depth": "queued frames", "samples": "parsed DATA frames, including UI-gated samples"}
            if raw_values:
                expected = [[f"{raw / 885:.4f}" for raw in values[:3]] + [f"{(values[3] - 17512) / 58.2 + 25:.4f}"] for values in raw_values]
                report["first_raw"] = raw_values[0]
                report["expected_first_csv"] = expected[0]
                report["actual_first_csv"] = rows[1] if len(rows) > 1 else None
                checks["all_100_csv_rows_match_unfiltered_raw"] = rows[1:] == expected
                checks["100_plotted_samples"] = len(window.plot.samples) == 100
                checks["four_rendered_curves"] = report["curve_points"] == [100] * 4
                checks["display_kalman_does_not_change_csv"] = window.plot.samples[1][1] != raw_values[1][0] / 885 and rows[2] == expected[1]
                checks["err_none_neutral"] = window.metadata is not None and source.stats["errors"] == 0
                checks["all_type_sequence_consecutive"] = all(source.stats[key] == 0 for key in ("dropped_frames", "duplicates", "out_of_order", "skipped_bytes", "queue_dropped"))
            elif not delivered["data"]:
                checks["fault_no_plot_or_csv_rows"] = not window.plot.samples and report["csv_numeric_rows"] == 0 and window.metadata is None
                checks["fault_label_explicit"] = "故障" in window.status_label.text() or "异常" in window.status_label.text()
            if args.port:
                require_live_data(report, window.metadata is not None)
            window.plot.refresh()
            checks["screenshot_saved"] = window.grab().save(str(out / "window.png"))
            # Drain the queued log bridge before preserving the displayed evidence.
            wait_until(lambda: False, 0.05)
            (out / "ui-log.txt").write_text(window.log_panel.toPlainText(), encoding="utf-8")
            if args.synthetic:
                before = len(window.plot.samples)
                source.metadata_invalidated.emit("acceptance boundary")
                checks["invalidated_gates_csv"] = window.metadata is None and not window.csv_button.isEnabled()
                # Send through the actual worker/parser after invalidation, not directly into UI slots.
                fake.chunks.extend((p.encode_data(102, 2000, 0, 0, 17512),))
                if not wait_until(lambda: len(delivered["data"]) == 101, 1):
                    raise RuntimeError("boundary sample was not delivered")
                checks["invalidated_gates_plot"] = len(window.plot.samples) == before
                # Nominal 100 Hz diagnostic stream through the same reader and UI.
                for seq in range(103, 203):
                    frame = p.encode_error(seq, p.ERR_SENSOR_DIAG, 0x34, 0x1C)
                    fake.chunks.extend((frame[:7], frame[7:]))
                if not wait_until(lambda: len(delivered["error"]) == 101, 3):
                    raise RuntimeError("100 Hz nominal diagnostics did not drain")
                checks["diagnostic_stream_gates_plot"] = len(window.plot.samples) == before and window.metadata is None
                report["diagnostic_phase"] = dict(nominal_hz=100, frames=100, source_stats=source.stats)
            source.close()
            checks["disconnect_gates_csv"] = not window.connected and window.metadata is None and not window.csv_button.isEnabled()
            source.status_received.disconnect(begin_csv)
            source.sample_received.disconnect(observe_sample)
            window.close()
            checks["close_stops_workers_and_timers"] = source._worker is None and not source._timer.isActive() and not window.refresh_timer.isActive() and not window.health_timer.isActive() and window._closed
            checks["ui_handler_detached"] = window._ui_handler not in logging.getLogger().handlers
            checks["isolated_settings_saved"] = (out / "settings.json").is_file()
            checks["no_temporary_residue"] = not list(out.glob("*.tmp")) and not list(out.glob(".*.tmp"))
            checks["fake_closed"] = fake.closed if fake else True
            checks["no_qt_callback_exceptions"] = not errors
            for handler in log_setup._owned_handlers:
                handler.flush()
            content = log_path.read_text(encoding="utf-8")
            checks["logs_have_health_and_serial_lifecycle"] = all(token in content for token in ("HEALTH cpu=", "rss_mib=", "threads=", "[transport=serial]", "START metrics=", "STOP metrics="))
            checks["logs_have_no_traceback"] = "Traceback (most recent call last)" not in content
            report["firmware_ui_warning_lines"] = content.count("传感器错误 ")
            if args.replay and len(delivered["error"]) >= 100:
                checks["fault_logs_throttled"] = report["firmware_ui_warning_lines"] <= 2
                report["original_capture_counters_not_replayable"] = {key: capture.get(key) for key in ("discarded_bytes", "lost_frames", "data_frames")}
            if args.synthetic:
                checks["nominal_100hz_diagnostic_logs_throttled"] = report["firmware_ui_warning_lines"] <= 2
            report["physical_data_observed"] = bool(args.port and delivered["data"] and report["csv_numeric_rows"])
            report["healthy_hardware_A4_A5"] = "REVIEW_LIVE_EVIDENCE" if report["physical_data_observed"] else "PENDING"
            report["passed"] = all(checks.values())
    except Exception as exc:
        report["passed"] = False
        report["failure"] = f"{type(exc).__name__}: {exc}"
        report["failure_stats"] = source.stats if source is not None else None
        report["failure_delivered"] = {key: len(value) for key, value in delivered.items()}
        logging.exception("ACCEPTANCE failed")
    finally:
        try:
            if source is not None:
                source.close()
            if window is not None and not window._closed:
                # Keep failure-path persistence isolated too.
                with patch.object(settings, "get_settings_path", lambda: out / "settings.json"):
                    window.close()
        finally:
            sys.excepthook = old_hook
            root_logger = logging.getLogger()
            for handler in log_setup._owned_handlers:
                root_logger.removeHandler(handler)
                handler.close()
            log_setup._owned_handlers[:] = previous_owned
            root_logger.handlers[:] = previous_handlers
            root_logger.setLevel(previous_level)
            report["qt_callback_exceptions"] = errors
            report["log_path"] = str(log_path) if log_path else None
            (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "mode": mode, "report": str(out / "report.json")}, ensure_ascii=False))
    return 0 if report["passed"] else 1


def main(argv=None):
    args = parse_args(argv)  # --help exits without importing Qt or opening a port.
    try:
        return run(args)
    except (OSError, ValueError) as exc:
        print(f"Acceptance configuration error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
