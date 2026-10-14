from __future__ import annotations

import sys
from dataclasses import replace

from PySide6.QtWidgets import QApplication

from pos_desktop.backend_client import PosBackendClient
from pos_desktop.config import PosConfig
from pos_desktop.database import PosDatabase
from pos_desktop.key_store import PosKeyStore, WindowsDpapiProtector
from pos_desktop.nfc import PcscTransport
from pos_desktop.service import PosService
from pos_desktop.simulator import AndroidHceSimulator, SimulatorTransport
from pos_desktop.ui import PosWindow


def main() -> int:
    config = PosConfig.from_environment()
    database = PosDatabase(config.database_path)
    database.migrate()
    profile = database.get_profile()
    if profile is not None:
        config = replace(
            config,
            merchant_id=profile["merchant_id"],
            terminal_id=profile["terminal_id"],
            pos_key_id=profile["key_id"],
        )
    key_store = PosKeyStore(database, WindowsDpapiProtector())
    simulator = AndroidHceSimulator() if config.simulator else None
    if simulator is not None:
        _, public_key, fingerprint = key_store.get_or_create(config.pos_key_id)
        simulator.trust_pos_key(config.pos_key_id, fingerprint, public_key)
        database.trust_wallet_key(
            simulator.wallet_key_id,
            simulator.wallet_fingerprint,
            simulator.wallet_id,
            simulator.wallet_public_key_b64,
        )
        transport_factory = lambda: SimulatorTransport(simulator)
    else:
        transport_factory = lambda: PcscTransport(config.reader_name)
    service = PosService(config, database, key_store, transport_factory)
    backend = PosBackendClient(config, key_store)
    application = QApplication(sys.argv)
    window = PosWindow(service, backend, simulator, offline_enabled=profile is not None)
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())

