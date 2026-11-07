"""Streaming CSV export published only after a successful atomic close."""
from __future__ import annotations

import csv
import logging
import os
from pathlib import Path
import tempfile

logger = logging.getLogger(__name__)


class CsvWriter:
    def __init__(self, path):
        self.path = Path(path)
        self._file = None
        self._writer = None
        self._temp = None
        self._rows = 0

    def open(self):
        if self._file is not None:
            raise RuntimeError("CSV writer is already open")
        descriptor, name = tempfile.mkstemp(prefix=".tmag-", suffix=".tmp", dir=self.path.parent)
        self._temp = Path(name)
        self._rows = 0
        try:
            try:
                self._file = os.fdopen(descriptor, "w", encoding="utf-8", newline="")
            except BaseException:
                os.close(descriptor)
                raise
            self._writer = csv.writer(self._file)
            self._writer.writerow(["X_mT", "Y_mT", "Z_mT", "T_C"])
        except BaseException:
            self.abort()
            raise

    def write(self, x: float, y: float, z: float, t: float):
        if self._file is None:
            raise RuntimeError("CSV writer is not open")
        try:
            self._writer.writerow([f"{value:.4f}" for value in (x, y, z, t)])
            self._rows += 1
        except BaseException:
            logger.exception("FILE_IO op=write kind=data path=%s rows=%d", self.path, self._rows)
            self.abort()
            raise

    def abort(self):
        """Discard an incomplete export; never replace the destination."""
        stream, temporary = self._file, self._temp
        self._file = self._writer = self._temp = None
        try:
            if stream is not None:
                stream.close()
        except Exception:
            logger.exception("FILE_IO op=close kind=data path=%s rows=%d", self.path, self._rows)
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    logger.exception("FILE_IO op=cleanup kind=data path=%s rows=%d", self.path, self._rows)

    def close(self):
        if self._file is None:
            return
        operation = "write"
        try:
            self._file.flush()
            os.fsync(self._file.fileno())
            self._file.close()
            logger.info("FILE_IO op=write kind=data path=%s rows=%d", self.path, self._rows)
            operation = "rename"
            os.replace(self._temp, self.path)
            logger.info("FILE_IO op=rename kind=data path=%s rows=%d", self.path, self._rows)
            self._file = self._writer = self._temp = None
        except BaseException:
            logger.exception("FILE_IO op=%s kind=data path=%s rows=%d", operation, self.path, self._rows)
            self.abort()
            raise
