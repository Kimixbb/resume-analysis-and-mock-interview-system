"""FastAPI 入口：注册 4 个接口路由。
运行：uvicorn backend.main:app --reload
"""
from fastapi import FastAPI

from backend import interrogator, matcher, parser, rewriter

app = FastAPI(title="简历压力测试与模拟面试系统", version="0.1.0")


@app.post("/parse", summary="M1 解析（A）")
def parse(payload: dict) -> dict:
    """TODO: 契约冻结后补 Pydantic 校验"""
    return parser.handle(payload)


@app.post("/match", summary="M2 匹配（B）")
def match(payload: dict) -> dict:
    return matcher.handle(payload)


@app.post("/interrogate", summary="M3 拷问（C）")
def interrogate(payload: dict) -> dict:
    return interrogator.handle(payload)


@app.post("/rewrite", summary="M4 重构（D）")
def rewrite(payload: dict) -> dict:
    return rewriter.handle(payload)
