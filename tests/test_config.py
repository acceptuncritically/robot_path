import tempfile
import unittest
from pathlib import Path

from brain.config import AppConfig, LLMConfig, TransportConfig, read_env_file
from brain.errors import ConfigError

MISSING_ENV_FILE = Path("这个文件不存在.env")


class EnvFileTests(unittest.TestCase):
    def test_parse_supported_lines(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(
                "# comment\nBRAIN_LLM_PROVIDER=openai\n"
                'export BRAIN_LLM_MODEL="qwen-plus"\n'
                "BRAIN_LLM_API_KEY='sk-test'\nNO_EQUALS\n",
                encoding="utf-8",
            )
            values = read_env_file(path)
        self.assertEqual(values["BRAIN_LLM_PROVIDER"], "openai")
        self.assertEqual(values["BRAIN_LLM_MODEL"], "qwen-plus")
        self.assertEqual(values["BRAIN_LLM_API_KEY"], "sk-test")
        self.assertNotIn("NO_EQUALS", values)

    def test_missing_file(self) -> None:
        self.assertEqual(read_env_file(MISSING_ENV_FILE), {})

    def test_utf8_bom(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_bytes(b"\xef\xbb\xbfBRAIN_TRANSPORT=tcp\nBRAIN_TCP_PORT=9002\n")
            config = AppConfig.from_env(env={}, env_file=path)
        self.assertEqual(config.transport.kind, "tcp")
        self.assertEqual(config.transport.port, 9002)


class AppConfigTests(unittest.TestCase):
    def test_defaults(self) -> None:
        config = AppConfig.from_env(env={}, env_file=MISSING_ENV_FILE)
        self.assertEqual(config.llm.provider, "mock")
        self.assertEqual(config.transport.kind, "mock")
        self.assertEqual(config.report_timeout, 5.0)
        self.assertIsNone(config.log_file)

    def test_api_key_selects_openai(self) -> None:
        config = AppConfig.from_env(env={"DASHSCOPE_API_KEY": "sk-auto"}, env_file=MISSING_ENV_FILE)
        self.assertEqual(config.llm.provider, "openai")
        self.assertEqual(config.llm.api_key, "sk-auto")

    def test_full_env_mapping(self) -> None:
        env = {
            "BRAIN_LLM_PROVIDER": "openai",
            "BRAIN_LLM_API_KEY": "sk-1",
            "BRAIN_LLM_BASE_URL": "http://127.0.0.1:11434/v1",
            "BRAIN_LLM_MODEL": "qwen2.5:7b",
            "BRAIN_LLM_TIMEOUT": "12.5",
            "BRAIN_LLM_MAX_RETRIES": "4",
            "BRAIN_TRANSPORT": "tcp",
            "BRAIN_TCP_HOST": "192.168.1.10",
            "BRAIN_TCP_PORT": "9123",
            "BRAIN_REPORT_TIMEOUT": "2.5",
            "BRAIN_LOG_FILE": "logs/brain.log",
            "BRAIN_VERBOSE": "true",
        }
        config = AppConfig.from_env(env=env, env_file=MISSING_ENV_FILE)
        self.assertEqual(config.llm.api_key, "sk-1")
        self.assertEqual(config.llm.base_url, "http://127.0.0.1:11434/v1")
        self.assertEqual(config.llm.model, "qwen2.5:7b")
        self.assertEqual(config.llm.timeout, 12.5)
        self.assertEqual(config.llm.max_retries, 4)
        self.assertEqual(config.transport.host, "192.168.1.10")
        self.assertEqual(config.transport.port, 9123)
        self.assertEqual(config.report_timeout, 2.5)
        self.assertEqual(config.log_file, "logs/brain.log")
        self.assertTrue(config.verbose)

    def test_os_env_overrides_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("BRAIN_TRANSPORT=tcp\nBRAIN_TCP_PORT=9001\n", encoding="utf-8")
            config = AppConfig.from_env(env={"BRAIN_TRANSPORT": "serial"}, env_file=path)
        self.assertEqual(config.transport.kind, "serial")
        self.assertEqual(config.transport.port, 9001)

    def test_invalid_values(self) -> None:
        bad_envs = (
            {"BRAIN_TRANSPORT": "udp"},
            {"BRAIN_TCP_PORT": "abc"},
            {"BRAIN_LLM_PROVIDER": "unknown"},
            {"BRAIN_REPORT_TIMEOUT": "0"},
            {"BRAIN_LLM_TIMEOUT": "-1"},
        )
        for env in bad_envs:
            with self.subTest(env=env), self.assertRaises(ConfigError):
                AppConfig.from_env(env=env, env_file=MISSING_ENV_FILE)

    def test_override_helpers(self) -> None:
        original = AppConfig.from_env(env={}, env_file=MISSING_ENV_FILE)
        updated = (
            original.with_llm(provider="openai", api_key="k")
            .with_transport(kind="tcp", port=1234)
            .with_app(report_timeout=2.0)
        )
        self.assertEqual(original.llm.provider, "mock")
        self.assertEqual(original.transport.kind, "mock")
        self.assertEqual(updated.llm.provider, "openai")
        self.assertEqual(updated.transport.kind, "tcp")
        self.assertEqual(updated.report_timeout, 2.0)

    def test_zero_report_timeout(self) -> None:
        with self.assertRaises(ConfigError):
            AppConfig(llm=LLMConfig(), transport=TransportConfig(), report_timeout=0)


if __name__ == "__main__":
    unittest.main()