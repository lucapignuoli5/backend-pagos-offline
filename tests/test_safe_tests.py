import socket
import unittest
from tools.safe_tests import deny_external_network


class SafeRunnerTests(unittest.TestCase):
    def test_external_tcp_udp_and_dns_are_blocked(self):
        with deny_external_network():
            with socket.socket() as tcp, socket.socket(type=socket.SOCK_DGRAM) as udp:
                with self.assertRaises(RuntimeError):
                    tcp.connect(('198.51.100.1', 443))
                with self.assertRaises(RuntimeError):
                    udp.sendto(b'never-transmitted', ('198.51.100.1', 53))
            for resolve in (socket.getaddrinfo, socket.gethostbyname, socket.gethostbyname_ex, socket.gethostbyaddr):
                with self.assertRaises(RuntimeError):
                    resolve('payments.example.invalid', 443) if resolve is socket.getaddrinfo else resolve('payments.example.invalid')

    def test_loopback_remains_available_for_local_integration(self):
        with deny_external_network(), socket.socket() as listener, socket.socket() as client:
            listener.bind(('127.0.0.1', 0))
            listener.listen(1)
            client.connect(listener.getsockname())
            peer, _ = listener.accept()
            with peer:
                client.sendall(b'x')
                self.assertEqual(peer.recv(1), b'x')
