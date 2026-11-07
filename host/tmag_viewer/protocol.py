"""TMAG3001 v1.2 wire codec, independent of Qt and serial transport.

Frames are 12 bytes; the compatibility name ``crc8`` means bytewise XOR
over bytes 2..10, not a polynomial CRC. Invalid encoder fields raise
ValueError. Integer sequence numbers wrap modulo 256, as in the C API;
the uint32 error counter is transmitted modulo 256. Other fields are
validated before packing and never silently truncated.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Optional

FRAME_SIZE = 12
SYNC = 0xAA
TYPE_DATA = 0x55
TYPE_STATUS = 0x56
TYPE_ERROR = 0xEE
PROTO_VERSION = 0x12

FLAG_RANGE_MASK = 0x03
FLAG_SENSOR_READY = 1 << 2
FLAG_CFG_OK = 1 << 3
FLAG_TRIGGER_INT = 1 << 4
FLAG_INT_PATH_OK = 1 << 5
FLAG_CLK_SRC_HSE = 1 << 6
FLAG_RATE_X10 = 1 << 7

ERR_NONE = 0x00
ERR_I2C_NACK = 0x01
ERR_SENSOR_ID = 0x02
ERR_CONFIG_FAIL = 0x03
ERR_I2C_READ = 0x04
ERR_I2C_TIMEOUT = 0x05
ERR_NO_CONV = 0x06
ERR_SENSOR_DIAG = 0x07
ERR_OVERFLOW = 0x08  # Reserved: no confirmed sensor overflow condition.
ERR_TX_OVERFLOW = 0x09

ERR_NAMES = {
    ERR_NONE: "NONE", ERR_I2C_NACK: "I2C_NACK", ERR_SENSOR_ID: "SENSOR_ID",
    ERR_CONFIG_FAIL: "CONFIG_FAIL", ERR_I2C_READ: "I2C_READ",
    ERR_I2C_TIMEOUT: "I2C_TIMEOUT", ERR_NO_CONV: "NO_CONV",
    ERR_SENSOR_DIAG: "SENSOR_DIAG", ERR_OVERFLOW: "OVERFLOW",
    ERR_TX_OVERFLOW: "TX_OVERFLOW",
}
RANGE_NAMES = ("±40mT", "±80mT", "±120mT", "±240mT")


def _integer(name: str, value: int, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in {low}..{high}")
    return value


def _sequence(seq: int) -> int:
    if isinstance(seq, bool) or not isinstance(seq, int):
        raise ValueError("seq must be an integer")
    return seq & 0xFF


@dataclass(frozen=True)
class Frame:
    """Decoded frame; use the fields corresponding to ``kind``."""

    kind: str
    seq: int
    x_raw: int = 0
    y_raw: int = 0
    z_raw: int = 0
    temp_raw: int = 0
    version: int = 0
    flags: int = 0
    range_code: int = 0
    sensitivity: int = 0
    sample_rate_hz: int = 0
    err_count: int = 0
    conv_status: int = 0
    device_status: int = 0
    err_code: int = 0
    err_name: str = ""
    i2c_addr: int = 0
    reg_addr: int = 0

    @property
    def sensor_ready(self) -> bool:
        return bool(self.flags & FLAG_SENSOR_READY)

    @property
    def cfg_ok(self) -> bool:
        return bool(self.flags & FLAG_CFG_OK)

    @property
    def int_path_ok(self) -> bool:
        return bool(self.flags & FLAG_INT_PATH_OK)

    @property
    def clock_from_hse(self) -> bool:
        return bool(self.flags & FLAG_CLK_SRC_HSE)

    @property
    def range_name(self) -> str:
        return RANGE_NAMES[self.range_code] if 0 <= self.range_code < 4 else "未知"

    def to_mt(self, raw: int, sensitivity: int) -> float:
        """Convert using received status sensitivity (LSB/mT), never a fallback.

        Zero/unknown sensitivity cannot supply engineering units and raises
        ValueError; the caller must wait for a usable status frame.
        """
        _integer("sensitivity", sensitivity, 1, 65535)
        return raw / float(sensitivity)


def to_celsius(raw: int) -> float:
    """Convert a signed sensor temperature reading to degrees Celsius."""
    return (raw - 17512) / 58.2 + 25


def crc8(data: bytes) -> int:
    """Compatibility name for bytewise XOR, with initial value zero."""
    result = 0
    for value in data:
        result ^= value
    return result


def _encode(kind: int, seq: int, payload: bytes) -> bytes:
    body = bytes([_sequence(seq)]) + payload
    return bytes([SYNC, kind]) + body + bytes([crc8(body)])


def encode_data(seq: int, x_raw: int, y_raw: int, z_raw: int, temp_raw: int) -> bytes:
    """Encode four signed int16 raw readings; invalid values raise ValueError."""
    values = (x_raw, y_raw, z_raw, temp_raw)
    for name, value in zip(("x_raw", "y_raw", "z_raw", "temp_raw"), values):
        _integer(name, value, -32768, 32767)
    return _encode(TYPE_DATA, seq, struct.pack(">hhhh", *values))


def encode_status(seq: int, flags: int, range_code: int, sensitivity: int,
                  sample_rate_hz: int, err_count: int, conv_status: int,
                  device_status: int) -> bytes:
    """Encode nominal integer Hz, deriving range/rate bits from logical fields."""
    _integer("flags", flags, 0, 255)
    _integer("range_code", range_code, 0, 3)
    _integer("sensitivity", sensitivity, 0, 65535)
    _integer("sample_rate_hz", sample_rate_hz, 0, 2550)
    _integer("err_count", err_count, 0, 0xFFFFFFFF)
    _integer("conv_status", conv_status, 0, 255)
    _integer("device_status", device_status, 0, 255)
    flags = (flags & ~(FLAG_RANGE_MASK | FLAG_RATE_X10)) | range_code
    rate = sample_rate_hz
    if rate > 255:
        if rate % 10:
            raise ValueError("sample_rate_hz above 255 must be an exact multiple of 10")
        flags |= FLAG_RATE_X10
        rate //= 10
    payload = struct.pack(">BBHBBBB", PROTO_VERSION, flags, sensitivity, rate,
                          err_count & 0xFF, conv_status, device_status)
    return _encode(TYPE_STATUS, seq, payload)


def encode_error(seq: int, err_code: int, i2c_addr: int = 0, reg_addr: int = 0) -> bytes:
    """Encode a diagnostic frame with five reserved zero bytes."""
    for name, value in (("err_code", err_code), ("i2c_addr", i2c_addr), ("reg_addr", reg_addr)):
        _integer(name, value, 0, 255)
    return _encode(TYPE_ERROR, seq, bytes([err_code, i2c_addr, reg_addr]) + bytes(5))


def decode_frame(data: bytes) -> Optional[Frame]:
    """Reject invalid framing, checksum, status version or ERROR padding."""
    if (len(data) != FRAME_SIZE or data[0] != SYNC
            or data[1] not in (TYPE_DATA, TYPE_STATUS, TYPE_ERROR)
            or crc8(data[2:11]) != data[11]):
        return None
    seq = data[2]
    if data[1] == TYPE_DATA:
        x, y, z, temp = struct.unpack(">hhhh", data[3:11])
        return Frame("data", seq, x_raw=x, y_raw=y, z_raw=z, temp_raw=temp)
    if data[1] == TYPE_STATUS:
        version, flags, sensitivity, rate, err, conv, device = struct.unpack(">BBHBBBB", data[3:11])
        if version != PROTO_VERSION:
            return None
        return Frame("status", seq, version=version, flags=flags,
                     range_code=flags & FLAG_RANGE_MASK, sensitivity=sensitivity,
                     sample_rate_hz=rate * (10 if flags & FLAG_RATE_X10 else 1),
                     err_count=err, conv_status=conv, device_status=device)
    if any(data[6:11]):
        return None
    code, addr, reg = data[3:6]
    return Frame("error", seq, err_code=code, err_name=ERR_NAMES.get(code, "UNKNOWN"),
                 i2c_addr=addr, reg_addr=reg)


class FrameStream:
    """Incremental, bounded-memory resynchronizer; no sequence-gap accounting."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, chunk: bytes) -> list[tuple[Optional[Frame], int]]:
        """Return (frame, 0) or (None, discarded byte count) events.

        Each input byte is examined a bounded number of times. At most 12
        candidate bytes are held, regardless of noise/chunk length. Invalid
        candidates slide one byte so embedded sync bytes remain recoverable.
        Adjacent discards within this call are combined; incomplete tails
        remain buffered and are not counted as discarded.
        """
        out: list[tuple[Optional[Frame], int]] = []
        dropped = 0
        for value in chunk:
            self._buf.append(value)
            while self._buf:
                if self._buf[0] != SYNC:
                    del self._buf[0]
                    dropped += 1
                elif len(self._buf) >= 2 and self._buf[1] not in (TYPE_DATA, TYPE_STATUS, TYPE_ERROR):
                    del self._buf[0]
                    dropped += 1
                elif len(self._buf) < FRAME_SIZE:
                    break
                else:
                    frame = decode_frame(bytes(self._buf))
                    if frame is None:
                        del self._buf[0]
                        dropped += 1
                    else:
                        if dropped:
                            out.append((None, dropped))
                            dropped = 0
                        out.append((frame, 0))
                        self._buf.clear()
        if dropped:
            out.append((None, dropped))
        return out
