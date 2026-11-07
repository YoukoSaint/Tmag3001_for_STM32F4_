import logging
import threading
import time
from collections import deque

import pytest
from PyQt5.QtTest import QTest
from PyQt5.QtCore import QObject

from tmag_viewer import protocol as p
from tmag_viewer.serial_source import SerialSource
from tmag_viewer import serial_source


class FakeSerial:
    def __init__(self, chunks=()):
        self.chunks = deque(chunks)
        self.stopped = threading.Event()
        self.closed = False

    def read(self, size):
        if self.chunks:
            chunk = self.chunks.popleft()
            if isinstance(chunk, Exception):
                raise chunk
            return chunk
        self.stopped.wait(0.01)
        return b""

    def cancel_read(self):
        self.stopped.set()

    def close(self):
        self.closed = True
        self.stopped.set()


def wait_until(predicate):
    deadline = time.monotonic() + 2
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(10)
    assert predicate()


def status(seq, rate=1000):
    return p.encode_status(seq, 0x0C, 0, 885, rate, 0, 1, 0)


@pytest.fixture
def source(qapp):
    instance = SerialSource()
    yield instance
    instance.close()


def connect_fake(source, chunks):
    fake = FakeSerial(chunks)
    source._serial_factory = lambda **kwargs: fake
    assert source.open("FAKE")
    return fake


def test_mixed_raw_frames_and_all_type_sequence(source):
    data, statuses, errors = [], [], []
    source.sample_received.connect(data.append)
    source.status_received.connect(statuses.append)
    source.error_received.connect(errors.append)
    wire = p.encode_data(254, -1234, 2, 3, 17512) + status(255) + p.encode_error(0, 1) + p.encode_data(1, 5, 6, 7, 8)
    connect_fake(source, [wire[:7], wire[7:]])
    wait_until(lambda: len(data) == 2 and len(errors) == 1)
    assert data[0].x_raw == -1234 and data[0].temp_raw == 17512
    assert statuses[0].sample_rate_hz == 1000
    assert source.stats["frames"] == 4
    assert source.stats["samples"] == 2
    assert source.stats["dropped"] == 0
    snapshot = source.stats
    snapshot["frames"] = 99
    assert source.stats["frames"] == 4


@pytest.mark.parametrize("middle,final_seq,skipped,dropped", [
    (b"noise", 1, 5, 0),
    (bytes.fromhex("aa5501000000000000000002"), 2, 12, 1),
    (b"", 4, 0, 3),
    (p.encode_data(0, 0, 0, 0, 0), 1, 0, 0),
])
def test_gap_and_discard_counters_separate(source, middle, final_seq, skipped, dropped):
    connect_fake(source, [p.encode_data(0, 1, 2, 3, 4) + middle + p.encode_data(final_seq, 1, 2, 3, 4)])
    wait_until(lambda: source.stats["last_seq"] == final_seq)
    assert source.stats["skipped_bytes"] == skipped
    assert source.stats["dropped_frames"] == dropped


def test_rate_counts_data_only_and_diagnostics_throttled(source, caplog):
    now = [10.0]
    source._clock = lambda: now[0]
    updates = []
    source.stats_updated.connect(updates.append)
    with caplog.at_level(logging.INFO):
        connect_fake(source, [p.encode_data(0, 1, 2, 3, 4) + status(1, 500) + p.encode_error(2, 0) + b"".join(p.encode_error(i + 3, 0xFE) for i in range(200))])
        wait_until(lambda: source.stats["frames"] == 203)
        now[0] = 12.0
        assert source.stats["rate_hz"] == 0.5
        assert source.stats["errors"] == 200
        QTest.qWait(250)
        assert len(updates) <= 3
    assert len([r for r in caplog.records if "firmware" in r.message]) <= 2


def test_close_reopen_resets_and_stops_worker(source):
    changes = []
    source.connection_changed.connect(changes.append)
    fake = connect_fake(source, [p.encode_data(40, 1, 2, 3, 4)])
    wait_until(lambda: source.stats["samples"] == 1)
    worker = source._worker
    source.close()
    source.close()
    assert fake.closed and not worker.isRunning()
    connect_fake(source, [status(7)])
    wait_until(lambda: source.stats["frames"] == 1)
    assert source.stats["samples"] == 0 and source.stats["dropped"] == 0
    assert changes == [True, False, True]


def test_open_and_read_failure_signals_and_logs(source, caplog):
    errors, changes = [], []
    source.transport_error.connect(errors.append)
    source.connection_changed.connect(changes.append)

    def fail(**kwargs):
        raise OSError("cannot open")

    source._serial_factory = fail
    with caplog.at_level(logging.INFO):
        assert not source.open("FAKE")
        assert changes == [False] and errors
        fake = connect_fake(source, [OSError("read failed")])
        wait_until(lambda: changes[-1] is False and len(changes) == 3)
    assert fake.closed
    assert "[transport=serial][addr=FAKE@115200]" in caplog.text
    assert "cannot open" in caplog.text and "read failed" in caplog.text


