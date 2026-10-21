class AppError(Exception):
    code = "INTERNAL_ERROR"
    status_code = 500
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)

class InvalidInput(AppError):      code, status_code = "INVALID_INPUT", 400 #输入非法
class NotFound(AppError):          code, status_code = "NOT_FOUND", 404 #资源不存在
class LLMOutputInvalid(AppError):  code, status_code = "LLM_OUTPUT_INVALID", 422 #模型返回格式不对
class LLMUpstreamError(AppError):  code, status_code = "LLM_UPSTREAM_ERROR", 500 #大模型上游报错，例如超时，无法连接
class DBError(AppError):           code, status_code = "DB_ERROR", 500 #数据库操作异常