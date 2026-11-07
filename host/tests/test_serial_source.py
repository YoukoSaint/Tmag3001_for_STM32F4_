import logging
import threading
import time
from collections import deque

import pytest
from PyQt5.QtTest import QTest

from tmag_viewer import protocol as p
from tmag_viewer.serial_source import SerialSource


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
    fake = connect_fake(source, [])
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
