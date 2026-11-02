"""全链路集成测试：parse → (match ∥ interrogate) → report → qa / rewrite → 回显。

测试负责人 D 的「串起来」用例：不起真实网络端口、不联网，
LLM 在 service 层用 fixtures 假实现替换，数据库用独立测试库。
验证的是「接口之间真的接得上」——上一段的输出能直接当下一段的输入。
"""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.contracts.report_schema import STARData, RewriteOutput
from app.services import rewrite_service

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_full_chain_parse_match_interrogate_report_qa_rewrite(client, fake_llm, monkeypatch):
    """一条链路跑到底，并逐段断言「下一段的输入 = 上一段的输出」。"""
    resume_text = _text("resume_bad.txt")
    jd_text = _text("jd_backend.txt")

    # ① parse
    parse_response = client.post(
        "/api/parse", json={"resume_text": resume_text, "jd_text": jd_text}
    )
    assert parse_response.status_code == 200, parse_response.text
    parsed = parse_response.json()
    assert parsed["parsed"]["raw_text"] == resume_text

    # ② match 与 ③ interrogate 并行（前端也是这样并发调用的）
    with ThreadPoolExecutor(max_workers=2) as pool:
        match_future = pool.submit(
            client.post, "/api/match", json={"parsed": parsed["parsed"], "req": parsed["req"]}
        )
        interrogate_future = pool.submit(
            client.post,
            "/api/interrogate",
            json={"parsed": parsed["parsed"], "req": parsed["req"]},
        )
        match_response = match_future.result()
        interrogate_response = interrogate_future.result()
    assert match_response.status_code == 200, match_response.text
    assert interrogate_response.status_code == 200, interrogate_response.text
    match_data = match_response.json()
    interrogate_data = interrogate_response.json()

    # ④ report：上一段的结果原样落库
    create_response = client.post(
        "/api/report",
        json={
            "resume_text": resume_text,
            "jd_text": jd_text,
            "parsed": parsed["parsed"],
            "req": parsed["req"],
            "score": match_data["score"],
            "gaps": match_data["gaps"],
            "risks": interrogate_data["risks"],
            "questions": interrogate_data["questions"],
            "weakest_experience_id": interrogate_data["weakest_experience_id"],
        },
    )
    assert create_response.status_code == 200, create_response.text
    report_id = create_response.json()["report_id"]

    # ⑤ 刷新回显：三表联查 + JSON 反序列化后字段完整
    report = client.get(f"/api/report/{report_id}").json()
    assert report["score"] == 58
    assert report["gaps"] == match_data["gaps"]
    assert report["risks"] == interrogate_data["risks"]
    assert report["questions"] == interrogate_data["questions"]
    assert report["weakest_experience_id"] == "proj_1"
    assert report["resume_text"] == resume_text
    assert report["jd_text"] == jd_text
    assert report["req"] == parsed["req"]

    # ⑥ qa：逐题提交，后端按 question_index 取原题
    for index, question in enumerate(report["questions"]):
        qa_response = client.post(
            "/api/qa",
            json={
                "report_id": report_id,
                "question_index": index,
                "answer": f"第 {index + 1} 题的具体回答：优化前 QPS 300，优化后 1200。",
            },
        )
        assert qa_response.status_code == 200, qa_response.text
        assert qa_response.json()["comment"].startswith("点评：")

    report = client.get(f"/api/report/{report_id}").json()
    assert [entry["question_index"] for entry in report["qa"]] == [0, 1, 2, 3]
    assert report["qa"][0]["question"] == report["questions"][0]["text"]

    # ⑦ rewrite：默认最差经历，复评分必须大于原分
    monkeypatch.setattr(
        rewrite_service,
        "model_json",
        lambda **kwargs: RewriteOutput(
            after="[S] 校园二手平台订单模块。[T] 独立承担接口层重构。"
            "[A] 批量查询 + Redis 缓存。[R] P99 从 480ms 降到 210ms。",
            star=STARData(S="校园二手平台订单模块", T="独立承担接口层重构", A="批量查询+缓存", R="P99 降 56%"),
            improved_score=70,
        ),
    )
    rewrite_response = client.post("/api/rewrite", json={"report_id": report_id})
    assert rewrite_response.status_code == 200, rewrite_response.text
    rewritten = rewrite_response.json()
    assert rewritten["improved_score"] > 58
    assert rewritten["before"] == report["parsed"]["experiences"][0]["raw"]

    # ⑧ 再回显一次：问答与重写都持久化了
    final = client.get(f"/api/report/{report_id}").json()
    assert final["rewrite"]["before"] == rewritten["before"]
    assert final["rewrite"]["improved_score"] == 70
    assert len(final["qa"]) == 4


def test_full_chain_survives_no_fatal_questions(client, fake_llm):
    """没有致命追问时 questions=[]，落库/回显/QA 流程依然闭合。"""
    fake_llm.interrogate_result.questions = []
    resume_text = _text("resume_good.txt")
    jd_text = _text("jd_backend.txt")
    parsed = client.post(
        "/api/parse",
        json={"resume_text": resume_text, "jd_text": jd_text},
    ).json()
    interrogate = client.post(
        "/api/interrogate", json={"parsed": parsed["parsed"], "req": parsed["req"]}
    ).json()
    assert interrogate["questions"] == []

    created = client.post(
        "/api/report",
        json={
            "resume_text": resume_text,
            "jd_text": jd_text,
            "parsed": parsed["parsed"],
            "req": parsed["req"],
            "score": 58,
            "gaps": json.loads((FIXTURES / "match.json").read_text(encoding="utf-8"))["gaps"],
            "risks": interrogate["risks"],
            "questions": interrogate["questions"],
            "weakest_experience_id": interrogate["weakest_experience_id"],
        },
    )
    assert created.status_code == 200, created.text

    report = client.get(f"/api/report/{created.json()['report_id']}").json()
    assert report["questions"] == []

    qa = client.post(
        "/api/qa",
        json={"report_id": report["report_id"], "question_index": 0, "answer": "有数字 123"},
    )
    assert qa.status_code == 400
    assert qa.json()["code"] == "INVALID_INPUT"
