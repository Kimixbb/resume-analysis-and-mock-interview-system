from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """基类"""


class Resume(Base):
    __tablename__ = "resume" #数据库表名

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True) #主键
    raw_text: Mapped[str] = mapped_column(Text, nullable=False) #原始文本
    parsed_json: Mapped[str] = mapped_column(Text, nullable=False) #解析后的JSON
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False) #创建时间


class Jd(Base):
    __tablename__ = "jd"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False) #原始文本
    req_json: Mapped[str] = mapped_column(Text, nullable=False) #要求的JSON
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False) #创建时间


class Report(Base):
    __tablename__ = "report"

    __table_args__ = (
        CheckConstraint("score >= 0 AND score <= 100", name="ck_report_score"), #检查约束，分数在0到100之间
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True) #主键
    resume_id: Mapped[int] = mapped_column(ForeignKey("resume.id"), nullable=False) #简历外键
    jd_id: Mapped[int] = mapped_column(ForeignKey("jd.id"), nullable=False) #职位外键
    score: Mapped[int] = mapped_column(Integer, nullable=False) #分数
    gaps: Mapped[str] = mapped_column(Text, nullable=False) #差距
    risks: Mapped[str] = mapped_column(Text, nullable=False) #风险
    qa: Mapped[str | None] = mapped_column(Text, nullable=True) #问答
    rewrite: Mapped[str | None] = mapped_column(Text, nullable=True) #重写
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False) #创建时间
