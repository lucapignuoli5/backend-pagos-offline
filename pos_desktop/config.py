from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PosConfig:
    database_path: Path
    merchant_id: str
    terminal_id: str
    pos_key_id: str
    backend_url: str
    reader_name: str | None
    simulator: bool

    @classmethod
    def from_environment(cls) -> "PosConfig":
        data_root = Path(os.getenv("LOCALAPPDATA", Path.home())) / "TFGOfflinePOS"
        return cls(
            database_path=Path(os.getenv("TFG_POS_DATABASE", data_root / "pos.sqlite")),
            merchant_id=os.getenv("TFG_POS_MERCHANT_ID", "merchant-demo"),
            terminal_id=os.getenv("TFG_POS_TERMINAL_ID", "terminal-demo"),
            pos_key_id=os.getenv("TFG_POS_KEY_ID", "pos-key-demo"),
            backend_url=os.getenv("TFG_BACKEND_URL", "http://127.0.0.1:8000"),
            reader_name=os.getenv("TFG_POS_READER") or None,
            simulator=os.getenv("TFG_POS_SIMULATOR", "0") == "1",
        )

