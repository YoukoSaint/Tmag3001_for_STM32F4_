"""Independent wire vectors and hostile stream tests for protocol v1.2."""
from dataclasses import FrozenInstanceError

import pytest

from tmag_viewer import protocol as p


DATA = bytes.fromhex("AA550105D8002CFF1E44683D")
STATUS_100 = bytes.fromhex("AA5642122C0375640001006F")
STATUS_500 = bytes.fromhex("AA564212AC037532000100B9")
STATUS_1000 = bytes.fromhex("AA564212AC037564000100EF")
ERROR = bytes.fromhex("AAEE0701340E00000000003C")


def status(rate=100, **overrides):
    args = dict(seq=0x42, flags=0x2C, range_code=0, sensitivity=885,
                sample_rate_hz=rate, err_count=0, conv_status=1, device_status=0)
    args.update(overrides)
    return p.encode_status(**args)


def repair_checksum(wire):
    wire = bytearray(wire)
    wire[-1] = p.crc8(wire[2:11])
    return bytes(wire)


def test_constants_and_legacy_xor():
    assert (p.FRAME_SIZE, p.SYNC, p.PROTO_VERSION) == (12, 0xAA, 0x12)
    assert (p.TYPE_DATA, p.TYPE_STATUS, p.TYPE_ERROR) == (0x55, 0x56, 0xEE)
    assert p.FLAG_RANGE_MASK == 3
    assert [p.FLAG_SENSOR_READY, p.FLAG_CFG_OK, p.FLAG_TRIGGER_INT,
            p.FLAG_INT_PATH_OK, p.FLAG_CLK_SRC_HSE, p.FLAG_RATE_X10] == [4, 8, 16, 32, 64, 128]
    names = ["NONE", "I2C_NACK", "SENSOR_ID", "CONFIG_FAIL", "I2C_READ",
             "I2C_TIMEOUT", "NO_CONV", "SENSOR_DIAG", "OVERFLOW", "TX_OVERFLOW"]
    for code, name in enumerate(names):
        assert getattr(p, "ERR_" + name) == code
        assert p.ERR_NAMES[code] == name
    assert p.crc8(b"") == 0
    assert p.crc8(bytes.fromhex("0105D8002CFF1E")) == 0x11


@pytest.mark.parametrize("wire,encoded,kind,seq", [
    (DATA, lambda: p.encode_data(1, 1496, 44, -226, 17512), "data", 1),
    (STATUS_100, lambda: status(100), "status", 0x42),
    (STATUS_500, lambda: status(500), "status", 0x42),
    (STATUS_1000, lambda: status(1000), "status", 0x42),
    (ERROR, lambda: p.encode_error(7, 1, 0x34, 0x0E), "error", 7),
])
def test_hardcoded_cross_language_goldens(wire, encoded, kind, seq):
    assert len(wire) == 12
    assert encoded() == wire
    frame = p.decode_frame(wire)
    assert (frame.kind, frame.seq) == (kind, seq)


@pytest.mark.parametrize("raw", [-32768, -1, 0, 1, 32767])
def test_signed_raw_roundtrip(raw):
    frame = p.decode_frame(p.encode_data(255, raw, -1, 32767, -32768))
    assert (frame.x_raw, frame.y_raw, frame.z_raw, frame.temp_raw) == (raw, -1, 32767, -32768)
    with pytest.raises(FrozenInstanceError):
        frame.seq = 0


@pytest.mark.parametrize("rate", [0, 1, 100, 200, 255, 260, 500, 1000, 2550])
def test_rate_encoding_replaces_stale_flag_and_preserves_hse(rate):
    wire = status(rate, flags=0xFF)
    frame = p.decode_frame(wire)
    assert frame.sample_rate_hz == rate
    assert bool(frame.flags & p.FLAG_RATE_X10) == (rate > 255)
    assert frame.clock_from_hse
    assert frame.flags & p.FLAG_RANGE_MASK == 0
    assert frame.sensor_ready and frame.cfg_ok and frame.int_path_ok
    assert frame.flags & p.FLAG_TRIGGER_INT


@pytest.mark.parametrize("rate", [-1, 256, 259, 2551, 2560, 65535, 100.0, True, False, None, "100"])
def test_unrepresentable_rates_rejected(rate):
    with pytest.raises(ValueError):
        status(rate)


@pytest.mark.parametrize("code,name", enumerate(("±40mT", "±80mT", "±120mT", "±240mT")))
def test_status_fields_and_received_sensitivity(code, name):
    frame = p.decode_frame(status(range_code=code, sensitivity=777, err_count=0x1234,
                                 conv_status=0xAB, device_status=0x17))
    assert (frame.version, frame.range_code, frame.range_name) == (0x12, code, name)
    assert (frame.sensitivity, frame.err_count, frame.conv_status, frame.device_status) == (777, 0x34, 0xAB, 0x17)
    assert frame.to_mt(1554, frame.sensitivity) == 2.0
    assert frame.to_mt(-777, frame.sensitivity) == -1.0