def test_read_failure_handler_can_reopen_without_closing_replacement(source):
    class CountedSerial(FakeSerial):
        close_calls = 0

        def close(self):
            self.close_calls += 1
            super().close()

    changes, errors, received = [], [], []
    source.connection_changed.connect(changes.append)
    source.sample_received.connect(received.append)
    replacement = CountedSerial()
    failed = CountedSerial([p.encode_data(40, 1, 2, 3, 4), OSError("read failed")])
    ports = iter([failed, replacement])
    source._serial_factory = lambda **kwargs: next(ports)

    def reconnect(message):
        errors.append(message)
        assert source._worker is old_worker and not old_worker.isRunning()
        assert source.open("REPLACEMENT")

    source.transport_error.connect(reconnect)
    assert source.open("FAILED")
    old_worker = source._worker
    wait_until(lambda: bool(errors))
    assert changes == [True, False, True]
    assert failed.closed
    assert failed.close_calls == 1
    assert source._worker is not None and source._worker.isRunning()
    assert not replacement.closed
    assert source.stats["frames"] == source.stats["samples"] == 0
    assert source.stats["last_seq"] is None

    received.clear()
    replacement.chunks.append(p.encode_data(7, 5, 6, 7, 8))
    wait_until(lambda: len(received) == 1)
    assert received[0].seq == 7
    assert source.stats["frames"] == source.stats["samples"] == 1
    assert source.stats["dropped_frames"] == 0
    replacement_worker = source._worker
    source.close()
    assert replacement.closed and not replacement_worker.isRunning()
    assert failed.close_calls == replacement.close_calls == 1
    assert source._worker is None
    assert changes == [True, False, True, False]


@pytest.mark.parametrize("port,baud", [("", 115200), (None, 115200), ("FAKE", 0), ("FAKE", True)])
def test_invalid_parameters_never_open(source, port, baud):
    source._serial_factory = lambda **kwargs: pytest.fail("must not open")
    assert not source.open(port, baud)


def test_delivery_queue_bounded_without_gui_events(source):
    connect_fake(source, [b"".join(p.encode_data(i, 1, 2, 3, 4) for i in range(5000))])
    deadline = time.monotonic() + 2
    while source.stats["frames"] < 5000 and time.monotonic() < deadline:
        time.sleep(0.005)
    assert source.stats["frames"] == 5000
    assert source.stats["queue_depth"] == source.stats["queue_capacity"] == 4096
    assert source.stats["queue_dropped"] == 904
    assert source.stats["dropped_frames"] == 0


def test_no_ui_and_factory_timeout(source, qapp):
    before = qapp.topLevelWidgets()
    arguments = []
    fake = FakeSerial()

    def factory(**kwargs):
        arguments.append(kwargs)
        return fake

    source._serial_factory = factory
    assert source.open("FAKE", 9600)
    assert arguments == [dict(port="FAKE", baudrate=9600, timeout=0.1)]
    assert qapp.topLevelWidgets() == before


def test_close_during_delivery_prevents_old_session_frames(source):
    received = []

    def consume(frame):
        received.append(frame)
        source.close()

    source.sample_received.connect(consume)
    connect_fake(source, [p.encode_data(0, 1, 2, 3, 4) + p.encode_data(1, 5, 6, 7, 8)])
    wait_until(lambda: bool(received))
    assert len(received) == 1


def test_close_from_connection_signal_does_not_start_orphan(source):
    source.connection_changed.connect(lambda connected: source.close() if connected else None)
    fake = FakeSerial()
    source._serial_factory = lambda **kwargs: fake
    assert not source.open("FAKE")
    assert fake.closed and source._worker is None


def test_overload_retains_status_before_remaining_samples(source):
    received = []
    source.status_received.connect(lambda frame: received.append(frame.kind))
    source.sample_received.connect(lambda frame: received.append(frame.kind))
    errors = []
    source.transport_error.connect(errors.append)
    first = b"".join(p.encode_data(i, 1, 2, 3, 4) for i in range(1000))
    second = b"".join(p.encode_data(i + 1001, 1, 2, 3, 4) for i in range(4000))
    connect_fake(source, [first + status(1000) + second])
    deadline = time.monotonic() + 2
    while source.stats["frames"] < 5001 and time.monotonic() < deadline:
        time.sleep(0.005)
    wait_until(lambda: bool(received))
    assert received.count("status") == 1
    assert received.index("status") == 95
    assert source.stats["queue_dropped"] == 905
    assert any("overflow" in str(error) for error in errors)


def test_metadata_only_overload_reports_invalidation(source):
    errors = []
    source.metadata_invalidated.connect(errors.append)
    connect_fake(source, [b"".join(status(i) for i in range(4200))])
    deadline = time.monotonic() + 2
    while source.stats["frames"] < 4200 and time.monotonic() < deadline:
        time.sleep(0.005)
    assert source.stats["queue_status_dropped"] == 104
    assert source.stats["queue_depth"] == 4096
    wait_until(lambda: bool(errors))
    assert "status may need refresh" in errors[0]


