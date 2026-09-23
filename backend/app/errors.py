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

class ModelRateLimit(AppError):
    status_code = 429
    code = "MODEL_RATE_LIMIT"
    message = "模型服务请求过于频繁，请稍后重试"

class ModelCallBudgetExceeded(AppError):
    status_code = 429
    code = "MODEL_CALL_BUDGET_EXCEEDED"
    message = "本次规划已达到模型调用上限，请稍后重试"

class PlanParseError(AppError):
    status_code = 502
    code = "PLAN_PARSE_ERROR"
    message = "无法解析有效的旅行计划，请重试"

class PlanValidationError(AppError):
    status_code = 422
    code = "PLAN_VALIDATION_ERROR"
    message = "旅行计划未满足确定性约束，请调整输入后重试"

class FeatureUnavailable(AppError):
    status_code = 503
    code = "FEATURE_NOT_READY"
    message = "该功能的结果解析尚未完成"

class ServiceBusy(AppError):
    status_code = 503
    code = "SERVICE_BUSY"
    message = "规划服务正在处理其他请求，请稍后重试"

class ToolArgumentError(AppError):
    status_code = 422
    code = "TOOL_ARGUMENT_ERROR"
    message = "工具参数不符合要求"

class ToolProtocolError(UpstreamError):
    code = "TOOL_PROTOCOL_ERROR"
    message = "外部工具返回了无法识别的数据"

class ToolRateLimit(UpstreamError):
    code = "TOOL_RATE_LIMIT"
    message = "外部工具请求过于频繁，请稍后重试"

class NoCandidates(AppError):
    status_code = 503
    code = "NO_CANDIDATES"
    message = "未获取到有效景点，暂时无法生成行程"


class PersistenceUnavailable(AppError):
    status_code = 503
    code = "PERSISTENCE_UNAVAILABLE"
    message = "计划存储暂时不可用，请稍后重试"


class PlanNotFound(AppError):
    status_code = 404
    code = "PLAN_NOT_FOUND"
    message = "未找到指定旅行计划"


class PlanVersionConflict(AppError):
    status_code = 409
    code = "PLAN_VERSION_CONFLICT"
    message = "旅行计划已被更新，请刷新后重试"


class CheckpointUnavailable(AppError):
    status_code = 503
    code = "CHECKPOINT_UNAVAILABLE"
    message = "工作流恢复未启用，请重新发起规划"


class PlanNotResumable(AppError):
    status_code = 409
    code = "PLAN_NOT_RESUMABLE"
    message = "该旅行计划当前无法继续，请重新发起规划"


class PlanAccessDenied(AppError):
    status_code = 403
    code = "PLAN_ACCESS_DENIED"
    message = "无权访问该旅行计划"


class WorkflowVersionUnsupported(AppError):
    status_code = 409
    code = "WORKFLOW_VERSION_UNSUPPORTED"
    message = "工作流版本不兼容，请重新发起规划"


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


class ConstraintExtractionError(AppError):
    status_code = 422
    code = "CONSTRAINT_EXTRACTION_ERROR"
    message = "未能提取可靠约束，请修改描述或手动填写结构化字段"