@pytest.mark.parametrize("sensitivity", [0, -1, True, 1.0, None, "885", 65536])
def test_invalid_engineering_sensitivity_never_invents_units(sensitivity):
    with pytest.raises(ValueError):
        p.Frame("data", 0).to_mt(1, sensitivity)


def test_temperature_and_unset_flags():
    frame = p.decode_frame(DATA)
    assert frame.temp_raw == 17512
    assert p.to_celsius(frame.temp_raw) == 25.0
    assert p.to_celsius(17512 + 582) == pytest.approx(35.0)
    assert not any((frame.sensor_ready, frame.cfg_ok, frame.int_path_ok, frame.clock_from_hse))
    assert p.Frame("status", 0, range_code=4).range_name == "未知"


@pytest.mark.parametrize("field,value", [
    ("range_code", -1), ("range_code", 4), ("range_code", True),
    ("sensitivity", -1), ("sensitivity", 65536), ("sensitivity", 885.0),
    ("flags", -1), ("flags", 256), ("flags", True),
    ("conv_status", 256), ("device_status", -1), ("err_count", -1),
    ("err_count", True), ("err_count", 0x100000000),
])
def test_invalid_status_integer_fields(field, value):
    with pytest.raises(ValueError):
        status(**{field: value})


@pytest.mark.parametrize("raw", [-32769, 32768, True, 1.5])
def test_invalid_raw_fields(raw):
    with pytest.raises(ValueError):
        p.encode_data(0, raw, 0, 0, 0)


def test_counter_wrap_and_error_fields():
    assert p.decode_frame(p.encode_data(256, 0, 0, 0, 0)).seq == 0
    assert p.decode_frame(p.encode_error(-1, 0)).seq == 255
    frame = p.decode_frame(p.encode_error(7, 0xFE, 0x34, 0x0E))
    assert (frame.err_code, frame.err_name, frame.i2c_addr, frame.reg_addr) == (0xFE, "UNKNOWN", 0x34, 0x0E)
    assert p.encode_error(0, 0)[6:11] == bytes(5)
    assert p.decode_frame(status(sensitivity=0, err_count=0xFFFFFFFF)).err_count == 255


@pytest.mark.parametrize("args", [(True, 0), (1.0, 0), (0, -1), (0, 256), (0, True), (0, 0, 256), (0, 0, 0, -1)])
def test_invalid_error_fields(args):
    with pytest.raises(ValueError):
        p.encode_error(*args)


@pytest.mark.parametrize("wire", [b"", DATA[:-1], DATA + b"x", bytes([0]) + DATA[1:],
                                   DATA[:1] + b"\x57" + DATA[2:], DATA[:-1] + b"\x00"])
def test_invalid_frames(wire):
    assert p.decode_frame(wire) is None


def test_unknown_status_version_rejected_even_with_valid_checksum():
    wire = bytearray(STATUS_100)
    wire[3] = 0x13
    assert p.decode_frame(repair_checksum(wire)) is None


@pytest.mark.parametrize("split", range(13))
def test_fragmented_all_boundaries(split):
    stream = p.FrameStream()
    events = stream.feed(DATA[:split]) + stream.feed(DATA[split:])
    assert events == [(p.decode_frame(DATA), 0)]
    assert len(stream._buf) == 0


def test_coalesced_types_do_not_count_sequence_gaps():
    stream = p.FrameStream()
    assert stream.feed(DATA + STATUS_100 + ERROR) == [
        (p.decode_frame(wire), 0) for wire in (DATA, STATUS_100, ERROR)]


def test_false_sync_corruption_noise_and_incomplete_tail_accounting():
    corrupt = bytearray(DATA)
    corrupt[4] = 0xAA
    invalid_version = bytearray(STATUS_100)
    invalid_version[3] = 0x13
    prefix = b"noise\xaa\x99" + corrupt + repair_checksum(invalid_version)
    stream = p.FrameStream()
    events = stream.feed(prefix + DATA + ERROR[:7])
    assert [frame for frame, _ in events if frame] == [p.decode_frame(DATA)]
    assert sum(dropped for _, dropped in events) == len(prefix)
    assert all(dropped == 0 if frame else dropped > 0 for frame, dropped in events)
    assert bytes(stream._buf) == ERROR[:7]
    assert stream.feed(ERROR[7:]) == [(p.decode_frame(ERROR), 0)]


def test_large_noise_and_bytewise_stream_remain_bounded():
    stream = p.FrameStream()
    events = stream.feed(b"x" * 100000)
    assert sum(dropped for _, dropped in events) == 100000
    assert len(events) == 1
    assert not stream._buf
    events = []
    for value in b"\xaa" * 50 + DATA + b"tail":
        events.extend(stream.feed(bytes([value])))
        assert len(stream._buf) < 12
    assert [frame for frame, _ in events if frame] == [p.decode_frame(DATA)]
    assert sum(dropped for _, dropped in events) == 54
    assert stream.feed(b"") == []
