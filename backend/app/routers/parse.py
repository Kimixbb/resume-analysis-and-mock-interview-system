"""M1 的接口入口：POST /api/parse。

router 保持很薄：只做「收请求 → 调服务 → 还响应」，
校验、拼 Prompt、调 LLM 等业务都在 services/parse_service.py 里。
"""

from fastapi import APIRouter

from app.contracts.parse import ParseRequest, ParseResponse
from app.services.parse_service import parse_resume

router = APIRouter(tags=["parse"])


# 注意用同步 def 而不是 async def：
# model_json 里是阻塞式 httpx.post，FastAPI 会把同步接口丢进线程池执行，
# 不会卡住事件循环，这样 match / interrogate 才能真正并行处理。
# responses= 把 400/422/500 登记进 /docs，联调时不会显示 Undocumented。
@router.post(
    "/api/parse",
    response_model=ParseResponse,
    responses={
        400: {"description": "输入不合法：字段缺失或请求体不是合法 JSON"},
        422: {"description": "LLM 输出不符合契约"},
        500: {"description": "LLM 超时或网络异常"},
    },
)
def parse(body: ParseRequest) -> ParseResponse:
    """解析简历与 JD：两段文本进，parsed + req 出。"""
    return parse_resume(body.resume_text, body.jd_text)
