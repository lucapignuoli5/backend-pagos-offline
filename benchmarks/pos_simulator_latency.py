from __future__ import annotations

import argparse
import json
import math
import platform
import statistics
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter_ns

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pos_desktop.config import PosConfig
from pos_desktop.database import PosDatabase
from pos_desktop.key_store import PosKeyStore
from pos_desktop.service import PosService
from pos_desktop.simulator import AndroidHceSimulator, SimulatorTransport


class BenchmarkProtector:
    """Protector reversible exclusivo del simulador; no representa DPAPI."""

    _PREFIX = b"benchmark-only:"

    def protect(self, value: bytes) -> bytes:
        return self._PREFIX + value[::-1]

    def unprotect(self, value: bytes) -> bytes:
        if not value.startswith(self._PREFIX):
            raise ValueError("Proteccion de benchmark invalida")
        return value[len(self._PREFIX):][::-1]


def nearest_rank(values: list[float], percentile: float) -> float:
    if not values or not 0 < percentile <= 1:
        raise ValueError("Muestra o percentil invalido")
    ordered = sorted(values)
    return ordered[math.ceil(percentile * len(ordered)) - 1]


def summarize(values: list[float]) -> dict[str, float]:
    return {
        "min": round(min(values), 6),
        "median": round(statistics.median(values), 6),
        "p95_nearest_rank": round(nearest_rank(values, 0.95), 6),
        "max": round(max(values), 6),
    }


def run(iterations: int, warmups: int) -> dict[str, object]:
    if iterations < 20:
        raise ValueError("Se requieren al menos veinte repeticiones")
    if warmups < 0:
        raise ValueError("La cantidad de calentamientos no puede ser negativa")

    with tempfile.TemporaryDirectory(prefix="tfg-pos-benchmark-") as directory:
        database_path = Path(directory) / "pos.sqlite"
        database = PosDatabase(database_path)
        simulator = AndroidHceSimulator()
        config = PosConfig(
            database_path=database_path,
            merchant_id="merchant-benchmark",
            terminal_id="terminal-benchmark",
            pos_key_id="pos-key-benchmark",
            backend_url="https://example.invalid",
            reader_name=None,
            simulator=True,
        )
        service = PosService(
            config,
            database,
            PosKeyStore(database, BenchmarkProtector()),
            lambda: SimulatorTransport(simulator),
        )
        _, public_key, fingerprint = service.key_store.get_or_create(config.pos_key_id)
        simulator.trust_pos_key(config.pos_key_id, fingerprint, public_key)
        database.trust_wallet_key(
            simulator.wallet_key_id,
            simulator.wallet_fingerprint,
            simulator.wallet_id,
            simulator.wallet_public_key_b64,
        )

        request_samples: list[float] = []
        receipt_ack_samples: list[float] = []
        total_samples: list[float] = []
        for index in range(warmups + iterations):
            operation = service.create_payment(12_345)
            started = perf_counter_ns()
            if service.deliver_request(operation.operation_id) != "REQUEST_RECEIVED":
                raise RuntimeError("La solicitud simulada no fue recibida")
            request_ms = (perf_counter_ns() - started) / 1_000_000

            # La confirmacion representa la accion humana y queda fuera de ambos intervalos.
            simulator.confirm(operation.operation_id)

            started = perf_counter_ns()
            if service.collect_receipt(operation.operation_id) != "LOCALLY_ACCEPTED":
                raise RuntimeError("El comprobante simulado no fue aceptado")
            receipt_ack_ms = (perf_counter_ns() - started) / 1_000_000
            if index >= warmups:
                request_samples.append(request_ms)
                receipt_ack_samples.append(receipt_ack_ms)
                total_samples.append(request_ms + receipt_ack_ms)

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "POS Python + transporte APDU/HCE simulado en memoria",
        "excludes": [
            "confirmacion humana",
            "espera entre acercamientos",
            "USB y PC/SC",
            "radiofrecuencia NFC",
            "Android real",
            "red y conciliacion backend",
        ],
        "iterations": iterations,
        "warmups_excluded": warmups,
        "percentile_method": "nearest-rank",
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "metrics_ms": {
            "request_delivery": summarize(request_samples),
            "receipt_and_ack": summarize(receipt_ack_samples),
            "electronic_total": summarize(total_samples),
        },
        "samples_ms": {
            "request_delivery": [round(value, 6) for value in request_samples],
            "receipt_and_ack": [round(value, 6) for value in receipt_ack_samples],
            "electronic_total": [round(value, 6) for value in total_samples],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Mide el flujo POS/HCE simulado sin espera humana")
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--warmups", type=int, default=3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run(args.iterations, args.warmups)
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")


if __name__ == "__main__":
    main()
