"""M4 接口测试（真实服务 + 独立测试库，只在 LLM / DB 边界打桩）。

覆盖设计文档 §5.5–§5.8：
- POST /api/report：三表落库、返回三个 id、嵌套校验 400、DB 异常 500 + 回滚；
- GET  /api/report/{id}：§5.6 全字段回显、404；
- POST /api/qa：按 question_index 取原题、1–1000 字校验、越界 400、404、同题覆盖；
- POST /api/rewrite：默认最差经历、显式经历、score 钳制、404/400/422；
- 错误体统一为 {code, message}，不再是 {detail}。
"""

import json

from sqlalchemy import text

from app.contracts.report_schema import STARData
from app.core import db
from app.core.errors import DBError


def _count_rows(table: str) -> int:
    with db.engine.connect() as connection:
        return connection.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar_one()


# ==================== POST /api/report ====================
def test_create_report_returns_three_ids(client, report_payload):
    response = client.post("/api/report", json=report_payload)

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"report_id", "resume_id", "jd_id"}
    assert all(isinstance(value, int) for value in body.values())
    assert (_count_rows("resume"), _count_rows("jd"), _count_rows("report")) == (1, 1, 1)


def test_created_report_is_readable_by_get(client, seeded_report, report_payload):
    response = client.get(f"/api/report/{seeded_report['report_id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["report_id"] == seeded_report["report_id"]
    assert body["score"] == report_payload["score"]
    assert body["resume_text"] == report_payload["resume_text"]
    assert body["questions"] == report_payload["questions"]
    assert body["weakest_experience_id"] == "proj_1"


def test_create_report_rejects_non_three_gaps(client, report_payload):
    report_payload["gaps"] = report_payload["gaps"][:2]

    response = client.post("/api/report", json=report_payload)

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_INPUT"


def test_create_report_rejects_score_out_of_range(client, report_payload):
    report_payload["score"] = 120

    response = client.post("/api/report", json=report_payload)

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_INPUT"


def test_create_report_rejects_unknown_weakest_experience(client, report_payload):
    report_payload["weakest_experience_id"] = "not_exist"

    response = client.post("/api/report", json=report_payload)

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_INPUT"


def test_create_report_rolls_back_when_db_fails(client, report_payload, monkeypatch):
    from app.services import report_service

    def broken(*args, **kwargs):
        raise DBError("数据库操作失败")

    # 服务层才是事务边界：这里让创建动作直接抛错，验证接口返回 500 且不回半条数据
    monkeypatch.setattr(report_service, "create_report_record", broken)

    response = client.post("/api/report", json=report_payload)

    assert response.status_code == 500
    assert response.json()["code"] == "DB_ERROR"
    # 事务回滚，三张表都没有半成品
    assert (_count_rows("resume"), _count_rows("jd"), _count_rows("report")) == (0, 0, 0)


def test_create_report_stores_m3_results_in_risks_column(client, report_payload):
    """不新增数据库列：M3 的 risks / questions / weakest_experience_id 合并存 report.risks。"""
    response = client.post("/api/report", json=report_payload)
    assert response.status_code == 200, response.text

    with db.engine.connect() as connection:
        stored = connection.execute(
            text("SELECT risks FROM report WHERE id = :id"),
            {"id": response.json()["report_id"]},
        ).scalar_one()
    payload = json.loads(stored)
    assert set(payload) == {"risks", "questions", "weakest_experience_id"}
    assert payload["questions"] == report_payload["questions"]
    assert payload["weakest_experience_id"] == "proj_1"


# ==================== GET /api/report/{id} ====================
def test_get_report_returns_all_contract_fields(client, seeded_report, report_payload):
    response = client.get(f"/api/report/{seeded_report['report_id']}")

    assert response.status_code == 200
    body = response.json()
    expected = {
        "report_id",
        "resume_text",
        "parsed",
        "jd_text",
        "req",
        "score",
        "gaps",
        "risks",
        "questions",
        "weakest_experience_id",
        "qa",
        "rewrite",
        "created_at",
    }
    assert set(body) == expected
    assert body["gaps"] == report_payload["gaps"]
    assert body["risks"] == report_payload["risks"]
    assert body["parsed"]["raw_text"] == report_payload["resume_text"]
    assert len(body["questions"]) == 4
    assert body["qa"] is None and body["rewrite"] is None
    assert body["created_at"]  # 非空时间字符串


def test_get_missing_report_returns_unified_404(client):
    response = client.get("/api/report/99999")

    assert response.status_code == 404
    assert response.json() == {"code": "NOT_FOUND", "message": "报告不存在"}


# ==================== POST /api/qa ====================
def test_qa_uses_backend_question_and_returns_comment(client, seeded_report):
    response = client.post(
        "/api/qa",
        json={
            "report_id": seeded_report["report_id"],
            "question_index": 0,
            "answer": "优化前 QPS 300、P99 480ms，优化后 QPS 1200、P99 210ms。",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"comment"}
    assert body["comment"].startswith("点评：")

    report = client.get(f"/api/report/{seeded_report['report_id']}").json()
    assert len(report["qa"]) == 1
    entry = report["qa"][0]
    assert entry["question_index"] == 0
    assert entry["question"] == report["questions"][0]["text"]
    assert entry["answer"].startswith("优化前 QPS 300")


def test_qa_vague_answer_points_to_missing_facts(client, seeded_report):
    response = client.post(
        "/api/qa",
        json={
            "report_id": seeded_report["report_id"],
            "question_index": 0,
            "answer": "大概吧",
        },
    )

    assert response.status_code == 200
    assert "缺具体事实" in response.json()["comment"]


def test_qa_same_question_overwrites_instead_of_appending(client, seeded_report):
    report_id = seeded_report["report_id"]
    url = "/api/qa"
    first = client.post(
        url, json={"report_id": report_id, "question_index": 1, "answer": "第一次回答，少于三十字"}
    )
    second = client.post(
        url,
        json={
            "report_id": report_id,
            "question_index": 1,
            "answer": "第二次回答：优化前 QPS 300，优化后 1200，P99 从 480ms 降到 210ms。",
        },
    )

    assert first.status_code == second.status_code == 200
    report = client.get(f"/api/report/{report_id}").json()
    assert len(report["qa"]) == 1
    assert report["qa"][0]["question_index"] == 1
    assert "QPS 300" in report["qa"][0]["answer"]


def test_qa_out_of_range_index_returns_400(client, seeded_report):
    response = client.post(
        "/api/qa",
        json={"report_id": seeded_report["report_id"], "question_index": 99, "answer": "有数字 123"},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_INPUT"


def test_qa_blank_answer_returns_400(client, seeded_report):
    response = client.post(
        "/api/qa",
        json={"report_id": seeded_report["report_id"], "question_index": 0, "answer": "   "},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_INPUT"


def test_qa_too_long_answer_returns_400(client, seeded_report):
    response = client.post(
        "/api/qa",
        json={
            "report_id": seeded_report["report_id"],
            "question_index": 0,
            "answer": "数" * 1001,
        },
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_INPUT"


def test_qa_missing_report_returns_404(client):
    response = client.post(
        "/api/qa", json={"report_id": 99999, "question_index": 0, "answer": "有数字 123"}
    )

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


# ==================== POST /api/rewrite ====================
def _fake_rewrite(monkeypatch, *, improved_score: int = 40):
    """返回固定重写结果的假 LLM，避免联网。"""
    from app.contracts.report_schema import RewriteOutput
    from app.services import rewrite_service

    result = RewriteOutput(
        after="[S] 校园二手平台订单模块。[T] 独立负责接口层重构。"
        "[A] 合并批量查询并引入缓存。[R] P99 从 480ms 降到 210ms。",
        star=STARData(S="校园二手平台订单模块", T="独立负责接口层重构", A="合并查询+缓存", R="P99 降 56%"),
        improved_score=improved_score,
    )
    monkeypatch.setattr(rewrite_service, "model_json", lambda **kwargs: result)
    return result


def test_rewrite_defaults_to_weakest_experience(client, seeded_report, report_payload, monkeypatch):
    _fake_rewrite(monkeypatch)
    report = client.get(f"/api/report/{seeded_report['report_id']}").json()
    weakest = next(
        exp for exp in report_payload["parsed"]["experiences"]
        if exp["id"] == report["weakest_experience_id"]
    )

    response = client.post("/api/rewrite", json={"report_id": seeded_report["report_id"]})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["before"] == weakest["raw"]  # before 是简历原文，不是 Mock 文本
    assert body["after"].startswith("[S]")
    assert set(body["star"]) == {"S", "T", "A", "R"}
    # 原分 58，模型给了 40 → 钳制为 58+5
    assert body["improved_score"] == 63

    stored = client.get(f"/api/report/{seeded_report['report_id']}").json()
    assert stored["rewrite"]["improved_score"] == 63
    assert stored["rewrite"]["before"] == weakest["raw"]


def test_rewrite_uses_explicit_experience_id(client, seeded_report, report_payload, monkeypatch):
    _fake_rewrite(monkeypatch, improved_score=90)
    work = next(exp for exp in report_payload["parsed"]["experiences"] if exp["id"] == "work_1")

    response = client.post(
        "/api/rewrite",
        json={"report_id": seeded_report["report_id"], "experience_id": "work_1"},
    )

    assert response.status_code == 200
    assert response.json()["before"] == work["raw"]
    assert response.json()["improved_score"] == 90


def test_rewrite_unknown_experience_returns_400(client, seeded_report):
    response = client.post(
        "/api/rewrite",
        json={"report_id": seeded_report["report_id"], "experience_id": "not_exist"},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_INPUT"


def test_rewrite_missing_report_returns_404(client):
    response = client.post("/api/rewrite", json={"report_id": 99999})

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


def test_rewrite_llm_missing_star_returns_422(client, seeded_report, monkeypatch):
    from app.core.errors import LLMOutputInvalid
    from app.services import rewrite_service

    def fake(**kwargs):
        raise LLMOutputInvalid("模型输出不符合约定")

    monkeypatch.setattr(rewrite_service, "model_json", fake)

    response = client.post("/api/rewrite", json={"report_id": seeded_report["report_id"]})

    assert response.status_code == 422
    assert response.json()["code"] == "LLM_OUTPUT_INVALID"


# ==================== OpenAPI ====================
def test_m4_routes_are_documented(client):
    paths = client.get("/openapi.json").json()["paths"]

    assert "/api/report" in paths
    assert "/api/report/{report_id}" in paths
    assert "/api/qa" in paths
    assert "/api/rewrite" in paths
    assert "404" in paths["/api/report/{report_id}"]["get"]["responses"]
