"""Qt serial transport with a bounded delivery queue and raw wire frames.

The reader never posts per-frame Qt events. A GUI-thread timer drains at most
4096 frames per tick; overflow is explicitly counted as queue_dropped, separate
from wire sequence loss. Call open/close on the owning Qt thread.
"""
from __future__ import annotations

from collections import deque
import logging
import threading
import time

from PyQt5.QtCore import QObject, QThread, QTimer, pyqtSignal
import serial

from .protocol import FrameStream, ERR_NONE

logger = logging.getLogger(__name__)
QUEUE_CAPACITY = 4096


class _Reader(QThread):
    def __init__(self, connection, owner):
        super().__init__(owner)
        self.connection = connection
        self.owner = owner
        self.stop_requested = threading.Event()
        self.failure = None

    def run(self):
        parser = FrameStream()
        try:
            while not self.stop_requested.is_set():
                chunk = self.connection.read(4096)
                if self.stop_requested.is_set():
                    break
                for frame, skipped in parser.feed(chunk):
                    self.owner._record(frame, skipped)
        except Exception as exc:
            if not self.stop_requested.is_set():
                self.failure = str(exc)
                logger.exception("[transport=serial][addr=%s@%d] read failed", self.owner._port, self.owner._baud)
        finally:
            try:
                self.connection.close()
            except Exception:
                logger.exception("[transport=serial][addr=%s@%d] serial close failed", self.owner._port, self.owner._baud)


