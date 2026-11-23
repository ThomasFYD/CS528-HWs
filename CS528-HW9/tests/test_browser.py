"""An idle browser preconnection must leave the next HTTP request free to run."""
import http.client
import socket
import threading
import unittest

from web_server import Application, FileServer


class BrowserConnectionTest(unittest.TestCase):
    def test_demo_renders_with_idle_connection_open(self):
        with FileServer(("127.0.0.1", 0), Application("sample", None)) as server:
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                with socket.create_connection(server.server_address, timeout=2):
                    client = http.client.HTTPConnection(*server.server_address, timeout=2)
                    try:
                        client.request("GET", "/hw9-demo")
                        response = client.getresponse()
                        self.assertEqual(response.status, 200)
                        self.assertIn(b"Run requests", response.read())
                    finally:
                        client.close()
            finally:
                server.shutdown()
                thread.join()
