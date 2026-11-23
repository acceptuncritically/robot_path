import logging
import sys
from pathlib import Path

from .errors import ConfigError

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%H:%M:%S"


def setup_logging(verbose: bool = False, log_file: str | None = None) -> logging.Logger:
    logger = logging.getLogger("brain")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    console_handler = logging.StreamHandler(stream=sys.stderr)
    console_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    logger.addHandler(console_handler)
    if log_file:
        path = Path(log_file)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ConfigError(f"创建日志目录失败: {exc}") from exc
        try:
            file_handler = logging.FileHandler(path, encoding="utf-8")
        except OSError as exc:
            raise ConfigError(f"打开日志文件失败: {exc}") from exc
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
        logger.addHandler(file_handler)
    return logger