"""pytest 共享配置：import 路径、独立测试库、报告样例、LLM 假实现。

配置（API Key、模型名）不在这里伪造，测试直接依赖项目根目录的 .env——
和正式运行用的是同一份配置。
所有会真正调用 LLM 的测试都必须用 monkeypatch 替换掉各 service 里的
model_json，所以 tests 全套不联网、不消耗 token。

数据库：每个用例都切到独立的 SQLite 文件，绝不碰 backend/app.db 的正式数据。
文件优先放在 backend/tests/.tmp/（进 .gitignore）；如果工作区权限不允许
在该目录建文件（例如沙箱只放开项目根目录），就自动退到项目根目录。
"""

import os
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

# conftest.py 位于 backend/tests/，parents[1] 就是 backend/。
# 把 backend/ 加进 sys.path，测试文件里才能 import app.xxx。
BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

# app.core.config 在被 import 时就会读取 .env，缺了会报一长串看不懂的
# pydantic 校验错误，所以在这里提前检查，缺了就给出一句人话提示。
ENV_FILE = BACKEND_DIR.parent / ".env"  # 项目根目录下的 .env
if not ENV_FILE.exists():
    raise SystemExit(
        "测试需要项目根目录下的 .env 文件：\n"
        "请先把 .env.example 复制为 .env（占位值即可，测试不会真的调 LLM），"
        "然后再运行 pytest。"
    )

PROJECT_ROOT = BACKEND_DIR.parent
FIXTURES_DIR = BACKEND_DIR / "fixtures"


def _temp_is_writable() -> bool:
    """系统临时目录是否可写；某些受限沙箱里它存在但建不了文件。"""
    if not os.access(tempfile.gettempdir(), os.W_OK):
        return False
    try:
        probe = Path(tempfile.gettempdir()) / f".dsh-probe-{uuid.uuid4().hex}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def pytest_configure(config: pytest.Config) -> None:
    """系统临时目录不可写时，把 pytest 的 basetemp 挪到项目内（tmp_path 随之可用）。"""
    if config.option.basetemp or _temp_is_writable():
        return
    basetemp = PROJECT_ROOT / ".pytest-tmp"
    basetemp.mkdir(parents=True, exist_ok=True)
    config.option.basetemp = str(basetemp)


def pytest_sessionstart(session) -> None:
    """把 Streamlit AppTest 的临时目录从系统 TEMP 挪到项目内。

    Streamlit 的 `testing/v1/app_test.py` 在 import 时就建了一个模块级
    TemporaryDirectory，进程退出时由 weakref finalizer 清理；受限沙箱里
    系统 TEMP 下 mkdtemp 建出的目录连 listdir 都被拒绝，清理会抛
    PermissionError，让 pytest 在全部用例通过后仍以 1 退出。
    这里换成项目内可写目录，并解除原对象的 finalizer，保证退出码干净。
    """
    if _temp_is_writable():
        return
    try:
        from streamlit.testing.v1 import app_test
    except ImportError:  # 没装 Streamlit 时不影响后端测试
        return

    workdir = PROJECT_ROOT / ".pytest-tmp" / "apptest"
    workdir.mkdir(parents=True, exist_ok=True)

    class _WorkspaceTempDir:
        name = str(workdir)

    original = getattr(app_test, "TMP_DIR", None)
    app_test.TMP_DIR = _WorkspaceTempDir()
    if original is not None and hasattr(original, "_finalizer"):
        original._finalizer.detach()  # 不再尝试删系统 TEMP 下的只读目录

    # 兜底：第三方库（如 Streamlit skills 探测）仍可能在系统 TEMP 下建
    # TemporaryDirectory，退出时同样会因沙箱限制清理失败。这里吞掉清理异常，
    # 让这类清理只留警告、不再把进程退出码改成 1。
    if not getattr(tempfile, "_dsh_guarded", False):
        original_rmtree = tempfile._rmtree

        def guarded_rmtree(path, ignore_errors=False, onerror=None):
            try:
                return original_rmtree(path, ignore_errors=True, onerror=None)
            except OSError:
                return None

        tempfile._rmtree = guarded_rmtree
        tempfile._dsh_guarded = True


def _test_db_path() -> Path:
    """选一个当前进程确实可写的目录来放测试库。"""
    for directory in (BACKEND_DIR / "tests" / ".tmp", PROJECT_ROOT):
        try:
            directory.mkdir(parents=True, exist_ok=True)
            probe = directory / f".probe-{uuid.uuid4().hex}"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return directory / f"report-test-{uuid.uuid4().hex}.db"
        except OSError:
            continue
    raise RuntimeError("找不到可写目录来创建测试数据库")


