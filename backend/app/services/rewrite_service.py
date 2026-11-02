"""M4 STAR 重写：按 report_id 取原文、拼 Prompt、调 LLM、钳制复评分、回写。

与旧版 Mock 的区别：
- before 从简历里「目标经历的原文」取，不再写死一段假文本；
- 目标经历 = 请求的 experience_id，否则用报告落库时存的 weakest_experience_id；
- after / star / improved_score 由 LLM 生成，经 RewriteOutput 校验（缺 STAR → 422）。
"""

from __future__ import annotations

import json
from pathlib import Path

from app.contracts.parse import JDReq, ResumeParsed
from app.contracts.report_schema import (
    RewriteOutput,
    RewriteResponse,
    clamp_improved_score,
)
from app.core.db import get_jd, get_report, get_resume, get_session, set_report_rewrite
from app.core.errors import InvalidInput, NotFound
from app.core.llm import model_json
from app.services.report_service import load_interrogate

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "rewrite.md"


def _build_user_prompt(
    *,
    experience: dict,
    risks: list[dict],
    req: JDReq,
    score: int,
) -> str:
    """只喂与这次重写相关的材料：经历原文、落在该经历上的风险、JD 关键词。"""
    payload = {
        "experience": experience,
        "risks": [
            {
                "type": risk.get("type", ""),
                "text": risk.get("text", ""),
                "reason": risk.get("reason", ""),
            }
            for risk in risks
            if risk.get("experience_id") == experience.get("id")
        ],
        "jd": {
            "hard_skills": req.hard_skills,
            "responsibilities": req.responsibilities,
            "keywords": req.keywords,
        },
        "original_score": score,
    }
    return json.dumps(payload, ensure_ascii=False)


def generate_star_rewrite(
    report_id: int, experience_id: str | None = None
) -> RewriteResponse:
    """对最差（或指定）经历做 STAR 重写，更新 report.rewrite 并返回对比结果。

    错误语义（设计文档 §5.7）：报告不存在 → 404；经历不存在 → 400；
    LLM 输出缺 STAR → 422；网络异常 → 500，全部由全局异常处理器统一成
    {code, message}。
    """
    with get_session() as session:
        report = get_report(session, report_id)
        if report is None:
            raise NotFound("报告不存在")

        resume = get_resume(session, report.resume_id)
        jd = get_jd(session, report.jd_id)
        if resume is None or jd is None:
            raise NotFound("报告关联的简历或 JD 不存在")

        parsed = ResumeParsed.model_validate_json(resume.parsed_json)
        req = JDReq.model_validate_json(jd.req_json)
        experiences = [exp.model_dump() for exp in parsed.experiences]
        # M3 的三段结果统一存在 report.risks 这一个字段里
        interrogate = load_interrogate(report.risks)

        target_id = experience_id or interrogate["weakest_experience_id"]
        if not target_id:
            raise InvalidInput("报告没有 weakest_experience_id，请在请求里指定 experience_id")

        experience = next(
            (item for item in experiences if item.get("id") == target_id), None
        )
        if experience is None:
            raise InvalidInput(f"经历不存在：{target_id}")
        if not (experience.get("raw") or "").strip():
            raise InvalidInput(f"经历 {target_id} 没有原文，无法重写")

        result = model_json(
            system=PROMPT_PATH.read_text(encoding="utf-8"),
            user=_build_user_prompt(
                experience=experience,
                risks=interrogate["risks"],
                req=req,
                score=report.score,
            ),
            schema=RewriteOutput,
        )

        # before 永远取自简历原文，避免模型改写「改前」文本
        rewritten = RewriteResponse(
            before=experience["raw"],
            after=result.after,
            star=result.star,
            improved_score=clamp_improved_score(report.score, result.improved_score),
        )

        if set_report_rewrite(
            session,
            report_id,
            rewritten.model_dump_json(),
        ) is None:
            raise NotFound("报告不存在")

        return rewritten
