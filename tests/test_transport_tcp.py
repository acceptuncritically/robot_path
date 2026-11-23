import json
import socket
import threading
import unittest

from brain.errors import InvalidReportPathError, TransportClosedError, TransportError
from brain.protocol import Target, build_target_message, parse_robot_report
from brain.transport.tcp_transport import TcpTransport
from tools.mock_c_server import MockCServer


class GbkBannerServer:
    def __init__(self) -> None:
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.bind(("127.0.0.1", 0))
        self._server_socket.listen(1)
        self.port = self._server_socket.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def start(self) -> "GbkBannerServer":
        self._thread.start()
        return self

    def _serve(self) -> None:
        connection, _ = self._server_socket.accept()
        with connection:
            report = {"path": [{"x": 0, "y": 0}], "status": "running"}
            payload = "上报JSON".encode("gbk") + b"\n" + json.dumps(report, indent=4).encode("utf-8") + b"\n"
            connection.sendall(payload)
        self._server_socket.close()

    def stop(self) -> None:
        try:
            self._server_socket.close()
        except OSError:
            pass
        self._thread.join(timeout=2.0)


class TcpTransportIntegrationTests(unittest.TestCase):
    def start_server(self, **kwargs: object) -> tuple[MockCServer, int]:
        server = MockCServer(host="127.0.0.1", port=0, verbose=False, **kwargs)
        port = server.start()
        self.addCleanup(server.stop)
        return server, port

    def connect(self, port: int) -> TcpTransport:
        transport = TcpTransport("127.0.0.1", port, connect_timeout=2.0)
        transport.open()
        self.addCleanup(transport.close)
        return transport

    def test_round_trip_running(self) -> None:
        _, port = self.start_server()
        transport = self.connect(port)
        transport.send_message(build_target_message(Target(5, 5)))
        raw = transport.recv_message(5.0)
        self.assertIsNotNone(raw)
        self.assertTrue(raw.startswith("{"))
        report = parse_robot_report(raw)
        self.assertEqual(report.status, "running")
        self.assertEqual((report.points[-1].x, report.points[-1].y), (5, 5))

    def test_round_trip_fail(self) -> None:
        _, port = self.start_server(mode="fail")
        transport = self.connect(port)
        transport.send_message(build_target_message(Target(5, 5)))
        report = parse_robot_report(transport.recv_message(5.0))
        self.assertEqual(report.status, "fail")
        self.assertEqual(report.points, ())

    def test_timeout_returns_none(self) -> None:
        _, port = self.start_server(mode="timeout")
        transport = self.connect(port)
        transport.send_message(build_target_message(Target(3, 2)))
        self.assertIsNone(transport.recv_message(0.3))

    def test_malformed_report(self) -> None:
        _, port = self.start_server(mode="malformed")
        transport = self.connect(port)
        transport.send_message(build_target_message(Target(3, 2)))
        raw = transport.recv_message(5.0)
        with self.assertRaises(InvalidReportPathError):
            parse_robot_report(raw)

    def test_connect_refused(self) -> None:
        server = MockCServer(host="127.0.0.1", port=0, verbose=False)
        port = server.start()
        server.stop()
        transport = TcpTransport("127.0.0.1", port, connect_timeout=0.5)
        with self.assertRaises(TransportError):
            transport.open()

    def test_detects_peer_closed(self) -> None:
        server, port = self.start_server()
        transport = self.connect(port)
        transport.send_message(build_target_message(Target(0, 0)))
        self.assertIsNotNone(transport.recv_message(5.0))
        server.stop()
        with self.assertRaises(TransportClosedError):
            transport.recv_message(2.0)
        self.assertFalse(transport.is_open)
        with self.assertRaises(TransportError):
            transport.send_message(build_target_message(Target(0, 0)))

    def test_send_before_open(self) -> None:
        transport = TcpTransport("127.0.0.1", 1)
        with self.assertRaises(TransportError):
            transport.send_message('{"target_x":0,"target_y":0}')

    def test_gbk_noise_does_not_break_parsing(self) -> None:
        server = GbkBannerServer().start()
        self.addCleanup(server.stop)
        transport = TcpTransport("127.0.0.1", server.port, connect_timeout=2.0)
        transport.open()
        self.addCleanup(transport.close)
        raw = transport.recv_message(3.0)
        self.assertIsNotNone(raw)
        report = parse_robot_report(raw)
        self.assertEqual(report.status, "running")
        self.assertEqual(report.points[-1].x, 0)


if __name__ == "__main__":
    unittest.main()