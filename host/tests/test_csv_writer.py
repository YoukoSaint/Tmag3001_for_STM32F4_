import csv
import logging

import pytest

from tmag_viewer.csv_writer import CsvWriter


def test_atomic_stream_and_format(tmp_path, caplog):
    target = tmp_path / "data.csv"
    writer = CsvWriter(target)
    with caplog.at_level(logging.INFO):
        writer.open()
        assert not target.exists()
        writer.write(1, -2.34567, 0, 25.12345)
        writer.close()
        writer.close()
    assert list(csv.reader(target.open(encoding="utf-8", newline=""))) == [
        ["X_mT", "Y_mT", "Z_mT", "T_C"],
        ["1.0000", "-2.3457", "0.0000", "25.1234"],
    ]
    assert list(tmp_path.iterdir()) == [target]
    assert "FILE_IO" in caplog.text and "rows=1" in caplog.text


def test_misuse_and_abort(tmp_path):
    target = tmp_path / "data.csv"
    target.write_text("old", encoding="utf-8")
    writer = CsvWriter(target)
    with pytest.raises(RuntimeError):
        writer.write(1, 2, 3, 4)
    writer.open()
    with pytest.raises(RuntimeError):
        writer.open()
    writer.write(1, 2, 3, 4)
    assert target.read_text() == "old"
    writer.abort()
    writer.close()
    assert target.read_text() == "old"
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize("operation", ["flush", "fsync", "replace", "write", "fdopen"])
def test_failure_preserves_original_and_cleans_temp(tmp_path, monkeypatch, operation):
    import tmag_viewer.csv_writer as module

    target = tmp_path / "data.csv"
    target.write_text("old", encoding="utf-8")
    writer = CsvWriter(target)

    def fail(*args, **kwargs):
        raise OSError("injected " + operation)

    if operation == "fdopen":
        descriptors = []

        def fail_fdopen(descriptor, *args, **kwargs):
            descriptors.append(descriptor)
            fail()

        monkeypatch.setattr(module.os, "fdopen", fail_fdopen)
        with pytest.raises(OSError, match="injected"):
            writer.open()
        with pytest.raises(OSError):
            module.os.fstat(descriptors[0])
    else:
        writer.open()
        descriptor = writer._file
        if operation in ("fsync", "replace"):
            monkeypatch.setattr(module.os, operation, fail)
        elif operation == "write":
            monkeypatch.setattr(writer, "_writer", type("Broken", (), {"writerow": fail})())
        else:
            class BrokenFlush:
                def flush(self):
                    fail()

                def close(self):
                    descriptor.close()
            writer._file = BrokenFlush()
        with pytest.raises(OSError, match="injected"):
            if operation == "write":
                writer.write(1, 2, 3, 4)
            else:
                writer.close()
        writer.close()
        with pytest.raises(RuntimeError):
            writer.write(1, 2, 3, 4)
        assert descriptor.closed
    assert target.read_text() == "old"
    assert list(tmp_path.iterdir()) == [target]
