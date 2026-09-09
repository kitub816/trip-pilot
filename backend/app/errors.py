"""Safe public errors; raw dependency exceptions are not API messages."""
class AppError(Exception):
    status_code = 500
    code = "INTERNAL_ERROR"
    message = "服务内部错误，请稍后重试"
    def __init__(self) -> None:
        super().__init__(self.message)

class ConfigurationError(AppError):
    status_code = 503
    code = "CONFIGURATION_ERROR"
    message = "服务配置不完整，请检查地图密钥、LLM密钥和模型配置"

class UpstreamError(AppError):
    status_code = 502
    code = "UPSTREAM_ERROR"
    message = "外部服务调用失败，请稍后重试"

class UpstreamTimeout(AppError):
    status_code = 504
    code = "UPSTREAM_TIMEOUT"
    message = "外部服务响应超时，请稍后重试"

class PlanParseError(AppError):
    status_code = 502
    code = "PLAN_PARSE_ERROR"
    message = "无法解析有效的旅行计划，请重试"

class FeatureUnavailable(AppError):
    status_code = 503
    code = "FEATURE_NOT_READY"
    message = "该功能的结果解析尚未完成"

class ServiceBusy(AppError):
    status_code = 503
    code = "SERVICE_BUSY"
    message = "规划服务正在处理其他请求，请稍后重试"


def upstream_failure(exc: BaseException) -> UpstreamError | UpstreamTimeout:
    """SDK wrappers preserve cause/context; classify without reading error text."""
    from httpx import TimeoutException
    from requests import Timeout
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (TimeoutError, TimeoutException, Timeout)):
            return UpstreamTimeout()
        current = current.__cause__ or current.__context__
    return UpstreamError()
