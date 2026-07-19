"""
面试记录模型
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Integer, JSON, Float
from sqlalchemy.orm import relationship

from ..db.session import Base
from ..db.types import GUID


class Interview(Base):
    __tablename__ = "interviews"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    user_id = Column(GUID, ForeignKey("users.id"), nullable=False)
    company_id = Column(GUID, ForeignKey("companies.id"), nullable=True)

    position = Column(String(200))       # 面试岗位
    status = Column(String(20), default="in_progress")  # in_progress | completed | cancelled

    # 面试记录
    questions_answers = Column(JSON, default=list)  # [{question, answer, score, feedback}]
    phase = Column(String(20), default="intro")     # 当前面试阶段

    # 评分
    overall_score = Column(Float)         # 总体评分
    phase_scores = Column(JSON)           # 各阶段评分

    # 复盘报告
    review_report = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关联
    user = relationship("User", back_populates="interviews")
    company = relationship("Company", back_populates="interviews")

    def __repr__(self):
        return f"<Interview {self.id} - {self.position}>"
