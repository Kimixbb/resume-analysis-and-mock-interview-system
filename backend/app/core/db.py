from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import settings
from backend.app.core.errors import DBError
from backend.app.core.models import Base, Jd, Report, Resume

# SQLite 需要关闭线程检查：FastAPI 的同步接口跑在线程池里。
# 其他数据库类型不需要关闭线程检查。
_connect_args = (
    {"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {}
)

# 创建数据库引擎
engine = create_engine(
    settings.database_url,
    connect_args=_connect_args,
    pool_pre_ping=True, # 检查连接是否有效
)

# 创建会话工厂
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False, # 自动刷新关闭，操作中手动进行刷新
    expire_on_commit=False, # 事务提交后此对象也不过期，防止查询出错
)


@contextmanager
def get_session() -> Iterator[Session]:# 返回一个会话迭代器
    session = SessionLocal()
    try:
        yield session # 用with内部执行代码
        session.commit() # 提交事务
    except SQLAlchemyError as exc:
        session.rollback()
        raise DBError("数据库操作失败") from exc
    except Exception:
        session.rollback() #有其他异常也回滚
        raise
    finally:
        session.close()

# 创建表格
def create_all() -> None:
    Base.metadata.create_all(bind=engine)

# 删除表格
def drop_all() -> None:
    Base.metadata.drop_all(bind=engine)

# 重置表格(这些都是测试用函数）
def init_db() -> None:
    drop_all()
    create_all()


def get_report(session: Session, report_id: int) -> Report | None:
    return session.get(Report, report_id) # session会自动生成相应的sql


def get_resume(session: Session, resume_id: int) -> Resume | None:
    return session.get(Resume, resume_id)


def get_jd(session: Session, jd_id: int) -> Jd | None:
    return session.get(Jd, jd_id)

# 创建报告
def create_report(
    session: Session,
    *, # 后续参数都要给出关键字，例如：score=80,不可以直接按序传参
    resume_text: str,
    parsed_json: str,
    jd_text: str,
    req_json: str,
    score: int,
    gaps_json: str,
    risks_json: str,
) -> Report:
    resume = Resume(raw_text=resume_text, parsed_json=parsed_json) # 创建简历对象
    jd = Jd(raw_text=jd_text, req_json=req_json) # 创建职位对象
    session.add_all([resume, jd])
    session.flush()

    report = Report(# 由于主键都设置了自增属性，所以不需要手动设置，上面的也同理，flush写入数据库
        resume_id=resume.id,
        jd_id=jd.id,
        score=score,
        gaps=gaps_json,
        risks=risks_json,
    )
    session.add(report)
    session.flush()
    return report

# 更新报告重写内容
def set_report_rewrite(
    session: Session,
    report_id: int,
    rewrite_json: str
) -> Report | None:
    report = session.get(Report, report_id)
    if report is None:
        return None
    report.rewrite = rewrite_json
    return report

# 更新报告QA内容
def set_report_qa(session: Session, report_id: int, qa_json: str) -> Report | None:
    report = session.get(Report, report_id)
    if report is None:
        return None
    report.qa = qa_json
    return report
