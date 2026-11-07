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

    def read(self, size):
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
