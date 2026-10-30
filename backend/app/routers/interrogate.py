"""M3 接口：POST /api/interrogate。"""

from fastapi import APIRouter

from app.contracts.interrogate import InterrogateRequest, InterrogateResponse
from app.services.interrogate_service import interrogate_resume

router = APIRouter(tags=["interrogate"])


@router.post(
    "/api/interrogate",
    response_model=InterrogateResponse,
    response_model_exclude_none=True,
    responses={
        400: {"description": "请求缺少 parsed 或 raw_text"},
        422: {"description": "LLM 输出不符合拷问契约"},
        500: {"description": "LLM 超时或网络异常"},
    },
)

# 接收 M1 的 parsed 和 req，返回标红风险、追问和最差经历。
def interrogate(body: InterrogateRequest) -> InterrogateResponse:
    return interrogate_resume(body.parsed, body.req)
