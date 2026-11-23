class BrainError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ConfigError(BrainError):
    pass


class LLMError(BrainError):
    pass


class LLMOutputError(BrainError):
    def __init__(self, message: str, raw_output: str = "") -> None:
        super().__init__(message)
        self.raw_output = raw_output


class TargetFormatError(LLMOutputError):
    pass


class TargetOutOfRangeError(LLMOutputError):
    pass


class TargetUncertainError(LLMOutputError):
    pass


class PlanningError(BrainError):
    def __init__(self, message: str, kind: str, attempts: int = 0, raw_output: str = "") -> None:
        super().__init__(message)
        self.kind = kind
        self.attempts = attempts
        self.raw_output = raw_output


class ProtocolError(BrainError):
    def __init__(self, message: str, raw: str = "") -> None:
        super().__init__(message)
        self.raw = raw


class MalformedReportError(ProtocolError):
    pass


class UnknownStatusError(ProtocolError):
    def __init__(self, status: object, raw: str = "") -> None:
        super().__init__(f"未知状态: {status!r}", raw)
        self.status = status


class InvalidReportPathError(ProtocolError):
    pass


class InvalidTargetCommandError(ProtocolError):
    pass


class TransportError(BrainError):
    pass


class TransportClosedError(TransportError):
    pass


class SessionBusyError(BrainError):
    pass


class SessionClosedError(BrainError):
    pass