@pytest.fixture(autouse=True)
def isolated_database():
    """每个用例一个全新的 SQLite 库，并替换掉 db.engine / db.SessionLocal。

    service / router 都是通过 `db.get_session` 拿连接，而 `get_session`
    内部读的是模块级 `SessionLocal`，所以这里替换后，整条链路都会落到
    测试库，正式库 `backend/app.db` 不会被写入。
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.core import db
    from app.core.models import Base

    path = _test_db_path()
    engine = create_engine(
        f"sqlite:///{path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    original_engine, original_session = db.engine, db.SessionLocal

    Base.metadata.create_all(bind=engine)
    db.engine = engine
    db.SessionLocal = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False
    )
    try:
        yield db
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
        db.engine = original_engine
        db.SessionLocal = original_session
        path.unlink(missing_ok=True)


@pytest.fixture
def client():
    """进程内直调 FastAPI 应用；进入 with 时才会执行 lifespan 建表。"""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def report_payload() -> dict:
    """backend/fixtures/report.json 里符合 POST /api/report 契约的那部分。"""
    import json

    raw = json.loads((FIXTURES_DIR / "report.json").read_text(encoding="utf-8"))
    return {
        key: raw[key]
        for key in (
            "resume_text",
            "jd_text",
            "parsed",
            "req",
            "score",
            "gaps",
            "risks",
            "questions",
            "weakest_experience_id",
        )
    }


@pytest.fixture
def seeded_report(client, report_payload) -> dict:
    """先落一份报告，返回三个 id；需要 report_id 的用例都复用它。"""
    response = client.post("/api/report", json=report_payload)
    assert response.status_code == 200, response.text
    return response.json()


class FakeLLM:
    """按 schema 类型返回对应 fixtures 的假模型，完全离线。"""

    def __init__(self) -> None:
        from app.contracts.interrogate import InterrogateResult
        from app.contracts.match import MatchResult
        from app.contracts.parse import ParseResult

        self.parse_result = ParseResult.model_validate_json(
            (FIXTURES_DIR / "parsed.json").read_text(encoding="utf-8")
        )
        self.match_result = MatchResult.model_validate_json(
            (FIXTURES_DIR / "match.json").read_text(encoding="utf-8")
        )
        self.interrogate_result = InterrogateResult.model_validate_json(
            (FIXTURES_DIR / "interrogate.json").read_text(encoding="utf-8")
        )
        self.calls: list[str] = []

    def __call__(self, system, user, schema, temperature=0.2):
        from app.contracts.interrogate import InterrogateResult
        from app.contracts.match import MatchResult
        from app.contracts.parse import ParseResult

        self.calls.append(schema.__name__)
        if schema is ParseResult:
            # 模拟 LLM 不返回 raw_text，由后端用请求原文覆盖
            return self.parse_result.model_copy(deep=True)
        if schema is MatchResult:
            return self.match_result.model_copy(deep=True)
        if schema is InterrogateResult:
            return self.interrogate_result.model_copy(deep=True)
        raise AssertionError(f"未预期的 LLM schema：{schema}")


@pytest.fixture
def fake_llm(monkeypatch) -> FakeLLM:
    """把 M1/M2/M3 服务里的 model_json 换成离线假实现。"""
    from app.services import interrogate_service, match_service, parse_service

    fake = FakeLLM()
    for module in (parse_service, match_service, interrogate_service):
        monkeypatch.setattr(module, "model_json", fake)
    return fake


class _FakeResponse:
    def __init__(self, status_code: int, payload) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload

    @property
    def text(self) -> str:
        return str(self._payload)


@pytest.fixture
def apptest_client(client):
    """让前端里的 requests 走进程内 TestClient，而不是真实 8000 端口。

    返回一个工厂：调用后得到已经完成首屏渲染的 AppTest。
    """
    import types

    from streamlit.testing.v1 import AppTest

    app_path = PROJECT_ROOT / "frontend" / "streamlit_app.py"
    fake_requests = types.ModuleType("requests")

    class RequestException(Exception):
        pass

    def request(method, url, json=None, timeout=None, **_kwargs):
        # 页面里传的是 http://127.0.0.1:8000/api/...，TestClient 只吃 /api/...
        path = "/api/" + url.split("/api/", 1)[-1]
        response = client.request(method, path, json=json)
        return _FakeResponse(response.status_code, response.json())

    fake_requests.request = request
    fake_requests.RequestException = RequestException

    original = sys.modules.get("requests")
    sys.modules["requests"] = fake_requests
    try:
        def factory() -> AppTest:
            at = AppTest.from_file(app_path, default_timeout=30)
            at.run()
            return at

        yield factory
    finally:
        if original is None:
            sys.modules.pop("requests", None)
        else:
            sys.modules["requests"] = original