class SerialSource(QObject):
    sample_received = pyqtSignal(object)
    status_received = pyqtSignal(object)
    error_received = pyqtSignal(object)
    transport_error = pyqtSignal(str)
    metadata_invalidated = pyqtSignal(str)
    stats_updated = pyqtSignal(dict)
    connection_changed = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._serial_factory = serial.Serial
        self._clock = time.monotonic
        self._lock = threading.Lock()
        self._queue = deque()
        self._worker = None
        # Synchronous Qt slots can issue a newer lifecycle request mid-emission.
        self._operation = 0
        self._port, self._baud = "", 115200
        self._connected = False
        self._started = self._clock()
        self._last_stats = self._started
        self._last_error_log = float("-inf")
        self._reported_queue_dropped = 0
        self._last_queue_log = float("-inf")
        self._reset()
        self._timer = QTimer(self)
        self._timer.setInterval(25)
        self._timer.timeout.connect(self._poll)

    def _reset(self):
        with self._lock:
            self._queue.clear()
            self._counts = dict(frames=0, samples=0, dropped_frames=0,
                                skipped_bytes=0, errors=0, last_seq=None,
                                queue_dropped=0, queue_status_dropped=0,
                                duplicates=0, out_of_order=0)

    @property
    def stats(self):
        with self._lock:
            snapshot = dict(self._counts)
            snapshot.update(dropped=snapshot["dropped_frames"],
                            queue_depth=len(self._queue), queue_capacity=QUEUE_CAPACITY)
        elapsed = self._clock() - self._started
        snapshot["rate_hz"] = snapshot["samples"] / elapsed if elapsed > 0 else 0.0
        return snapshot

    def _record(self, frame, skipped):
        with self._lock:
            counts = self._counts
            counts["skipped_bytes"] += skipped
            if frame is None:
                return
            previous = counts["last_seq"]
            delta = (frame.seq - previous) & 255 if previous is not None else 1
            if delta == 0:
                counts["duplicates"] += 1
            elif delta < 128:
                counts["dropped_frames"] += delta - 1
                counts["last_seq"] = frame.seq
            else:
                counts["out_of_order"] += 1
            counts["frames"] += 1
            counts["samples"] += frame.kind == "data"
            counts["errors"] += frame.kind == "error" and frame.err_code != ERR_NONE
            if len(self._queue) == QUEUE_CAPACITY:
                # Preserve configuration boundaries before the surviving data.
                # Even status-only overload is bounded and explicitly reported.
                index = next((i for i, queued in enumerate(self._queue)
                              if queued.kind != "status"), 0)
                discarded = self._queue[index]
                del self._queue[index]
                counts["queue_status_dropped"] += discarded.kind == "status"
                counts["queue_dropped"] += 1
            self._queue.append(frame)

    def open(self, port: str, baud: int = 115200) -> bool:
        """Open a session; return False if a synchronous slot supersedes it."""
        self._operation += 1
        operation = self._operation
        self._close(operation)
        if self._operation != operation:
            return False
        if (not isinstance(port, str) or not port.strip() or isinstance(baud, bool)
                or not isinstance(baud, int) or baud <= 0):
            self.transport_error.emit("Invalid serial port or baud rate")
            if self._operation == operation:
                self.connection_changed.emit(False)
            return False
        self._port, self._baud = port, baud
        self._reset()
        self._started = self._last_stats = self._clock()
        self._last_error_log = float("-inf")
        self._reported_queue_dropped = 0
        self._last_queue_log = float("-inf")
        try:
            connection = self._serial_factory(port=port, baudrate=baud, timeout=0.1)
        except Exception as exc:
            logger.exception("[transport=serial][addr=%s@%d] open failed", port, baud)
            self.transport_error.emit(str(exc))
            if self._operation == operation:
                self.connection_changed.emit(False)
            return False
        if self._operation != operation:
            connection.close()
            return False
        self._worker = _Reader(connection, self)
        self._connected = True
        logger.info("[transport=serial][addr=%s@%d] START metrics=%s", port, baud, self.stats)
        self._worker.start()
        self._timer.start()
        self.connection_changed.emit(True)
        return self._operation == operation

    def _poll(self):
        session = self._worker
        operation = self._operation
        with self._lock:
            pending = list(self._queue)
            self._queue.clear()
            queue_dropped = self._counts["queue_dropped"]
            status_dropped = self._counts["queue_status_dropped"]
        if queue_dropped > self._reported_queue_dropped:
            self._reported_queue_dropped = queue_dropped
            now = self._clock()
            if now - self._last_queue_log >= 5:
                logger.warning("[transport=serial][addr=%s@%d] delivery queue overflow lost=%d", self._port, self._baud, queue_dropped)
                self._last_queue_log = now
            message = "Serial delivery queue overflow: %d frames lost" % queue_dropped
            self.transport_error.emit(message)
            if self._worker is not session or self._operation != operation:
                return
            if status_dropped:
                self.metadata_invalidated.emit(message + "; status may need refresh")
        for frame in pending:
            if self._worker is not session or self._operation != operation:
                return
            if frame.kind == "data":
                self.sample_received.emit(frame)
            elif frame.kind == "status":
                self.status_received.emit(frame)
            else:
                self.error_received.emit(frame)
                if self._worker is not session or self._operation != operation:
                    return
                now = self._clock()
                if frame.err_code != ERR_NONE and now - self._last_error_log >= 5:
                    logger.warning("[transport=serial][addr=%s@%d] firmware error=%s code=%d errors=%d", self._port, self._baud, frame.err_name, frame.err_code, self.stats["errors"])
                    self._last_error_log = now
        if self._worker is not session or self._operation != operation:
            return
        now = self._clock()
        if now - self._last_stats >= 0.2:
            self.stats_updated.emit(self.stats)
            if self._worker is not session or self._operation != operation:
                return
            self._last_stats = now
        worker = session
        if worker is not None and not worker.isRunning() and worker.failure is not None:
            self.transport_error.emit(worker.failure)
            # A synchronous error handler may already have opened a new session.
            if self._worker is worker and self._operation == operation:
                self.close()

    def close(self) -> None:
        self._operation += 1
        self._close(self._operation)

    def _close(self, operation):
        """Retire the current reader within the caller's lifecycle request."""
        worker = self._worker
        if worker is None:
            return
        worker.stop_requested.set()
        try:
            cancel = getattr(worker.connection, "cancel_read", None)
            if cancel is not None:
                cancel()
        except Exception:
            logger.exception("[transport=serial][addr=%s@%d] cancel read failed", self._port, self._baud)
        if QThread.currentThread() is worker:
            raise RuntimeError("Serial reader cannot wait for itself")
        if not worker.wait(500):
            try:
                worker.connection.close()
            except Exception:
                logger.exception("[transport=serial][addr=%s@%d] stop close failed", self._port, self._baud)
            if not worker.wait(500):
                logger.error("[transport=serial][addr=%s@%d] STOP failed: reader still running", self._port, self._baud)
                self.transport_error.emit("Serial reader did not stop")
                raise RuntimeError("Serial reader did not stop")
        self._timer.stop()
        self._worker = None
        worker.deleteLater()
        with self._lock:
            self._queue.clear()
        if self._connected:
            self._connected = False
            logger.info("[transport=serial][addr=%s@%d] STOP metrics=%s", self._port, self._baud, self.stats)
            self.connection_changed.emit(False)
            if self._operation != operation:
                return
        self.stats_updated.emit(self.stats)
