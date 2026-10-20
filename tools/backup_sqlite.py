"""Create an explicit, consistent SQLite backup before a schema upgrade.

Stop the backend/POS first. This tool does not import either application.
"""

from __future__ import annotations

import argparse
import sqlite3
from contextlib import closing
from pathlib import Path
from urllib.parse import quote


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    destination = args.destination.resolve(strict=False)
    if not source.is_file() or destination == source or destination.exists():
        parser.error("Origen inexistente o destino ya existente")
    if not destination.parent.is_dir():
        parser.error("El directorio de destino debe existir")
    uri = "file:" + quote(source.as_posix(), safe="/:\\") + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as original:
        if original.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            parser.error("La base de origen requiere revision antes de copiar")
        try:
            destination.open("xb").close()
            with closing(sqlite3.connect(destination)) as backup:
                original.backup(backup)
                if backup.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise RuntimeError("La copia no supero la comprobacion SQLite")
        except Exception:
            destination.unlink(missing_ok=True)
            raise
    print(f"Copia SQLite creada: {destination}")


if __name__ == "__main__":
    main()
