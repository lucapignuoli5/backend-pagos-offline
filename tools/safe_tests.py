"""Run tests with disposable storage and no external network/payment services."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from contextlib import contextmanager
from datetime import datetime, timezone
import ipaddress
import os
from pathlib import Path
import secrets
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def is_loopback(host: str) -> bool:
    try:
        return host == 'localhost' or ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@contextmanager
def deny_external_network():
    """Guard Python socket APIs; this is not an OS firewall."""
    with ExitStack() as guards:
        original_connect = socket.socket.connect
        original_sendto = socket.socket.sendto

        def connect(sock, address):
            if not isinstance(address, tuple) or not is_loopback(address[0]):
                raise RuntimeError('External network blocked by test runner')
            return original_connect(sock, address)

        def sendto(sock, data, *arguments):
            address = arguments[-1] if arguments else None
            if not isinstance(address, tuple) or not is_loopback(address[0]):
                raise RuntimeError('External UDP blocked by test runner')
            return original_sendto(sock, data, *arguments)

        def resolver(original):
            def resolve(host, *args, **kwargs):
                if not is_loopback(host):
                    raise RuntimeError('External DNS blocked by test runner')
                return original(host, *args, **kwargs)
            return resolve

        guards.enter_context(patch.object(socket.socket, 'connect', connect))
        guards.enter_context(patch.object(socket.socket, 'sendto', sendto))
        guards.enter_context(patch.object(socket.socket, 'connect_ex', lambda *args: (_ for _ in ()).throw(RuntimeError('connect_ex blocked'))))
        for name in ('getaddrinfo', 'gethostbyname', 'gethostbyname_ex', 'gethostbyaddr'):
            guards.enter_context(patch.object(socket, name, resolver(getattr(socket, name))))
        yield


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--legacy-clock', action='store_true', help='Freeze only legacy v2 synchronization fixtures')
    args = parser.parse_args()
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(ROOT))
    with tempfile.TemporaryDirectory(prefix='tfg-safe-tests-') as directory, ExitStack() as stack:
        os.environ.update({
            'DATABASE_URL': 'sqlite:///' + str(Path(directory) / 'backend.sqlite'),
            'JWT_SECRET_KEY': secrets.token_hex(32),
            'MERCADO_PAGO_ENABLED': 'false', 'NGROK_ENABLED': 'false',
            'DEMO_SEED_ENABLED': 'false', 'QT_QPA_PLATFORM': 'offscreen',
            'PYTHONDONTWRITEBYTECODE': '1',
        })
        previous_directory = Path.cwd()
        os.chdir(directory)
        stack.callback(os.chdir, previous_directory)
        stack.enter_context(deny_external_network())
        if args.legacy_clock:
            import sync_v2

            class LegacyClock(datetime):
                @classmethod
                def now(cls, tz=None):
                    value = cls(2026, 10, 13, 15, 0, 30, tzinfo=timezone.utc)
                    return value.astimezone(tz) if tz else value.replace(tzinfo=None)

            stack.enter_context(patch.object(sync_v2, 'datetime', LegacyClock))
        suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
