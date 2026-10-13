import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication
except ImportError:
    QApplication = None

from pos_desktop.backend_client import PosBackendClient
from pos_desktop.config import PosConfig
from pos_desktop.database import PosDatabase
from pos_desktop.key_store import PosKeyStore
from pos_desktop.service import PosService
from pos_desktop.simulator import AndroidHceSimulator, SimulatorTransport


class UiTestProtector:
    def protect(self, value: bytes) -> bytes:
        return b"ui:" + value

    def unprotect(self, value: bytes) -> bytes:
        return value[3:]


@unittest.skipUnless(QApplication is not None, "PySide6 no instalado")
class PosUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_all_required_pages_construct_without_starting_network_or_reader(self):
        from pos_desktop.ui import PosWindow

        with tempfile.TemporaryDirectory() as directory:
            config = PosConfig(
                Path(directory) / "ui.sqlite", "merchant-1", "terminal-1", "pos-key-1",
                "http://127.0.0.1:8000", None, True,
            )
            database = PosDatabase(config.database_path)
            key_store = PosKeyStore(database, UiTestProtector())
            simulator = AndroidHceSimulator()
            service = PosService(
                config, database, key_store, lambda: SimulatorTransport(simulator),
                now=lambda: datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc),
            )
            window = PosWindow(service, PosBackendClient(config, key_store), simulator)
            self.assertEqual(window.stack.count(), 4)
            self.assertIn("POS", window.windowTitle())
            window.close()


if __name__ == "__main__":
    unittest.main()
