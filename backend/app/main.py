from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.db import create_all
from app.core.errors import AppError
from app.routers.parse import router as parse_router  # M1 解析（A 负责）
from app.routers.match import router as match_router  # M2 匹配（B 负责）

logger = logging.getLogger(__name__)

# 目前的函数都没有使用await，没有并发需求，但为了保持一致，都使用async
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    create_all() # 服务启动前创建表格（若无）
    yield
    # 服务关闭后暂无工作

app = FastAPI(
    title="简历诊断与模拟面试系统",
    version="0.1.0",
    description="简历 + JD 诊断、风险拷问与 STAR 重写。",
    lifespan=lifespan, # 生命周期管理
)

# 捕获定义的异常
@app.exception_handler(AppError) #error里面定义的父类异常，捕获这类异常，多态区分具体子对象
async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.code, "message": exc.message},
    )


# 捕获请求验证异常
@app.exception_handler(RequestValidationError)
async def handle_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    # 统一格式 {code, message}；把第一条错误自带的原因拼上去，
    # 例如「JSON decode error」（请求体不是合法 JSON）、「Field required」（少传了字段）。
    errors = exc.errors()
    first = errors[0] if errors else {}
    message = f"请求参数不合法：{first.get('msg', '')}"
    return JSONResponse(
        status_code=400,
        content={"code": "INVALID_INPUT", "message": message},
    )

# 捕获未定义的异常
@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "unhandled error: %s %s",
        request.method,
        request.url.path,
        exc_info=(type(exc), exc, exc.__traceback__),
    ) # 打印这类未知异常的具体信息
    return JSONResponse(
        status_code=500,
        content={"code": "INTERNAL_ERROR", "message": "服务异常，请重试"},
    )


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "根路径"}


# 各模块把自己的 router 注册进来
app.include_router(parse_router)
app.include_router(match_router)
