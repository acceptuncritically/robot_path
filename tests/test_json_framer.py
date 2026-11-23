import json
import unittest

from brain.errors import ProtocolError
from brain.transport.json_framer import JsonFramer

C_OUTPUT = '===== 上报JSON =====\n{\n    "path": [],\n    "status": "fail"\n}\n'


class JsonFramerTests(unittest.TestCase):
    def test_complete_message(self) -> None:
        framer = JsonFramer()
        messages = framer.feed('{"status": "fail", "path": []}')
        self.assertEqual(len(messages), 1)
        self.assertEqual(json.loads(messages[0]), {"status": "fail", "path": []})

    def test_noise_is_discarded(self) -> None:
        framer = JsonFramer()
        messages = framer.feed(C_OUTPUT)
        self.assertEqual(len(messages), 1)
        self.assertEqual(json.loads(messages[0])["status"], "fail")

    def test_chunked_message(self) -> None:
        framer = JsonFramer()
        collected: list[str] = []
        for index in range(0, len(C_OUTPUT), 7):
            collected.extend(framer.feed(C_OUTPUT[index : index + 7]))
        self.assertEqual(len(collected), 1)
        self.assertEqual(json.loads(collected[0])["status"], "fail")

    def test_partial_message_waits_for_rest(self) -> None:
        framer = JsonFramer()
        self.assertEqual(framer.feed('{"status": "running", "path": ['), [])
        messages = framer.feed('{"x": 0, "y": 0}]}')
        self.assertEqual(len(messages), 1)

    def test_two_messages_in_one_chunk(self) -> None:
        framer = JsonFramer()
        messages = framer.feed('{"a": 1}{"b": 2}')
        self.assertEqual([json.loads(message) for message in messages], [{"a": 1}, {"b": 2}])

    def test_braces_inside_strings(self) -> None:
        framer = JsonFramer()
        messages = framer.feed('{"note": "}{", "ok": true}')
        self.assertEqual(len(messages), 1)
        self.assertEqual(json.loads(messages[0])["note"], "}{")

    def test_buffer_limit(self) -> None:
        framer = JsonFramer(max_buffer_size=32)
        with self.assertRaises(ProtocolError):
            framer.feed('{"status": "' + "a" * 100)

    def test_reset(self) -> None:
        framer = JsonFramer()
        framer.feed('{"status": ')
        framer.reset()
        messages = framer.feed('{"status": "fail", "path": []}')
        self.assertEqual(len(messages), 1)


if __name__ == "__main__":
    unittest.main()