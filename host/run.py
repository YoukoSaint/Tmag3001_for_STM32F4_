"""TMAG3001 可视化应用入口。

用法:
    python host/run.py
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# 允许以 python host/run.py 直接运行。
sys.path.insert(0, str(Path(__file__).resolve().parent))


def main() -> int:
    from tmag_viewer.log_setup import setup_logging

    log_path = setup_logging("tmag_viewer", str(Path(__file__).resolve().parent / "logs"))
    logger = logging.getLogger(__name__)
    logger.info("Logging initialized: %s", log_path)

    from PyQt5.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    from tmag_viewer.main_window import MainWindow

    win = MainWindow()
    win.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