def test_out_of_order_frame_does_not_turn_into_false_255_loss(source):
    wire = b"".join(p.encode_data(i, 1, 2, 3, 4) for i in (10, 9, 11))
    connect_fake(source, [wire])
    wait_until(lambda: source.stats["frames"] == 3)
    assert source.stats["out_of_order"] == 1
    assert source.stats["dropped_frames"] == 0
    assert source.stats["last_seq"] == 11


def test_failed_shutdown_keeps_worker_reference_until_stopped(source):
    entered, release = threading.Event(), threading.Event()

    class Stubborn(FakeSerial):
        def read(self, size):
            entered.set()
            release.wait(4)
            return b""

        def cancel_read(self):
            pass

        def close(self):
            self.closed = True

    fake = Stubborn()
    source._serial_factory = lambda **kwargs: fake
    assert source.open("FAKE")
    assert entered.wait(1)
    worker = source._worker
    try:
        with pytest.raises(RuntimeError, match="did not stop"):
            source.close()
        assert source._worker is worker and worker.isRunning()
    finally:
        release.set()
        assert worker.wait(1000)
        source.close()
    assert source._worker is None


@pytest.fixture
def fake_workers(monkeypatch):
    workers = []

    class FakeWorker(QObject):
        def __init__(self, connection, owner):
            super().__init__(owner)
            self.connection = connection
            self.stop_requested = threading.Event()
            self.failure = None
            self.running = False
            self.wait_calls = 0
            workers.append(self)

        def start(self):
            self.running = True

        def isRunning(self):
            return self.running

        def wait(self, timeout):
            self.wait_calls += 1
            if self.running:
                self.connection.close()
                self.running = False
            return True

    monkeypatch.setattr(serial_source, "_Reader", FakeWorker)
    return workers


def test_reopen_from_disconnect_supersedes_outer_open(source, fake_workers):
    ports, changes, updates = [], [], []

    def factory(**kwargs):
        ports.append(kwargs["port"])
        return FakeSerial()

    source._serial_factory = factory
    source.connection_changed.connect(changes.append)
    source.stats_updated.connect(updates.append)
    assert source.open("A")
    source._record(p.decode_frame(p.encode_data(10, 1, 2, 3, 4)), 0)

    def reopen(connected):
        if not connected and len(ports) == 1:
            assert source.open("C")

    source.connection_changed.connect(reopen)
    assert not source.open("B")
    assert ports == ["A", "C"]
    assert source._worker is fake_workers[-1]
    assert changes == [True, False, True]
    assert source.stats["frames"] == 0
    assert not updates  # The superseded close must not emit C's stats.
    source.close()
    assert all(not worker.isRunning() and worker.connection.closed
               and worker.wait_calls == 1 for worker in fake_workers)


@pytest.mark.parametrize("invalid", [False, True])
def test_open_error_reconnect_has_no_stale_disconnection(source, fake_workers, invalid):
    changes = []
    source.connection_changed.connect(changes.append)

    def factory(**kwargs):
        if kwargs["port"] == "BAD":
            raise OSError("cannot open")
        return FakeSerial()

    source._serial_factory = factory
    source.transport_error.connect(lambda message: source.open("GOOD"))
    assert not source.open("" if invalid else "BAD")
    assert changes == [True]
    assert source._connected and source._worker.isRunning()
    assert source._port == "GOOD" and source.stats["frames"] == 0
    source.close()
    assert all(not worker.isRunning() and worker.connection.closed
               for worker in fake_workers)


def test_stats_reopen_does_not_inspect_or_drain_replacement(source, fake_workers):
    now, received, errors = [10.0], [], []
    source._clock = lambda: now[0]
    source._serial_factory = lambda **kwargs: FakeSerial()
    source.sample_received.connect(received.append)
    source.transport_error.connect(errors.append)
    assert source.open("OLD")
    old = source._worker

    def reopen(snapshot):
        if source._worker is old:
            now[0] = 12.0
            assert source.open("NEW")
            source._record(p.decode_frame(p.encode_data(7, 1, 2, 3, 4)), 0)
            source._worker.failure = "new read failed"
            source._worker.connection.close()
            source._worker.running = False

    source.stats_updated.connect(reopen)
    now[0] = 11.0
    source._poll()
    assert source._worker is fake_workers[-1]
    assert source._port == "NEW" and source._connected
    assert source._last_stats == 12.0
    assert source.stats["frames"] == source.stats["queue_depth"] == 1
    assert not received and not errors
    source._poll()
    assert [frame.seq for frame in received] == [7]
    assert errors == ["new read failed"]
    assert source._worker is None
    assert all(not worker.isRunning() and worker.connection.closed
               and worker.wait_calls == 1
               for worker in fake_workers)
