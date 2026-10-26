"""Exercise the installed driver's real authentication code without a server.

Only packet transport is mocked. RSA encryption and authentication dispatch run
normally, including the full-auth path that failed on the VM with PyMySQL 1.2.3.
These protocol tests supplement, but do not replace, live Cloud SQL verification.
"""
import unittest
from unittest.mock import Mock

import pymysql
from pymysql.constants import CLIENT
from pymysql.protocol import MysqlPacket
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


class MySQLAuthenticationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.public_key = key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)

    def connection(self, packets, known_key=False):
        # No socket is opened. This flag configures only the synthetic transport;
        # production continues using the Cloud SQL connector's encrypted socket.
        conn = pymysql.Connection(user="hw5-test", password="test-only-password",
                                  charset="utf8mb4", defer_connect=True, ssl_disabled=True)
        self.addCleanup(conn._force_close)
        conn.server_version = "8.4.0"
        conn.server_capabilities = (CLIENT.PROTOCOL_41 | CLIENT.SECURE_CONNECTION |
                                    CLIENT.PLUGIN_AUTH | CLIENT.PLUGIN_AUTH_LENENC_CLIENT_DATA)
        conn._auth_plugin_name = "caching_sha2_password"
        conn.salt = b"01234567890123456789"
        conn._secure = False
        conn.server_public_key = self.public_key if known_key else None
        conn.write_packet = Mock()
        conn._read_packet = Mock(side_effect=[MysqlPacket(data, "utf8") for data in packets])
        return conn

    def test_fast_auth_completes(self):
        conn = self.connection([b"\x01\x03", b"\x00\x00\x00\x02\x00\x00\x00"])
        conn._request_authentication()
        self.assertEqual(conn._read_packet.call_count, 2)

    def test_full_rsa_auth_with_known_key_completes(self):
        conn = self.connection([b"\x01\x04", b"\x00\x00\x00\x02\x00\x00\x00"], known_key=True)
        conn._request_authentication()
        self.assertEqual(conn._read_packet.call_count, 2)
        self.assertEqual(len(conn.write_packet.call_args.args[0]), 256)

    def test_full_rsa_auth_requests_key_and_completes(self):
        conn = self.connection([b"\x01\x04", b"\x01" + self.public_key,
                                b"\x00\x00\x00\x02\x00\x00\x00"])
        conn._request_authentication()
        self.assertEqual(conn._read_packet.call_count, 3)
        self.assertEqual(conn.write_packet.call_args_list[1].args[0], b"\x02")
        self.assertEqual(len(conn.write_packet.call_args.args[0]), 256)

    def test_full_auth_rejects_server_access_denied(self):
        conn = self.connection([b"\x01\x04", b"\xff\x15\x04#28000Access denied for test user"], known_key=True)
        with self.assertRaises(pymysql.OperationalError) as failure:
            conn._request_authentication()
        self.assertEqual(failure.exception.args[0], 1045)


if __name__ == "__main__":
    unittest.main()
