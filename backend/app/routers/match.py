"""M2 接口：POST /api/match。"""

from fastapi import APIRouter

from app.contracts.match import MatchRequest, MatchResponse
from app.services.match_service import match_resume

router = APIRouter(tags=["match"])


@router.post(
    "/api/match",
    response_model=MatchResponse,
    response_model_exclude_none=True,
    responses={
        400: {"description": "请求缺少有效的简历或岗位要求"},
        422: {"description": "LLM 输出不符合匹配契约"},
        500: {"description": "LLM 超时或网络异常"},
    },
)
def match(body: MatchRequest) -> MatchResponse:
    """接收 M1 的 parsed 和 req，返回匹配分与三条差距。"""
    return match_resume(body.parsed, body.req)
