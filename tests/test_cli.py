import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from brain.cli import build_llm_client, main
from brain.config import AppConfig
from brain.errors import ConfigError
from brain.llm.mock_client import MockLLMClient

MISSING_ENV_FILE = Path("这个文件不存在.env")
MOCK_ENV = {"BRAIN_LLM_PROVIDER": "mock", "BRAIN_TRANSPORT": "mock"}


class CliTests(unittest.TestCase):
    def run_cli(self, argv: list[str]) -> tuple[int, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(argv)
        return code, stdout.getvalue()

    def test_selftest(self) -> None:
        code, output = self.run_cli(["--selftest"])
        self.assertEqual(code, 0)
        self.assertIn("自检结果", output)
        self.assertIn("PASS", output)

    def test_once_success(self) -> None:
        with mock.patch.dict(os.environ, MOCK_ENV, clear=False):
            code, output = self.run_cli(["--once", "去迷宫右下角"])
        self.assertEqual(code, 0)
        self.assertIn("已规划路线", output)

    def test_once_obstacle_still_completes(self) -> None:
        with mock.patch.dict(os.environ, MOCK_ENV, clear=False):
            code, output = self.run_cli(["--once", "去(2,1)"])
        self.assertEqual(code, 0)
        self.assertIn("阻挡", output)

    def test_once_uncertain_returns_nonzero(self) -> None:
        with mock.patch.dict(os.environ, MOCK_ENV, clear=False):
            code, output = self.run_cli(["--once", "随便走走吧"])
        self.assertEqual(code, 1)
        self.assertIn("无法确定目标", output)

    def test_version(self) -> None:
        stdout = io.StringIO()
        with self.assertRaises(SystemExit) as context, contextlib.redirect_stdout(stdout):
            main(["--version"])
        self.assertEqual(context.exception.code, 0)
        self.assertIn("1.0.0", stdout.getvalue())

    def test_build_llm_mock(self) -> None:
        config = AppConfig.from_env(env={"BRAIN_LLM_PROVIDER": "mock"}, env_file=MISSING_ENV_FILE)
        self.assertIsInstance(build_llm_client(config), MockLLMClient)

    def test_build_llm_openai_without_key(self) -> None:
        config = AppConfig.from_env(
            env={"BRAIN_LLM_PROVIDER": "openai", "BRAIN_LLM_API_KEY": ""},
            env_file=MISSING_ENV_FILE,
        )
        with self.assertRaises(ConfigError):
            build_llm_client(config)

    def test_invalid_log_file_returns_two(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            blocker = Path(directory) / "blocker"
            blocker.write_text("not a directory", encoding="utf-8")
            log_path = blocker / "brain.log"
            with mock.patch.dict(os.environ, MOCK_ENV, clear=False):
                code, _ = self.run_cli(["--once", "去(5,5)", "--log-file", str(log_path)])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()