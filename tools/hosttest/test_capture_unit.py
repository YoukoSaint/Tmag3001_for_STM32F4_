"""Capture acceptance checks using synthetic bytes, never a physical port."""
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).with_name("test_capture.py")


def load_capture():
    assert SCRIPT.is_file(), "capture command must exist"
    spec = importlib.util.spec_from_file_location("capture_command", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class Serial:
    def __init__(self, clock, chunks, fail=False):
        self.clock, self.chunks, self.fail = clock, list(chunks), fail
        self.closed = False
        self.timeout = 0.1
        self.flush_count = 0
        self.read_sizes = []

    def reset_input_buffer(self):
        self.flush_count += 1
        self.clock.now += 0.025

    def read(self, size):
        self.read_sizes.append(size)
        self.clock.now += 0.1
        if self.fail:
            raise OSError("disconnected")
        return self.chunks.pop(0) if self.chunks else b""

    def close(self):
        self.closed = True


def run(chunks, tmp_path, *args, fail=False):
    capture = load_capture()
    clock = Clock()
    port = Serial(clock, chunks, fail)
    summary_path = tmp_path / "summary.json"
    code = capture.main(["--seconds", "1", "--json-out", str(summary_path), *args],
                        serial_factory=lambda **kwargs: port, clock=clock)
    return code, json.loads(summary_path.read_text(encoding="utf-8")), port


def test_fragmented_mixed_global_sequence_and_raw_records(tmp_path):
    c = load_capture()
    p = c.protocol
    frames = [p.encode_data(254, 1, -2, 3, 4),
              p.encode_status(255, 0, 0, 100, 1000, 0, 0x21, 0x14),
              p.encode_error(0, p.ERR_NONE), p.encode_data(2, 5, 6, 7, 8),
              p.encode_data(2, 5, 6, 7, 8), p.encode_error(3, p.ERR_I2C_NACK)]
    wire = b"noise" + b"".join(frames)
    code, out, port = run([wire[:7], wire[7:30], wire[30:]], tmp_path)
    assert code == 0 and port.closed
    assert out["valid_frames"] == 6
    assert out["data_frames"] == 3 and out["error_frames"] == 1
    assert out["lost_frames"] == 1 and out["duplicate_frames"] == 1
    assert out["discarded_bytes"] == 5
    assert out["last_status"]["sample_rate_hz"] == 1000
    assert out["last_status"]["device_status"] == 0x14
    assert len(out["data_records"]) == 3
    assert out["data_records"][1]["after_status"] is True
    assert out["data_hz"] == pytest.approx(3 / out["elapsed_seconds"])
    assert all(record["crc_valid"] for record in out["records"])


def test_read_size_experiment_is_explicit_and_validated(tmp_path):
    p = load_capture().protocol
    code, out, port = run([p.encode_status(0, 0, 0, 885, 100, 0, 1, 0x10)],
                          tmp_path, "--read-size", "1")
    assert code == 0 and out["read_size"] == 1
    assert port.read_sizes and set(port.read_sizes) == {1}
    for size in ["0", "-1", "65537"]:
        with pytest.raises(SystemExit):
            load_capture().main(["--read-size", size])


@pytest.mark.parametrize("rate", [500, 1000])
def test_no_sensor_status_error_is_accepted(tmp_path, rate):
    p = load_capture().protocol
    code, out, port = run([p.encode_status(0, 0, 0, 0, rate, 1, 0, 0)
                           + p.encode_error(1, p.ERR_I2C_NACK)], tmp_path)
    assert code == 0 and port.closed
    assert out["data_frames"] == 0 and out["last_status"]["sample_rate_hz"] == rate


@pytest.mark.parametrize("wire,args", [(b"silent text", []), (b"", []),
    ("data", []), ("status", ["--require-data"])])
def test_missing_required_frames_fails_and_closes(tmp_path, wire, args):
    p = load_capture().protocol
    if wire == "data":
        wire = p.encode_data(0, 0, 0, 0, 0)
    elif wire == "status":
        wire = p.encode_status(0, 0, 0, 0, 100, 0, 0, 0)
    code, out, port = run([wire], tmp_path, *args)
    assert code != 0 and port.closed and out["failure"]


def test_read_failure_closes_and_writes_summary(tmp_path):
    code, out, port = run([], tmp_path, fail=True)
    assert code != 0 and port.closed and "disconnected" in out["failure"]


def test_open_failure_and_positive_duration(tmp_path):
    capture = load_capture()
    def unavailable(**kwargs):
        raise OSError("unavailable")
    assert capture.main(["--seconds", "0.1"], serial_factory=unavailable) != 0
    for seconds in ["0", "-1", "nan", "inf"]:
        with pytest.raises(SystemExit):
            capture.main(["--seconds", seconds], serial_factory=unavailable)


def test_checksum_noise_recovery_retains_exact_wire_bytes(tmp_path):
    p = load_capture().protocol
    status = p.encode_status(10, 0, 0, 100, 500, 0, 1, 2)
    damaged = bytearray(p.encode_data(11, 100, 200, 300, 400))
    damaged[-1] ^= 1
    data = p.encode_data(12, -32768, 32767, 0, -1)
    code, out, _ = run([status + damaged + data], tmp_path)
    assert code == 0 and out["valid_frames"] == 2
    assert out["discarded_bytes"] == 12 and out["lost_frames"] == 1
    assert [r["raw_hex"] for r in out["records"]] == [status.hex(), data.hex()]


def test_atomic_json_failure_preserves_previous_file_and_cleans_temp(tmp_path, monkeypatch):
    c = load_capture()
    target = tmp_path / "capture.json"
    target.write_text("previous", encoding="utf-8")
    def refuse(source, destination):
        raise PermissionError("cannot replace")
    monkeypatch.setattr(c.os, "replace", refuse)
    with pytest.raises(PermissionError):
        c.atomic_json(target, {"valid_frames": 1})
    assert target.read_text(encoding="utf-8") == "previous"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["capture.json"]


def test_preview_bounded_but_json_preserves_every_data(tmp_path, capsys):
    p = load_capture().protocol
    wire = p.encode_status(0, 0, 0, 100, 1000, 0, 0, 0)
    wire += b"".join(p.encode_data(i, i, i, i, i) for i in range(1, 61))
    code, out, _ = run([wire], tmp_path)
    printed = capsys.readouterr().out.splitlines()
    assert code == 0 and out["data_frames"] == 60
    assert len(out["data_records"]) == 60 and out["lost_frames"] == 0
    assert sum(line.startswith("DATA ") for line in printed) == 20
    assert any(line.startswith("METRICS ") for line in printed)


def test_import_from_unrelated_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    c = load_capture()
    assert Path(c.protocol.__file__).resolve() == SCRIPT.parents[2] / "host/tmag_viewer/protocol.py"


@pytest.mark.parametrize("flush", [False, True])
def test_raw_preserves_original_reads_noise_rejects_and_tail(tmp_path, flush):
    p = load_capture().protocol
    good = p.encode_status(10, 0, 0, 100, 500, 0, 1, 2)
    bad = bytes.fromhex("aaee6b07341c00000000aaee")
    tail = p.encode_data(11, 1, 2, 3, 4)[:7]
    wire = b"noise" + bad + good + tail
    raw = tmp_path / "wire.bin"
    args = ["--raw-out", str(raw)] + (["--flush-input"] if flush else [])
    code, out, port = run([wire[:8], wire[8:25], wire[25:]], tmp_path, *args)
    assert code == 0 and port.closed
    assert raw.read_bytes() == wire
    assert out["raw_bytes"] == len(wire) and out["raw_complete"] is True
    assert Path(out["raw_path"]) == raw
    assert out["flush_input"] is flush and port.flush_count == int(flush)
    assert out["flush_duration_seconds"] == pytest.approx(0.025 if flush else 0)
    assert bool(out["flush_started_utc"]) is flush
    assert out["valid_frames"] == 1
    for record in out["records"]:
        end = record["raw_end_offset"]
        assert wire[end-12:end].hex() == record["raw_hex"]
    assert out["records"][0]["raw_end_offset"] == 29


def test_raw_existing_file_preserved_without_opening_port(tmp_path):
    target = tmp_path / "wire.bin"
    target.write_bytes(b"previous")
    code, out, port = run([], tmp_path, "--raw-out", str(target))
    assert code != 0 and out["failure"]
    assert target.read_bytes() == b"previous"
    assert out["raw_complete"] is False and out["raw_bytes"] == 0
    assert not port.closed  # The unopened fake port was never acquired.


def test_raw_and_json_must_be_distinct_before_open(tmp_path):
    c = load_capture()
    def unexpected(**kwargs):
        pytest.fail("must reject paths before opening serial")
    target = tmp_path / "same"
    with pytest.raises(SystemExit):
        c.main(["--raw-out", str(target), "--json-out", str(target)],
               serial_factory=unexpected)
    assert not target.exists()


def test_raw_read_failure_marks_incomplete_and_closes(tmp_path):
    raw = tmp_path / "wire.bin"
    code, out, port = run([], tmp_path, "--raw-out", str(raw), fail=True)
    assert code != 0 and port.closed and "disconnected" in out["failure"]
    assert raw.read_bytes() == b"" and out["raw_complete"] is False


def test_raw_json_samefile_alias_preserves_existing_evidence(tmp_path, monkeypatch):
    c = load_capture()
    raw, summary = tmp_path / "wire.bin", tmp_path / "summary.json"
    raw.write_bytes(b"previous")
    summary.write_bytes(b"previous")
    monkeypatch.setattr(c.os.path, "samefile", lambda first, second: True)
    with pytest.raises(SystemExit):
        c.main(["--raw-out", str(raw), "--json-out", str(summary)],
               serial_factory=lambda **kw: pytest.fail("must not open port"))
    assert raw.read_bytes() == summary.read_bytes() == b"previous"


def test_raw_write_failure_closes_and_retains_partial_metadata(tmp_path, monkeypatch):
    c = load_capture()
    clock = Clock()
    port = Serial(clock, [b"noise"])
    class FailingRaw:
        closed = False
        def write(self, chunk):
            raise OSError("disk full")
        def close(self):
            self.closed = True
    raw = FailingRaw()
    monkeypatch.setattr(c, "open_raw", lambda path: raw)
    summary = tmp_path / "summary.json"
    code = c.main(["--seconds", "1", "--raw-out", str(tmp_path / "wire.bin"),
                   "--json-out", str(summary)], serial_factory=lambda **kw: port, clock=clock)
    out = json.loads(summary.read_text(encoding="utf-8"))
    assert code != 0 and port.closed and raw.closed
    assert "disk full" in out["failure"]
    assert out["raw_complete"] is False and out["raw_bytes"] == 0
    assert out["read_bytes"] == 5 and out["valid_frames"] == 0


def test_raw_short_write_then_failure_keeps_exact_partial_prefix(tmp_path, monkeypatch):
    c = load_capture()
    clock = Clock()
    port = Serial(clock, [b"noise"])
    target = tmp_path / "wire.bin"
    backing = c.open_raw(target)
    class PartialRaw:
        calls = 0
        def write(self, chunk):
            self.calls += 1
            if self.calls == 1:
                return backing.write(chunk[:2])
            raise OSError("disk full")
        def close(self):
            backing.close()
    monkeypatch.setattr(c, "open_raw", lambda path: PartialRaw())
    summary = tmp_path / "summary.json"
    assert c.main(["--raw-out", str(target), "--json-out", str(summary)],
                  serial_factory=lambda **kw: port, clock=clock) == 1
    out = json.loads(summary.read_text(encoding="utf-8"))
    assert port.closed and backing.closed
    assert target.read_bytes() == b"no"
    assert out["raw_bytes"] == 2 and out["read_bytes"] == 5
    assert out["raw_complete"] is False and out["valid_frames"] == 0


def test_raw_fsync_failure_closes_and_marks_incomplete(tmp_path, monkeypatch):
    c = load_capture()
    clock = Clock()
    frame = c.protocol.encode_error(1, 0)
    port = Serial(clock, [frame])
    def refuse(fd):
        raise OSError("fsync failed")
    monkeypatch.setattr(c.os, "fsync", refuse)
    target, summary = tmp_path / "wire.bin", tmp_path / "summary.json"
    assert c.main(["--seconds", "1", "--no-require-status", "--raw-out", str(target),
                   "--json-out", str(summary)],
                  serial_factory=lambda **kw: port, clock=clock) == 1
    out = json.loads(summary.read_text(encoding="utf-8"))
    assert port.closed and target.read_bytes() == frame
    assert out["raw_bytes"] == len(frame) and out["raw_complete"] is False
    assert "fsync failed" in out["failure"]


def test_flush_failure_closes_outputs_and_does_not_read(tmp_path):
    c = load_capture()
    clock = Clock()
    port = Serial(clock, [b"never read"])
    def refuse():
        port.flush_count += 1
        clock.now += 0.03
        raise OSError("flush failed")
    port.reset_input_buffer = refuse
    target, summary = tmp_path / "wire.bin", tmp_path / "summary.json"
    assert c.main(["--flush-input", "--raw-out", str(target), "--json-out", str(summary)],
                  serial_factory=lambda **kw: port, clock=clock) == 1
    out = json.loads(summary.read_text(encoding="utf-8"))
    assert port.closed and port.flush_count == 1 and port.chunks == [b"never read"]
    assert out["raw_complete"] is False and out["read_bytes"] == 0
    assert out["flush_duration_seconds"] == pytest.approx(0.03)
    assert "flush failed" in out["failure"]
