import unittest

from brain.text_json import iter_json_objects


class TextJsonTests(unittest.TestCase):
    def test_single_object(self) -> None:
        values = list(iter_json_objects('{"a": 1}'))
        self.assertEqual(values, [{"a": 1}])

    def test_noise_before_and_after(self) -> None:
        text = '日志行\n{"status": "running"}\n结束'
        values = list(iter_json_objects(text))
        self.assertEqual(values, [{"status": "running"}])

    def test_multiple_objects(self) -> None:
        values = list(iter_json_objects('{"a": 1}\n{"b": 2}'))
        self.assertEqual(values, [{"a": 1}, {"b": 2}])

    def test_braces_inside_string(self) -> None:
        text = '{"note": "a } b", "value": 1}'
        values = list(iter_json_objects(text))
        self.assertEqual(values, [{"note": "a } b", "value": 1}])

    def test_invalid_then_valid(self) -> None:
        text = '{broken {"a": 1}'
        values = list(iter_json_objects(text))
        self.assertEqual(values, [{"a": 1}])

    def test_no_object(self) -> None:
        self.assertEqual(list(iter_json_objects("没有 JSON")), [])

    def test_empty_text(self) -> None:
        self.assertEqual(list(iter_json_objects("")), [])


if __name__ == "__main__":
    unittest.main()