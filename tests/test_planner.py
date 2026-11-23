import unittest

from brain.errors import LLMError, PlanningError
from brain.llm.base import LLMClient
from brain.llm.mock_client import MockLLMClient
from brain.planning.planner import TargetPlanner
from brain.protocol import Target


class FailingLLM(LLMClient):
    name = "failing"

    def __init__(self, message: str = "网络不可达") -> None:
        self.message = message
        self.calls = 0

    def complete(self, system_prompt: str, user_message: str) -> str:
        self.calls += 1
        raise LLMError(self.message)


class PlannerTests(unittest.TestCase):
    def test_success_first_attempt(self) -> None:
        client = MockLLMClient(scripted_outputs=['{"target_x": 3, "target_y": 2}'])
        planner = TargetPlanner(client, max_retries=2)
        result = planner.plan("去(3,2)")
        self.assertEqual(result.target, Target(3, 2))
        self.assertEqual(result.attempts, 1)
        self.assertEqual(len(client.calls), 1)

    def test_retry_after_bad_output(self) -> None:
        client = MockLLMClient(scripted_outputs=["垃圾输出", '{"target_x": 4, "target_y": 4}'])
        planner = TargetPlanner(client, max_retries=2)
        result = planner.plan("去(4,4)")
        self.assertEqual(result.target, Target(4, 4))
        self.assertEqual(result.attempts, 2)
        self.assertIn("输出不可用", getattr(client, "calls")[1])

    def test_retry_after_out_of_range(self) -> None:
        client = MockLLMClient(
            scripted_outputs=['{"target_x": 9, "target_y": 9}', '{"target_x": 2, "target_y": 1}']
        )
        planner = TargetPlanner(client, max_retries=2)
        result = planner.plan("去(9,9)")
        self.assertEqual(result.target, Target(2, 1))
        self.assertEqual(result.attempts, 2)

    def test_exhausted_retries_format(self) -> None:
        client = MockLLMClient(scripted_outputs=["垃圾"] * 3)
        planner = TargetPlanner(client, max_retries=2)
        with self.assertRaises(PlanningError) as context:
            planner.plan("去(3,2)")
        self.assertEqual(context.exception.kind, "format")
        self.assertEqual(context.exception.attempts, 3)

    def test_exhausted_retries_range(self) -> None:
        client = MockLLMClient(scripted_outputs=['{"target_x": 9, "target_y": 9}'] * 3)
        planner = TargetPlanner(client, max_retries=2)
        with self.assertRaises(PlanningError) as context:
            planner.plan("去(9,9)")
        self.assertEqual(context.exception.kind, "range")

    def test_uncertain_no_retry(self) -> None:
        client = MockLLMClient(scripted_outputs=['{"target_x": -1, "target_y": -1}'])
        planner = TargetPlanner(client, max_retries=2)
        with self.assertRaises(PlanningError) as context:
            planner.plan("随便走走吧")
        self.assertEqual(context.exception.kind, "uncertain")
        self.assertEqual(len(client.calls), 1)

    def test_llm_error(self) -> None:
        client = FailingLLM()
        planner = TargetPlanner(client, max_retries=2)
        with self.assertRaises(PlanningError) as context:
            planner.plan("去右下角")
        self.assertEqual(context.exception.kind, "llm")
        self.assertIn("网络不可达", context.exception.message)

    def test_empty_instruction(self) -> None:
        client = MockLLMClient()
        planner = TargetPlanner(client, max_retries=2)
        with self.assertRaises(PlanningError) as context:
            planner.plan("   ")
        self.assertEqual(context.exception.kind, "format")
        self.assertEqual(context.exception.attempts, 0)
        self.assertEqual(client.calls, [])

    def test_negative_max_retries(self) -> None:
        with self.assertRaises(ValueError):
            TargetPlanner(MockLLMClient(), max_retries=-1)


if __name__ == "__main__":
    unittest.main()