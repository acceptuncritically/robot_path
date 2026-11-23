import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping

from .errors import ConfigError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen-plus"
DEFAULT_TCP_HOST = "127.0.0.1"
DEFAULT_TCP_PORT = 9000
DEFAULT_SERIAL_PORT = "COM3"
DEFAULT_BAUDRATE = 115200
SUPPORTED_LLM_PROVIDERS = ("mock", "openai")
SUPPORTED_TRANSPORTS = ("mock", "tcp", "serial")


def read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ConfigError(f"读取环境变量文件失败: {exc}") from exc
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def _merged_env(env: Mapping[str, str] | None, env_file: Path | None) -> dict[str, str]:
    file_values = read_env_file(env_file or DEFAULT_ENV_FILE)
    os_values = dict(os.environ) if env is None else dict(env)
    merged = dict(file_values)
    merged.update(os_values)
    return merged


def _get_str(env: Mapping[str, str], key: str, default: str = "") -> str:
    value = env.get(key)
    if value is None:
        return default
    stripped = str(value).strip()
    return stripped or default


def _get_optional_str(env: Mapping[str, str], key: str) -> str | None:
    value = _get_str(env, key)
    return value or None


def _get_float(env: Mapping[str, str], key: str, default: float) -> float:
    value = env.get(key)
    if value is None or not str(value).strip():
        return default
    try:
        return float(str(value).strip())
    except ValueError as exc:
        raise ConfigError(f"{key} 必须是数字") from exc


def _get_int(env: Mapping[str, str], key: str, default: int) -> int:
    value = env.get(key)
    if value is None or not str(value).strip():
        return default
    try:
        return int(str(value).strip())
    except ValueError as exc:
        raise ConfigError(f"{key} 必须是整数") from exc


def _get_bool(env: Mapping[str, str], key: str, default: bool = False) -> bool:
    value = env.get(key)
    if value is None or not str(value).strip():
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on", "y")


@dataclass(frozen=True)
class LLMConfig:
    provider: str = "mock"
    base_url: str = DEFAULT_BASE_URL
    api_key: str = ""
    model: str = DEFAULT_MODEL
    timeout: float = 30.0
    max_retries: int = 2
    temperature: float = 0.0
    max_tokens: int = 128

    def __post_init__(self) -> None:
        if self.provider not in SUPPORTED_LLM_PROVIDERS:
            raise ConfigError(f"不支持的 LLM 提供方: {self.provider}")
        if self.timeout <= 0:
            raise ConfigError("LLM 超时必须大于 0")
        if self.max_retries < 0:
            raise ConfigError("LLM 重试次数不能为负数")
        if self.max_tokens <= 0:
            raise ConfigError("max_tokens 必须大于 0")

    def describe(self) -> str:
        if self.provider == "mock":
            return "MockLLM 离线模式"
        key_state = "已配置" if self.api_key else "未配置"
        return f"OpenAI 兼容接口 {self.base_url} 模型 {self.model} API Key {key_state}"


@dataclass(frozen=True)
class TransportConfig:
    kind: str = "mock"
    host: str = DEFAULT_TCP_HOST
    port: int = DEFAULT_TCP_PORT
    serial_port: str = DEFAULT_SERIAL_PORT
    baudrate: int = DEFAULT_BAUDRATE
    connect_timeout: float = 3.0

    def __post_init__(self) -> None:
        if self.kind not in SUPPORTED_TRANSPORTS:
            raise ConfigError(f"不支持的通信方式: {self.kind}")
        if not 1 <= self.port <= 65535:
            raise ConfigError("TCP 端口必须在 1 到 65535 之间")
        if self.baudrate <= 0:
            raise ConfigError("波特率必须大于 0")
        if self.connect_timeout <= 0:
            raise ConfigError("连接超时必须大于 0")


@dataclass(frozen=True)
class AppConfig:
    llm: LLMConfig
    transport: TransportConfig
    report_timeout: float = 5.0
    log_file: str | None = None
    verbose: bool = False

    def __post_init__(self) -> None:
        if self.report_timeout <= 0:
            raise ConfigError("等待回包超时必须大于 0")

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        env_file: str | Path | None = None,
    ) -> "AppConfig":
        file_path = Path(env_file) if env_file is not None else None
        merged = _merged_env(env, file_path)
        api_key = (
            _get_str(merged, "BRAIN_LLM_API_KEY")
            or _get_str(merged, "DASHSCOPE_API_KEY")
            or _get_str(merged, "OPENAI_API_KEY")
        )
        provider = _get_str(merged, "BRAIN_LLM_PROVIDER").lower()
        if not provider:
            provider = "openai" if api_key else "mock"
        llm = LLMConfig(
            provider=provider,
            base_url=_get_str(merged, "BRAIN_LLM_BASE_URL", DEFAULT_BASE_URL),
            api_key=api_key,
            model=_get_str(merged, "BRAIN_LLM_MODEL", DEFAULT_MODEL),
            timeout=_get_float(merged, "BRAIN_LLM_TIMEOUT", 30.0),
            max_retries=_get_int(merged, "BRAIN_LLM_MAX_RETRIES", 2),
            temperature=_get_float(merged, "BRAIN_LLM_TEMPERATURE", 0.0),
            max_tokens=_get_int(merged, "BRAIN_LLM_MAX_TOKENS", 128),
        )
        transport = TransportConfig(
            kind=_get_str(merged, "BRAIN_TRANSPORT", "mock").lower(),
            host=_get_str(merged, "BRAIN_TCP_HOST", DEFAULT_TCP_HOST),
            port=_get_int(merged, "BRAIN_TCP_PORT", DEFAULT_TCP_PORT),
            serial_port=_get_str(merged, "BRAIN_SERIAL_PORT", DEFAULT_SERIAL_PORT),
            baudrate=_get_int(merged, "BRAIN_BAUDRATE", DEFAULT_BAUDRATE),
            connect_timeout=_get_float(merged, "BRAIN_CONNECT_TIMEOUT", 3.0),
        )
        return cls(
            llm=llm,
            transport=transport,
            report_timeout=_get_float(merged, "BRAIN_REPORT_TIMEOUT", 5.0),
            log_file=_get_optional_str(merged, "BRAIN_LOG_FILE"),
            verbose=_get_bool(merged, "BRAIN_VERBOSE"),
        )

    def with_llm(self, **changes: object) -> "AppConfig":
        return replace(self, llm=replace(self.llm, **changes))

    def with_transport(self, **changes: object) -> "AppConfig":
        return replace(self, transport=replace(self.transport, **changes))

    def with_app(self, **changes: object) -> "AppConfig":
        return replace(self, **changes)