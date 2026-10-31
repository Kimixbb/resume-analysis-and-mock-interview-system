from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.db import create_all
from app.core.errors import AppError

# ==================== 1. 导入各模块的 Router ====================
from app.routers.parse import router as parse_router            # M1 解析（A 负责）
from app.routers.match import router as match_router            # M2 匹配（B 负责）
from app.routers.interrogate import router as interrogate_router # M3 拷问（C 负责）
from app.routers.report_router import router as report_router   # M4 报告与重写（D 负责）

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    create_all() # 服务启动前创建表格（若无）
    yield
    # 服务关闭后暂无工作

app = FastAPI(
    title="简历诊断与模拟面试系统",
    version="0.1.0",
    description="简历 + JD 诊断、风险拷问与 STAR 重写。",
    lifespan=lifespan,
)

# ==================== 2. 注册所有 Router ====================
app.include_router(parse_router)
app.include_router(match_router)
app.include_router(interrogate_router)
app.include_router(report_router) # 你的 M4 接口终于注册进来了！

# ==================== 3. 全局异常处理 ====================
@app.exception_handler(AppError)
async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.code, "message": exc.message},
    )

@app.exception_handler(RequestValidationError)
async def handle_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    errors = exc.errors()
    first = errors[0] if errors else {}
    message = f"请求参数不合法：{first.get('msg', '')}"
    return JSONResponse(
        status_code=400,
        content={"code": "INVALID_INPUT", "message": message},
    )

@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "unhandled error: %s %s",
        request.method,
        request.url.path,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return JSONResponse(
        status_code=500,
        content={"code": "INTERNAL_ERROR", "message": "服务异常，请重试"},
    )

@app.get("/")
def root() -> dict[str, str]:
    return {"message": "根路径"}