"""Headless TMAG capture; default success requires at least one status frame.

JSON retains every valid wire frame and DATA reading, including before/after
status timing. Sequence loss is modulo 256 across ALL frame types; a whole
256-frame loss cannot be detected by the wire counter alone. No commands are
written to the serial port.

Optional raw output contains original reads, including noise and incomplete
tails. It is created exclusively (never overwrites an existing file). Serial
or raw-I/O failures preserve partial raw output and leave raw_complete false.
raw_complete reflects serial/raw-I/O completion; later frame validation or
JSON output failure is independent and may leave raw_complete true.
Elapsed time and DATA Hz include serial open and optional input flush time.
"""
from __future__ import annotations

import argparse
from collections import deque
from dataclasses import asdict
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "host"))
from tmag_viewer import protocol


def positive_seconds(value):
    seconds = float(value)
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("seconds must be finite and positive")
    return seconds


def atomic_json(path, summary):
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                         prefix=target.name + ".", suffix=".tmp",
                                         delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(summary, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        os.replace(temporary, target)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def open_raw(path):
    """Create a new unbuffered evidence file; preserve existing files."""
    return Path(path).open("xb", buffering=0)


def main(argv=None, *, serial_factory=None, clock=time.monotonic):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM9")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--read-size", type=int, default=4096,
                        help="bytes requested per serial read (default: 4096)")
    parser.add_argument("--seconds", type=positive_seconds, default=10.0)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--raw-out", type=Path,
                        help="new raw byte file; existing files are refused")
    parser.add_argument("--flush-input", action="store_true",
                        help="discard preexisting driver input once after open (default: off)")
    parser.add_argument("--require-status", action=argparse.BooleanOptionalAction,
                        default=True, help="require a valid status (default: true)")
    parser.add_argument("--require-data", action="store_true")
    args = parser.parse_args(argv)
    if args.baud <= 0:
        parser.error("baud must be positive")
    if not 1 <= args.read_size <= 65536:
        parser.error("read-size must be between 1 and 65536")
    if args.raw_out and args.json_out:
        if (args.raw_out.resolve() == args.json_out.resolve()
                or (args.raw_out.exists() and args.json_out.exists()
                    and os.path.samefile(args.raw_out, args.json_out))):
            parser.error("raw and JSON output paths must be distinct")
    started = clock()
    result = dict(port=args.port, baud=args.baud, read_size=args.read_size,
                  requested_seconds=args.seconds,
                  started_utc=datetime.now(timezone.utc).isoformat(),
                  valid_frames=0, data_frames=0, status_frames=0, error_frames=0,
                  error_none_frames=0, discarded_bytes=0, lost_frames=0,
                  duplicate_frames=0, last_status=None, records=[], data_records=[],
                  raw_path=str(args.raw_out.resolve()) if args.raw_out else None,
                  raw_bytes=0, read_bytes=0,
                  raw_complete=False if args.raw_out else None,
                  flush_input=args.flush_input, flush_started_utc=None,
                  flush_duration_seconds=0.0, open_duration_seconds=0.0,
                  failure=None)
    serial_port = None
    raw_file = None
    raw_offset = 0
    stream = protocol.FrameStream()
    raw_tail = deque(maxlen=protocol.FRAME_SIZE)
    last_seq = None
    next_metrics = started + 1
    diagnostic_preview = 0
    try:
        if args.raw_out:
            raw_file = open_raw(args.raw_out)
        if serial_factory is None:
            import serial
            serial_factory = serial.Serial
        open_started = clock()
        serial_port = serial_factory(port=args.port, baudrate=args.baud,
                                     timeout=min(0.1, args.seconds))
        result["open_duration_seconds"] = clock() - open_started
        if args.flush_input:
            result["flush_started_utc"] = datetime.now(timezone.utc).isoformat()
            flush_started = clock()
            try:
                serial_port.reset_input_buffer()
            finally:
                result["flush_duration_seconds"] = clock() - flush_started
        while clock() < started + args.seconds:
            serial_port.timeout = min(0.1, max(0.001, started + args.seconds - clock()))
            chunk = serial_port.read(args.read_size)
            result["read_bytes"] += len(chunk)
            if raw_file is not None:
                remaining = memoryview(chunk)
                while remaining:
                    written = raw_file.write(remaining)
                    if written is None or written <= 0:
                        raise OSError("raw output write made no progress")
                    result["raw_bytes"] += written
                    remaining = remaining[written:]
            received = clock() - started
            for value in chunk:
                raw_offset += 1
                raw_tail.append(value)
                for frame, discarded in stream.feed(bytes((value,))):
                    result["discarded_bytes"] += discarded
                    if frame is None:
                        continue
                    result["valid_frames"] += 1
                    if last_seq is not None:
                        delta = (frame.seq - last_seq) & 0xFF
                        if delta == 0:
                            result["duplicate_frames"] += 1
                        else:
                            result["lost_frames"] += delta - 1
                    last_seq = frame.seq
                    record = asdict(frame)
                    record.update(elapsed_seconds=received, raw_hex=bytes(raw_tail).hex(),
                                  raw_end_offset=raw_offset,
                                  crc_valid=True,
                                  after_status=result["last_status"] is not None)
                    result["records"].append(record)
                    if frame.kind == "data":
                        result["data_frames"] += 1
                        result["data_records"].append(record)
                        if result["data_frames"] <= 20:
                            print(f"DATA {json.dumps(record)}")
                    elif frame.kind == "status":
                        result["status_frames"] += 1
                        result["last_status"] = record
                    elif frame.err_code == protocol.ERR_NONE:
                        result["error_none_frames"] += 1
                    else:
                        result["error_frames"] += 1
                    if frame.kind != "data" and diagnostic_preview < 20:
                        diagnostic_preview += 1
                        print(f"{frame.kind.upper()} {json.dumps(record)}")
            if clock() >= next_metrics:
                elapsed = clock() - started
                print(f"METRICS t={elapsed:.3f}s DATA={result['data_frames']} "
                      f"DATA_Hz={result['data_frames'] / elapsed:.3f} "
                      f"status={result['status_frames']} errors={result['error_frames']} "
                      f"lost_frames={result['lost_frames']} "
                      f"discarded_bytes={result['discarded_bytes']}")
                next_metrics = clock() + 1
    except (OSError, ImportError, ValueError, AttributeError) as error:
        result["failure"] = f"{type(error).__name__}: {error}"
    finally:
        if serial_port is not None:
            try:
                serial_port.close()
            except OSError as error:
                result["failure"] = result["failure"] or f"close failed: {error}"
        if raw_file is not None:
            try:
                if result["failure"] is None:
                    raw_file.flush()
                    os.fsync(raw_file.fileno())
            except OSError as error:
                result["failure"] = f"raw output finalization failed: {error}"
            finally:
                try:
                    raw_file.close()
                except OSError as error:
                    result["failure"] = result["failure"] or f"raw close failed: {error}"
            result["raw_complete"] = result["failure"] is None
    elapsed = max(0.0, clock() - started)
    result.update(elapsed_seconds=elapsed,
                  data_hz=result["data_frames"] / elapsed if elapsed else 0.0)
    if result["failure"] is None:
        if not result["valid_frames"]:
            result["failure"] = "no valid protocol frames received"
        elif args.require_status and not result["status_frames"]:
            result["failure"] = "required status frame missing"
        elif args.require_data and not result["data_frames"]:
            result["failure"] = "required DATA frame missing"
    if args.json_out:
        try:
            atomic_json(args.json_out, result)
        except (OSError, ValueError) as error:
            result["failure"] = f"JSON output failed: {error}"
    print("SUMMARY " + json.dumps({k: v for k, v in result.items()
                                   if k not in ("records", "data_records")},
                                  ensure_ascii=False))
    return 1 if result["failure"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
