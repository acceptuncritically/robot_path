import unittest

from brain.errors import ProtocolError, TransportError
from brain.grid import OBSTACLES, find_path
from brain.protocol import PathPoint, STATUS_FAIL, STATUS_RUNNING, Target, parse_robot_report
from brain.transport.mock_transport import MockTransport


class GridTests(unittest.TestCase):
    def test_path_to_corner(self) -> None:
        points = find_path(Target(5, 5))
        self.assertIsNotNone(points)
        self.assertEqual(points[0], PathPoint(0, 0))
        self.assertEqual(points[-1], PathPoint(5, 5))
        for previous, current in zip(points, points[1:]):
            distance = abs(previous.x - current.x) + abs(previous.y - current.y)
            self.assertEqual(distance, 1)
        for point in points:
            self.assertNotIn((point.x, point.y), OBSTACLES)

    def test_obstacle_target_has_no_path(self) -> None:
        self.assertIsNone(find_path(Target(2, 1)))

    def test_start_equals_goal(self) -> None:
        self.assertEqual(find_path(Target(0, 0)), [PathPoint(0, 0)])

    def test_custom_start(self) -> None:
        points = find_path(Target(5, 5), start=(3, 2))
        self.assertIsNotNone(points)
        self.assertEqual(points[0], PathPoint(3, 2))


class MockTransportTests(unittest.TestCase):
    def open_transport(self, **kwargs: object) -> MockTransport:
        transport = MockTransport(**kwargs)
        transport.open()
        self.addCleanup(transport.close)
        return transport

    def test_normal_running_report(self) -> None:
        transport = self.open_transport()
        transport.send_message('{"target_x":5,"target_y":5}\n')
        raw = transport.recv_message(0.1)
        self.assertIsNotNone(raw)
        report = parse_robot_report(raw)
        self.assertEqual(report.status, STATUS_RUNNING)
        self.assertEqual(report.points[-1], PathPoint(5, 5))
        self.assertIn("===== 上报JSON =====", raw)

    def test_obstacle_target_fail(self) -> None:
        transport = self.open_transport()
        transport.send_message('{"target_x":2,"target_y":1}\n')
        report = parse_robot_report(transport.recv_message(0.1))
        self.assertEqual(report.status, STATUS_FAIL)
        self.assertEqual(report.points, ())

    def test_timeout_scenario(self) -> None:
        transport = self.open_transport(scenario="timeout")
        transport.send_message('{"target_x":5,"target_y":5}\n')
        self.assertIsNone(transport.recv_message(0.1))

    def test_malformed_scenario(self) -> None:
        transport = self.open_transport(scenario="malformed")
        transport.send_message('{"target_x":5,"target_y":5}\n')
        raw = transport.recv_message(0.1)
        with self.assertRaises(ProtocolError):
            parse_robot_report(raw)

    def test_unknown_status_scenario(self) -> None:
        transport = self.open_transport(scenario="unknown_status")
        transport.send_message('{"target_x":5,"target_y":5}\n')
        report = None
        with self.assertRaises(ProtocolError):
            report = parse_robot_report(transport.recv_message(0.1))
        self.assertIsNone(report)

    def test_send_error_scenario(self) -> None:
        transport = self.open_transport(scenario="send_error")
        with self.assertRaises(TransportError):
            transport.send_message('{"target_x":5,"target_y":5}\n')

    def test_send_before_open(self) -> None:
        transport = MockTransport()
        with self.assertRaises(TransportError):
            transport.send_message('{"target_x":5,"target_y":5}\n')

    def test_invalid_command_recorded(self) -> None:
        transport = self.open_transport()
        transport.send_message('{"target_x":9,"target_y":2}\n')
        self.assertEqual(len(transport.invalid_messages), 1)
        self.assertEqual(transport.received_targets, [])
        self.assertIsNone(transport.recv_message(0.1))

    def test_scripted_reports(self) -> None:
        transport = self.open_transport(scripted_reports=[None, '{"status":"fail","path":[]}'])
        transport.send_message('{"target_x":5,"target_y":5}\n')
        self.assertIsNone(transport.recv_message(0.1))
        transport.send_message('{"target_x":4,"target_y":4}\n')
        report = parse_robot_report(transport.recv_message(0.1))
        self.assertEqual(report.status, STATUS_FAIL)

    def test_drain_keeps_scripted_reports(self) -> None:
        transport = self.open_transport(scripted_reports=['{"status":"fail","path":[]}'])
        self.assertEqual(transport.drain(), [])
        self.assertEqual(len(transport._scripted_reports), 1)

    def test_close_is_idempotent(self) -> None:
        transport = MockTransport()
        transport.open()
        transport.close()
        transport.close()
        self.assertFalse(transport.is_open)

    def test_invalid_scenario(self) -> None:
        with self.assertRaises(ValueError):
            MockTransport(scenario="unknown")


if __name__ == "__main__":
    unittest.main()