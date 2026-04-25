"""Application entry point for Loci."""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    """Launch the Loci desktop application."""

    from PySide6.QtWidgets import QApplication

    from loci.services.storage_service import StorageService
    from loci.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    storage = StorageService.default()
    window = MainWindow(storage=storage)
    window.resize(1500, 900)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
